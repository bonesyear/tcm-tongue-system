"""受限 ZIP 知识库导入；只覆盖导入副本，不修改外部原始知识库。"""
from __future__ import annotations

import io
import os
from pathlib import PurePosixPath
import shutil
import stat
import uuid
import zipfile

from src.retrieval import invalidate_kb_caches
from src.retrieval.kb_paths import resolve_kb_root
from src.retrieval.synonym_loader import load_map

MAX_UPLOAD_BYTES = 8 * 1024 * 1024
MAX_FILES = 32
MAX_FILE_BYTES = 4 * 1024 * 1024
MAX_TOTAL_BYTES = 32 * 1024 * 1024
MAX_COMPRESSION_RATIO = 200
_ALLOWED_SUFFIXES = {".md", ".yaml", ".yml"}
_ALLOWED_COMPRESSION = {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}


def _entry_path(info):
    name = info.filename
    if not name or len(name) > 240 or "\\" in name or ":" in name or "\x00" in name:
        raise ValueError("压缩包包含不安全的文件路径")
    path = PurePosixPath(name)
    if path.is_absolute() or any(part in ("", ".", "..") or part.startswith(".")
                                 for part in path.parts):
        raise ValueError("压缩包包含不安全的文件路径")
    if path.suffix.lower() not in _ALLOWED_SUFFIXES:
        raise ValueError("只支持 Markdown/YAML 知识库文件")
    mode = info.external_attr >> 16
    kind = stat.S_IFMT(mode)
    if stat.S_ISLNK(mode) or (kind and kind != stat.S_IFREG):
        raise ValueError("压缩包不能包含链接或特殊文件")
    if info.flag_bits & 1 or info.compress_type not in _ALLOWED_COMPRESSION:
        raise ValueError("不支持加密或特殊压缩格式")
    if info.file_size > MAX_FILE_BYTES:
        raise ValueError("单个知识库文件超过 4 MiB 上限")
    if info.file_size / max(info.compress_size, 1) > MAX_COMPRESSION_RATIO:
        raise ValueError("压缩包压缩比异常，已停止导入")
    return path


