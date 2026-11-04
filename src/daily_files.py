"""每日记录文件的一次扫描、副本排除与按日期选档。"""
from __future__ import annotations

import os
import re
import sys
import threading


_DAILY_FILE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}).*analysis.*\.json$", re.IGNORECASE)
SUSPECT_ARCHIVE_RE = re.compile(
    r"\.bak(?:\.|$)|copy|tmp|_旧格式|副本|备份|快照|_backup(?=[^a-z0-9]|$)"
    r"|\(\d+\)\s*\.json$", re.IGNORECASE)
_CACHE: dict[str, tuple[tuple[int, int], dict[str, list[tuple]]]] = {}
_LOCK = threading.RLock()


def _scan_daily_dir(daily_dir: str) -> dict[str, list[tuple]]:
    grouped: dict[str, list[tuple]] = {}
    try:
        entries = sorted(os.scandir(daily_dir), key=lambda entry: entry.name)
    except FileNotFoundError:
        return grouped
    except OSError as error:
        print(f"⚠️ 警告: 记录目录读取失败 {daily_dir}: {error}", file=sys.stderr)
        return grouped
    for entry in entries:
        try:
            if not entry.is_file(follow_symlinks=False):
                continue
            match = _DAILY_FILE_RE.match(entry.name)
            if not match or SUSPECT_ARCHIVE_RE.search(entry.name):
                continue
            stat = entry.stat(follow_symlinks=False)
            grouped.setdefault(match.group(1), []).append(
                (entry.path, entry.name, stat.st_mtime_ns, stat.st_size))
        except OSError as error:
            print(f"⚠️ 警告: 跳过无法访问的记录文件 {entry.path}: {error}", file=sys.stderr)
    return grouped


def _directory_signature(daily_dir: str) -> tuple[int, int]:
    try:
        stat = os.stat(daily_dir)
        return stat.st_mtime_ns, stat.st_size
    except OSError:
        return 0, 0


def daily_files(daily_dir: str) -> dict[str, list[tuple]]:
    """返回日期到候选文件的映射；只缓存目录结构，不缓存记录内容。"""
    root = os.path.abspath(daily_dir)
    signature = _directory_signature(root)
    cached = _CACHE.get(root)
    if cached and cached[0] == signature:
        return cached[1]
    with _LOCK:
        cached = _CACHE.get(root)
        if cached and cached[0] == signature:
            return cached[1]
        grouped = _scan_daily_dir(root)
        _CACHE[root] = (_directory_signature(root), grouped)
        return grouped


def select_daily_file(daily_dir: str, date_str: str) -> str | None:
    """规范名优先；否则取 mtime 最新的非副本文件并明确告警。"""
    candidates = daily_files(daily_dir).get(date_str, [])
    # 扫描结果统一为绝对路径；相对目录调用也必须识别规范正档。
    exact = os.path.join(os.path.abspath(daily_dir), f"{date_str}_analysis.json")
    for candidate in candidates:
        if candidate[0] == exact:
            return exact
    if not candidates:
        return None
    chosen = max(candidates, key=lambda item: item[2])
    if len(candidates) > 1:
        print(f"⚠️ 警告: {date_str} 有多份非规范命名的 analysis 候选: "
              f"{sorted(item[1] for item in candidates)}；"
              f"选用 mtime 最新者 {chosen[1]}", file=sys.stderr)
    return chosen[0]
