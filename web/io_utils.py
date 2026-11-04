"""UTF-8 文本与 JSON 的临时文件、版本检查与原子替换工具。"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
import tempfile
import threading


VERSION_NOT_PROVIDED = object()


class WriteConflictError(RuntimeError):
    def __init__(self, path):
        self.path = os.fspath(path)
        super().__init__("文件已被其他操作更新，请刷新后重试")


_THREAD_LOCK = threading.RLock()
_LOCK_STATE = threading.local()


def _os_lock(handle):
    if os.name == "nt":
        import msvcrt
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
    else:
        import fcntl
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)


def _os_unlock(handle):
    if os.name == "nt":
        import msvcrt
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def write_lock(directory):
    """同目录可重入的线程/进程写锁；独立锁文件不随目标替换。"""
    root = os.path.abspath(os.fspath(directory))
    depth = getattr(_LOCK_STATE, "depth", 0)
    if depth:
        if _LOCK_STATE.root != root:
            raise RuntimeError("不能嵌套不同目录的写锁")
        _LOCK_STATE.depth = depth + 1
        try:
            yield
        finally:
            _LOCK_STATE.depth = depth
        return
    with _THREAD_LOCK:
        os.makedirs(root, exist_ok=True)
        with open(os.path.join(root, ".write.lock"), "a+b") as handle:
            _os_lock(handle)
            _LOCK_STATE.root = root
            _LOCK_STATE.depth = 1
            try:
                yield
            finally:
                _LOCK_STATE.depth = 0
                _os_unlock(handle)


def file_version(path) -> str | None:
    try:
        with open(path, "rb") as handle:
            data = handle.read()
    except FileNotFoundError:
        return None
    return hashlib.sha256(data).hexdigest()


def read_versioned_json(path):
    with open(path, "rb") as handle:
        data = handle.read()
    return json.loads(data.decode("utf-8")), hashlib.sha256(data).hexdigest()


def _check_version(path, expected_version):
    if expected_version is not VERSION_NOT_PROVIDED \
            and file_version(path) != expected_version:
        raise WriteConflictError(path)


def _write_temp(path, writer) -> str:
    directory = os.path.dirname(os.path.abspath(os.fspath(path)))
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            writer(f)
            f.flush()
            os.fsync(f.fileno())
        return tmp
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def write_temp_json(path, raw) -> str:
    return _write_temp(path, lambda f: json.dump(
        raw, f, ensure_ascii=False, indent=2))


def _replace_temp(tmp: str, path, expected_version=VERSION_NOT_PROVIDED) -> None:
    try:
        with write_lock(os.path.dirname(os.path.abspath(os.fspath(path)))):
            _check_version(path, expected_version)
            os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def atomic_write_text(path, text: str, expected_version=VERSION_NOT_PROVIDED) -> None:
    tmp = _write_temp(path, lambda f: f.write(text))
    _replace_temp(tmp, path, expected_version)


def atomic_write_json(path, raw, expected_version=VERSION_NOT_PROVIDED) -> None:
    tmp = write_temp_json(path, raw)
    _replace_temp(tmp, path, expected_version)


def remove_file(path, expected_version=VERSION_NOT_PROVIDED) -> None:
    with write_lock(os.path.dirname(os.path.abspath(os.fspath(path)))):
        _check_version(path, expected_version)
        os.unlink(path)


def atomic_write_bytes(path, data: bytes, expected_version=VERSION_NOT_PROVIDED) -> None:
    directory = os.path.dirname(os.path.abspath(os.fspath(path)))
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=directory)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        _replace_temp(tmp, path, expected_version)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
