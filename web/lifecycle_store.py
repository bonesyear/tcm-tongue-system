"""记录快照、当前代恢复与保留策略；文件操作限定在调用方数据目录。"""
from __future__ import annotations

import datetime
import json
import os
import shutil
import sys
import uuid

from src.derived import current_derived_meta
from src.record import DailyRecord


BACKUP_RETENTION = 20


def _index_path(backup_dir):
    return os.path.join(backup_dir, ".index.json")


def _read_index(backup_dir):
    from io_utils import read_versioned_json
    try:
        index, _ = read_versioned_json(_index_path(backup_dir))
        if not isinstance(index, list):
            raise ValueError("备份索引不是列表")
        return [item for item in index if isinstance(item, dict)]
    except FileNotFoundError:
        return []
    except (OSError, ValueError, TypeError) as error:
        print(f"⚠️ 警告: 备份索引读取失败，按空索引重建: {error}", file=sys.stderr)
        return []


def _write_index(backup_dir, index):
    from io_utils import atomic_write_json
    atomic_write_json(_index_path(backup_dir), index)


def _write_snapshot(backup_dir, source, purpose, raw=None):
    from io_utils import atomic_write_json, write_lock
    os.makedirs(backup_dir, exist_ok=True)
    with write_lock(backup_dir):
        index = _read_index(backup_dir)
        sequence = max((item.get("sequence", 0) for item in index
                        if isinstance(item.get("sequence"), int)), default=0) + 1
        basename = os.path.basename(source)
        snapshot_id = f"{basename}.{purpose}.{sequence:08d}.{uuid.uuid4().hex[:12]}.bak"
        destination = os.path.join(backup_dir, snapshot_id)
        if raw is None:
            shutil.copyfile(source, destination)
        else:
            atomic_write_json(destination, raw)
        item = {
            "id": snapshot_id, "purpose": purpose, "sequence": sequence,
            "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(
                timespec="seconds"),
        }
        index.append(item)
        _write_index(backup_dir, index)
        return item


def _prune(filepath, backup_dir):
    from io_utils import read_versioned_json
    try:
        current, _ = read_versioned_json(filepath)
    except (OSError, ValueError, TypeError):
        current = {}
    protected = set()
    if isinstance(current, dict):
        for key in ("pristine_snapshot", "restore_state"):
            value = current.get(key, {})
            if isinstance(value, dict):
                for field in ("id", "safety_id"):
                    if isinstance(value.get(field), str):
                        protected.add(value[field])
    index = _read_index(backup_dir)
    prefix = os.path.basename(filepath) + "."
    generic = sorted((item for item in index
                      if item.get("id", "").startswith(prefix)
                      and item.get("purpose") != "pristine"),
                     key=lambda item: item.get("sequence", 0))
    remove = generic[:-BACKUP_RETENTION] if len(generic) > BACKUP_RETENTION else []
    if not remove:
        return
    removed = {item["id"] for item in remove if item["id"] not in protected}
    if not removed:
        return
    for snapshot_id in removed:
        try:
            os.unlink(os.path.join(backup_dir, snapshot_id))
        except FileNotFoundError:
            pass
    _write_index(backup_dir,
                 [item for item in index if item.get("id") not in removed])


def backup_file(filepath: str, backup_dir: str, purpose="correction") -> str:
    """按用途保留文件快照；恢复不依赖文件名或本地墙钟排序。"""
    from io_utils import write_lock
    item = _write_snapshot(backup_dir, filepath, purpose)
    with write_lock(backup_dir):
        _prune(filepath, backup_dir)
    return os.path.join(backup_dir, item["id"])


def create_pristine_snapshot(raw: dict, backup_dir: str) -> dict:
    """保存一次向导提交完成时的记录，供当前代修正前恢复。"""
    from io_utils import write_lock
    snapshot = json.loads(json.dumps(raw, ensure_ascii=False))
    snapshot.pop("pristine_snapshot", None)
    snapshot.pop("restore_state", None)
    with write_lock(backup_dir):
        record_id = snapshot.get("record_id") or f"{snapshot['date']}-web"
        return _write_snapshot(backup_dir, record_id + "_analysis.json",
                               "pristine", snapshot)


