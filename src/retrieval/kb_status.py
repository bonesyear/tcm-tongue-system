"""知识库可用状态与轻量版本签名；仅使用标准库。"""
from __future__ import annotations

import hashlib
import os

from .grep_search import list_kb_files
from .kb_paths import kb_map_path, resolve_kb_root


_UNSET = object()


def inspect_kb(kb_root=_UNSET):
    """返回知识库状态；无参数可读环境默认，显式空值表示未配置。"""
    info = {"root": "", "status": "unconfigured", "file_count": 0,
            "revision": "", "error": ""}
    if kb_root is _UNSET:
        configured = bool(os.environ.get("TCM_KB_ROOT"))
        root = resolve_kb_root()
    else:
        if not kb_root:
            return info
        configured = True
        root = resolve_kb_root(kb_root)
    info["root"] = root
    if not os.path.isdir(root):
        if configured:
            info.update(status="error", error="知识库目录不存在或不是目录")
        return info
    try:
        with os.scandir(root):
            pass
        files = list_kb_files(root)
        if not files:
            info["status"] = "empty" if configured else "unconfigured"
            return info
        paths = list(files)
        map_path = kb_map_path(root)
        if os.path.isfile(map_path):
            paths.append(map_path)
        digest = hashlib.sha256()
        for path in sorted(paths):
            stat = os.stat(path)
            relative = os.path.relpath(path, root).replace(os.sep, "/")
            digest.update(relative.encode("utf-8"))
            digest.update(b"\0")
            digest.update(str(stat.st_size).encode("ascii"))
            digest.update(b"\0")
            digest.update(str(stat.st_mtime_ns).encode("ascii"))
            digest.update(b"\0")
        info.update(status="ready", file_count=len(files),
                    revision=digest.hexdigest())
    except OSError as error:
        info.update(status="error", error=str(error), revision="")
    return info


KB_CATEGORIES_DISABLED_KEY = "TCM_KB_CATEGORIES_DISABLED"
KB_COMPOSITE_DISABLED_KEY = "TCM_KB_COMPOSITE_DISABLED"

KB_CATEGORY_DEFS = {
    "constitution": {"label": "中医体质辨证知识库",
                     "env_key": "TCM_KB_CONSTITUTION_ROOT",
                     "disabled_key": "TCM_KB_CONSTITUTION_DISABLED"},
    "diet": {"label": "食疗知识库", "env_key": "TCM_KB_DIET_ROOT",
             "disabled_key": "TCM_KB_DIET_DISABLED"},
    "formula": {"label": "方剂知识库", "env_key": "TCM_KB_FORMULA_ROOT",
                "disabled_key": "TCM_KB_FORMULA_DISABLED"},
}


def kb_env_key(category):
    if category == "composite":
        return "TCM_KB_ROOT"
    if category not in KB_CATEGORY_DEFS:
        raise ValueError("未知知识库类别")
    return KB_CATEGORY_DEFS[category]["env_key"]


def kb_disabled_key(category):
    if category == "composite":
        return KB_COMPOSITE_DISABLED_KEY
    if category not in KB_CATEGORY_DEFS:
        raise ValueError("未知知识库类别")
    return KB_CATEGORY_DEFS[category]["disabled_key"]


def _config_value(config, key):
    if config is None:
        return os.environ.get(key)
    if callable(config):
        return config(key)
    return config.get(key)


def _external_allowed(config):
    return _config_value(config, "TCM_KB_ALLOW_EXTERNAL_KB") == "1"


def _managed_root(category, config):
    data_root = _config_value(config, "TCM_DATA_ROOT")
    if not data_root:
        from src import paths
        data_root = paths.DATA_ROOT
    data_root = resolve_kb_root(data_root)
    return os.path.join(data_root, "private_kb") if category == "composite" \
        else os.path.join(data_root, "private_kb", category)


def _is_managed_root(category, root, config):
    return bool(root) and os.path.abspath(root) == _managed_root(category, config)


def kb_legacy_root(config=None):
    """综合根须未停用，且明确允许外部根或为程序管理副本。"""
    if _config_value(config, KB_COMPOSITE_DISABLED_KEY) == "1":
        return None
    root = _config_value(config, "TCM_KB_ROOT")
    if root and (_external_allowed(config) or _is_managed_root("composite", root, config)):
        return root
    return None


def kb_category_root(category, config=None):
    """整组与自身停用优先；专用根优先于综合回退。"""
    if category == "composite":
        return kb_legacy_root(config)
    if _config_value(config, KB_CATEGORIES_DISABLED_KEY) == "1" \
            or _config_value(config, kb_disabled_key(category)) == "1":
        return None
    specific = _config_value(config, kb_env_key(category))
    if specific:
        return specific if _external_allowed(config) \
            or _is_managed_root(category, specific, config) else None
    strict = _config_value(config, "TCM_KB_STRICT_CATEGORIES") == "1"
    return None if strict else kb_legacy_root(config)


def inspect_kb_categories(config=None):
    """区分整组与自身停用；有效停用优先于专用根和综合回退。"""
    strict = _config_value(config, "TCM_KB_STRICT_CATEGORIES") == "1"
    group_disabled = _config_value(config, KB_CATEGORIES_DISABLED_KEY) == "1"
    result = {}
    for category, definition in KB_CATEGORY_DEFS.items():
        specific = _config_value(config, definition["env_key"])
        self_disabled = _config_value(config, definition["disabled_key"]) == "1"
        disabled = group_disabled or self_disabled
        root = kb_category_root(category, config)
        if disabled or root is None:
            info = {"root": root or "", "status": "unconfigured",
                    "file_count": 0, "revision": "", "error": ""}
        else:
            info = inspect_kb(root)
        info.update(category=category, label=definition["label"],
                    env_key=definition["env_key"], disabled=disabled,
                    self_disabled=self_disabled, group_disabled=group_disabled,
                    legacy=not specific and not strict and not disabled and bool(root))
        result[category] = info
    return result