def _extract(data, staging):
    total = 0
    count = 0
    has_markdown = False
    seen = set()
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        if len(archive.infolist()) > 64:
            raise ValueError("压缩包条目过多")
        for info in archive.infolist():
            if info.is_dir():
                continue
            path = _entry_path(info)
            key = path.as_posix().casefold()
            if key in seen:
                raise ValueError("压缩包包含重复或大小写冲突的文件名")
            seen.add(key)
            count += 1
            if count > MAX_FILES:
                raise ValueError("知识库文件数量超过 32 个上限")
            target = os.path.join(staging, *path.parts)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with archive.open(info) as source, open(target, "xb") as output:
                while True:
                    chunk = source.read(64 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > MAX_TOTAL_BYTES:
                        raise ValueError("知识库展开后超过 32 MiB 上限")
                    output.write(chunk)
            with open(target, "rb") as extracted:
                text = extracted.read().decode("utf-8-sig")
            if path.suffix.lower() == ".md" and text.strip():
                has_markdown = True
    if not has_markdown:
        raise ValueError("压缩包没有可用的 Markdown 知识库内容")
    return count


_MANIFEST_FIELDS = {"schema_version", "category", "name", "source", "license"}


def _validate_manifest(staging, category):
    path = os.path.join(staging, "kb.yaml")
    if not os.path.isfile(path):
        if category != "composite":
            raise ValueError("分类 ZIP 必须包含 kb.yaml 类别清单")
        return
    if os.path.getsize(path) > 16 * 1024:
        raise ValueError("kb.yaml 类别清单过大")
    with open(path, encoding="utf-8-sig") as handle:
        lines = handle.read().splitlines()
    data = {}
    for raw in lines:
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        text = raw.split(" #", 1)[0].rstrip()
        key, separator, value = text.partition(":")
        key = key.strip()
        if not separator or key not in _MANIFEST_FIELDS or key in data:
            raise ValueError("kb.yaml 含不支持或重复的字段")
        value = value.strip()
        if not value:
            raise ValueError(f"kb.yaml 的 {key} 不能为空")
        data[key] = value
    if data.get("schema_version") != "1":
        raise ValueError("kb.yaml 必须声明 schema_version: 1")
    if data.get("category") != category:
        raise ValueError(f"kb.yaml 类别必须为 {category}")


def _restore_directory(final, backup, failed, has_previous):
    if os.path.lexists(final):
        os.replace(final, failed)
    if has_previous:
        os.replace(backup, final)


def _preserve_composite_categories(staging, final, preserve):
    from src.retrieval import KB_CATEGORY_DEFS
    for category in KB_CATEGORY_DEFS:
        if os.path.exists(os.path.join(staging, category)):
            raise ValueError("综合包不能包含系统分类目录，请改用分类导入")
        source = os.path.join(final, category)
        if os.path.isdir(source):
            shutil.copytree(source, os.path.join(preserve, category))


def _restore_composite_categories(final, preserve):
    from src.retrieval import KB_CATEGORY_DEFS
    for category in KB_CATEGORY_DEFS:
        source = os.path.join(preserve, category)
        if os.path.isdir(source):
            os.replace(source, os.path.join(final, category))


def import_kb(upload, data_root, env_path, env_locked=False, write_env=None,
              category="composite"):
    """完整校验后替换指定类别的导入副本，不修改其他类别或外部原库。"""
    from src.retrieval.kb_status import kb_env_key
    env_key = kb_env_key(category)
    data = upload.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise ValueError("ZIP 文件超过 8 MiB 上限")
    data_root = os.path.abspath(data_root)
    final = os.path.join(data_root, "private_kb") if category == "composite" \
        else os.path.join(data_root, "private_kb", category)
    if os.path.lexists(final) and (not os.path.isdir(final) or os.path.islink(final)):
        raise ValueError("导入副本路径必须是普通目录")
    staging_root = os.path.join(data_root, ".kb-staging")
    os.makedirs(staging_root, exist_ok=True)
    identity = uuid.uuid4().hex
    staging = os.path.join(staging_root, identity)
    backup = os.path.join(data_root, f".kb-backup-{identity}")
    failed = os.path.join(data_root, f".kb-failed-{identity}")
    preserve = os.path.join(data_root, f".kb-preserve-{identity}")
    os.makedirs(staging)
    try:
        try:
            archive = io.BytesIO(data)
            if not zipfile.is_zipfile(archive):
                raise ValueError("请上传有效的 ZIP 文件")
            archive.close()
            count = _extract(data, staging)
            map_path = os.path.join(staging, "synonym_map.yaml")
            if os.path.isfile(map_path):
                load_map(map_path)
            _validate_manifest(staging, category)
        except (zipfile.BadZipFile, UnicodeError) as error:
            raise ValueError(f"知识库 ZIP 或文本编码无效: {error}") from error

        os.makedirs(os.path.dirname(final), exist_ok=True)
        if category == "composite":
            _preserve_composite_categories(staging, final, preserve)
        has_previous = os.path.exists(final)
        if has_previous:
            os.replace(final, backup)
        try:
            os.replace(staging, final)
            if category == "composite":
                _restore_composite_categories(final, preserve)
        except Exception:
            _restore_directory(final, backup, failed, has_previous)
            raise
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        shutil.rmtree(preserve, ignore_errors=True)
        raise
    shutil.rmtree(preserve, ignore_errors=True)

    if not env_locked:
        from kb_config_tx import read_config_bytes, restore_config_bytes
        from src.retrieval.kb_status import kb_disabled_key
        previous_config = read_config_bytes(env_path)
        updates = {env_key: final, kb_disabled_key(category): ""}
        try:
            write_env(env_path, updates)
        except Exception as error:
            config_rollback_error = None
            try:
                restore_config_bytes(env_path, previous_config)
            except Exception as rollback_error:
                config_rollback_error = rollback_error
            try:
                _restore_directory(final, backup, failed, has_previous)
            except OSError as restore_error:
                raise OSError(
                    f"配置写回及导入副本恢复均失败: {restore_error}；"
                    f"旧副本: {backup}；新副本: {failed}") from restore_error
            invalidate_kb_caches(final)
            if config_rollback_error is not None:
                raise OSError(
                    f"{env_key} 写回失败，且配置回滚失败: {config_rollback_error}；"
                    "目录已恢复，请检查 .env 实际内容") from error
            return {"ok": False, "root": final, "category": category,
                    "error": f"{env_key} 写回失败，已恢复原导入状态: {error}"}
    if has_previous:
        shutil.rmtree(backup)
    invalidate_kb_caches(final)
    from src.retrieval.grep_search import list_kb_files
    return {"ok": True, "root": final, "count": count, "category": category,
            "configured": not env_locked, "kb_root": resolve_kb_root(final),
            "markdown_count": len(list_kb_files(final))}