def restore_original(daily_dir: str, backup_dir: str, date_str: str,
                     timezone_name=None) -> dict:
    """恢复当前代 pristine，或撤销最近一次恢复；缺失记录时不复活。"""
    from io_utils import atomic_write_json, read_versioned_json
    import records_store
    filepath = records_store.select_daily_file(daily_dir, date_str)
    if not filepath:
        return {"ok": False, "error": f"{date_str} 无记录"}
    try:
        current, version = read_versioned_json(filepath)
    except (OSError, ValueError, TypeError) as error:
        return {"ok": False, "error": f"记录读取失败: {error}"}
    state = current.get("restore_state", {})
    undo = isinstance(state, dict) and state.get("active") is True
    if undo:
        snapshot_id = state.get("safety_id")
    else:
        pristine = current.get("pristine_snapshot", {})
        snapshot_id = pristine.get("id") if isinstance(pristine, dict) else None
    if not isinstance(snapshot_id, str) or os.path.basename(snapshot_id) != snapshot_id:
        prefix = os.path.basename(filepath) + "."
        try:
            candidates = [entry.path for entry in os.scandir(backup_dir)
                          if entry.is_file() and entry.name.startswith(prefix)
                          and entry.name.endswith(".bak")]
        except OSError:
            candidates = []
        if not candidates:
            return {"ok": False, "error": "当前代没有可恢复的修正前快照（未被修正或快照缺失）"}
        snapshot_id = os.path.basename(max(candidates, key=os.path.getmtime))
    snapshot_path = os.path.join(backup_dir, snapshot_id)
    try:
        restored, _ = read_versioned_json(snapshot_path)
    except (OSError, ValueError, TypeError) as error:
        return {"ok": False, "error": f"快照读取失败: {error}"}
    if not isinstance(restored, dict):
        return {"ok": False, "error": "快照根节点不是对象"}
    diagnosis = current.get("diagnosis")
    if isinstance(diagnosis, dict) and isinstance(diagnosis.get("report"), dict):
        restored["diagnosis"] = diagnosis
    if "pattern_differentiation" in current:
        restored["pattern_differentiation"] = current["pattern_differentiation"]
    if isinstance(current.get("pristine_snapshot"), dict):
        restored["pristine_snapshot"] = current["pristine_snapshot"]
    safety = records_store.backup_file(filepath, backup_dir, purpose="restore")
    restored["restore_state"] = {"active": not undo,
                                 "safety_id": os.path.basename(safety)}
    restored["manually_corrected"] = True
    import time_utils
    restored["corrected_at"] = time_utils.iso_now(timezone_name)
    audit = restored.get("restore_audit", [])
    if not isinstance(audit, list):
        return {"ok": False, "error": "restore_audit 格式错误"}
    audit.append({
        "action": "undo" if undo else "restore", "snapshot_id": snapshot_id,
        "safety_id": os.path.basename(safety), "sequence": len(audit) + 1,
        "at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
    })
    restored["restore_audit"] = audit
    restored["derived_meta"] = current_derived_meta(DailyRecord(restored))
    errors, warnings = records_store.validate_candidate(
        restored, daily_dir, previous_raw=current)
    if errors:
        return {"ok": False, "errors": errors, "warnings": warnings}
    atomic_write_json(filepath, restored, version)
    return {"ok": True, "restored_from": snapshot_id,
            "safety_backup": os.path.basename(safety),
            "undo": undo, "warnings": warnings}


def _remove_photo_tree(path):
    from io_utils import write_lock
    if not os.path.isdir(path):
        return
    with write_lock(path):
        for root, dirs, files in os.walk(path, topdown=False):
            for name in files:
                if name != ".write.lock":
                    os.unlink(os.path.join(root, name))
            for name in dirs:
                os.rmdir(os.path.join(root, name))
    lock_file = os.path.join(path, ".write.lock")
    if os.path.exists(lock_file):
        os.unlink(lock_file)
    os.rmdir(path)


def delete_day(daily_dir: str, backup_dir: str, photos_dir: str,
               date_str: str, confirmed=False) -> dict:
    """管理员明确确认后删除当日关联数据；不允许恢复已删除内容。"""
    from io_utils import file_version, write_lock
    from date_utils import parse_date
    import records_store
    if confirmed is not True:
        return {"ok": False, "error": "必须明确确认 DELETE"}
    if parse_date(date_str) is None:
        return {"ok": False, "error": "非法日期"}
    filepath = records_store.select_daily_file(daily_dir, date_str)
    basename = os.path.basename(filepath) if filepath else f"{date_str}_analysis.json"
    version = file_version(filepath) if filepath else None
    with write_lock(daily_dir):
        if filepath and file_version(filepath) != version:
            from io_utils import WriteConflictError
            raise WriteConflictError(filepath)
        if filepath:
            os.unlink(filepath)
        for entry in os.scandir(daily_dir):
            if entry.is_file() and entry.name.startswith(f".wizard-{date_str}.json"):
                os.unlink(entry.path)
    index = _read_index(backup_dir)
    prefix = basename + "."
    for item in index:
        snapshot_id = item.get("id", "")
        if snapshot_id.startswith(prefix) and os.path.basename(snapshot_id) == snapshot_id:
            path = os.path.join(backup_dir, snapshot_id)
            if os.path.isfile(path):
                os.unlink(path)
    _write_index(backup_dir, [item for item in index
                             if not item.get("id", "").startswith(prefix)])
    if os.path.isdir(backup_dir):
        for entry in os.scandir(backup_dir):
            if entry.is_file() and entry.name.startswith(prefix) \
                    and entry.name.endswith(".bak"):
                os.unlink(entry.path)
    _remove_photo_tree(os.path.join(photos_dir, date_str))
    backup_photos = os.path.join(backup_dir, "photos", date_str)
    if os.path.isdir(backup_photos):
        shutil.rmtree(backup_photos)
    return {"ok": True, "deleted": date_str}
