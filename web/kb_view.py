"""可重建的统一知识库视图；只复制语料，不修改任何来源根。"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile
import time

from io_utils import write_lock
from src import paths
from src.retrieval import (
    KB_CATEGORY_DEFS, invalidate_kb_caches, list_kb_files, synonym_loader,
)
from src.retrieval.synonym_loader import (
    MAX_SYNONYM_KEYS, MAX_SYNONYM_TERM_CHARS, MAX_SYNONYMS_PER_KEY,
)

_VIEW_SCHEMA = 1
_CACHE_MARKER = ".kb-unified-cache-v1"
_MAX_CACHED_VIEWS = 8
_RETIRE_SECONDS = 3600
_VIEW_NAME = re.compile(r"^[0-9a-f]{64}$")
_STAGING_NAME = re.compile(r"^\.[0-9a-f]{64}\.staging-[A-Za-z0-9_]+$")


def category_for_shared_file(relative, active):
    first = relative.replace("\\", "/").split("/", 1)[0]
    for category, directory in (("constitution", "diagnostics"),
                                ("diet", "diet-lifestyle"), ("formula", "formulas")):
        if first == directory:
            return category
    if len(active) < len(KB_CATEGORY_DEFS):
        raise ValueError(f"共享综合知识库文件无法确定类别: {relative}；"
                         "缺类时请按 diagnostics/、diet-lifestyle/、formulas/ 分类"
                         "或改用分类专用根")
    return "composite"


def _build_view(active, view):
    distinct_roots = list(dict.fromkeys(active.values()))
    shared = {root for root in distinct_roots
              if list(active.values()).count(root) > 1}
    ordered_roots = sorted(distinct_roots,
                           key=lambda root: (root not in shared,
                                             distinct_roots.index(root)))
    owners = {}
    merged_map = {}
    for root in ordered_roots:
        root_path = Path(root)
        for source in root_path.rglob("*"):
            if not source.is_file() or source.suffix.lower() != ".md" \
                    or source.name == "README.md":
                continue
            relative = source.relative_to(root_path).as_posix()
            if root in shared:
                owner = category_for_shared_file(relative, active)
                if owner != "composite" and active.get(owner) != root:
                    continue
            else:
                owner = next(category for category, value in active.items()
                             if value == root)
            target = view / relative
            try:
                if target.exists():
                    if not target.is_file():
                        raise ValueError(f"知识库路径类型冲突: {relative}")
                    if target.read_bytes() != source.read_bytes():
                        raise ValueError(f"重复且内容冲突的知识库文件: {relative}")
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, target)
            except (FileExistsError, NotADirectoryError, IsADirectoryError) as error:
                raise ValueError(f"知识库路径类型冲突: {relative}") from error
            owners[relative] = owner
        map_path = root_path / "synonym_map.yaml"
        if map_path.is_file():
            for key, values in synonym_loader.load_map(str(map_path)).items():
                aliases = merged_map.setdefault(key, [])
                for value in values:
                    if value not in aliases:
                        aliases.append(value)
    if len(merged_map) > MAX_SYNONYM_KEYS or any(
            len(values) > MAX_SYNONYMS_PER_KEY for values in merged_map.values()):
        raise ValueError("统一别名词典超过现有键或别名数量上限")
    return owners, merged_map


def _file_digest(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _view_key(active):
    roots = []
    for category, root in active.items():
        files = []
        for filename in list_kb_files(root):
            path = Path(filename)
            files.append([path.relative_to(root).as_posix(), _file_digest(path)])
        map_path = Path(root) / "synonym_map.yaml"
        if map_path.is_file():
            files.append(["synonym_map.yaml", _file_digest(map_path)])
        roots.append([category, root, files])
    payload = json.dumps({"schema": _VIEW_SCHEMA, "roots": roots},
                         ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _valid_relative(value):
    if not isinstance(value, str) or not value or "\\" in value:
        return False
    path = PurePosixPath(value)
    return not path.is_absolute() and ".." not in path.parts and path.as_posix() == value


def _load_view(view, key):
    try:
        manifest = json.loads((view / "view.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        return None
    if not isinstance(manifest, dict) \
            or manifest.get("schema") != _VIEW_SCHEMA or manifest.get("key") != key:
        return None
    owners = manifest.get("owners")
    aliases = manifest.get("aliases")
    if not isinstance(owners, dict) or not isinstance(aliases, dict):
        return None
    allowed = set(KB_CATEGORY_DEFS) | {"composite"}
    if any(not _valid_relative(relative) or not isinstance(category, str)
           or category not in allowed for relative, category in owners.items()):
        return None
    files = {Path(filename).relative_to(view).as_posix()
             for filename in list_kb_files(str(view))}
    if files != set(owners):
        return None
    if len(aliases) > MAX_SYNONYM_KEYS:
        return None
    for term, values in aliases.items():
        if not isinstance(term, str) or len(term) > MAX_SYNONYM_TERM_CHARS \
                or not isinstance(values, list) \
                or len(values) > MAX_SYNONYMS_PER_KEY \
                or any(not isinstance(value, str) or len(value) > MAX_SYNONYM_TERM_CHARS
                       for value in values):
            return None
    return owners, aliases


def _remove_path(path):
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)


def _cleanup_staging(root):
    for path in root.iterdir():
        if _STAGING_NAME.fullmatch(path.name) and path.is_dir() \
                and not path.is_symlink():
            shutil.rmtree(path)


def _prune(root, current=None):
    views = [path for path in root.iterdir()
             if _VIEW_NAME.fullmatch(path.name) and path.is_dir()
             and not path.is_symlink() and _load_view(path, path.name) is not None]
    others = sorted((path for path in views if path != current),
                    key=lambda path: path.stat().st_mtime, reverse=True)
    keep = max(0, _MAX_CACHED_VIEWS - (1 if current is not None else 0))
    for path in others[keep:]:
        invalidate_kb_caches(str(path))
        if time.time() - path.stat().st_mtime >= _RETIRE_SECONDS:
            _remove_path(path)


def _cache_root(cache_root):
    if cache_root is not None:
        return Path(cache_root).resolve()
    return (Path(paths.DATA_ROOT) / "cache" / "kb-unified").resolve()


def _overlaps_sources(root, active):
    def inside(parent, child):
        try:
            return os.path.commonpath((str(parent), str(child))) == str(parent)
        except ValueError:
            return False

    return any(inside(Path(source).resolve(), root) or inside(root, Path(source).resolve())
               for source in active.values())


@contextmanager
def unified_view(active, cache_root=None):
    root = _cache_root(cache_root)
    if _overlaps_sources(root, active):
        with tempfile.TemporaryDirectory(prefix="kb-unified-") as temporary:
            view = Path(temporary)
            try:
                owners, aliases = _build_view(active, view)
                yield str(view), owners, aliases
            finally:
                invalidate_kb_caches(str(view))
        return

    root.mkdir(parents=True, exist_ok=True)
    with write_lock(str(root)):
        marker = root / _CACHE_MARKER
        if not marker.exists():
            marker.write_text("1\n", encoding="utf-8")
        _cleanup_staging(root)
        key = _view_key(active)
        view = root / key
        loaded = _load_view(view, key)
        if loaded is None:
            if view.exists() or view.is_symlink():
                _remove_path(view)
            staging = Path(tempfile.mkdtemp(prefix=f".{key}.staging-", dir=root))
            try:
                owners, aliases = _build_view(active, staging)
                if _view_key(active) != key:
                    raise ValueError("知识库在统一视图构建期间已变化，请重试")
                manifest = {"schema": _VIEW_SCHEMA, "key": key,
                            "owners": owners, "aliases": aliases}
                (staging / "view.json").write_text(
                    json.dumps(manifest, ensure_ascii=False, sort_keys=True), encoding="utf-8")
                os.replace(staging, view)
            finally:
                if staging.exists():
                    shutil.rmtree(staging)
            loaded = owners, aliases
        os.utime(view, None)
        _prune(root, current=view)
    yield str(view), *loaded


def cleanup_unified_view_cache(cache_root=None):
    root = _cache_root(cache_root)
    marker = root / _CACHE_MARKER
    if not root.is_dir() or not marker.is_file():
        return
    with write_lock(str(root)):
        if not marker.is_file():
            return
        _cleanup_staging(root)
        _prune(root)
