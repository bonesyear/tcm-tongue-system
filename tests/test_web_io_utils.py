"""Web 文件写入的原子性、临时文件隔离与版本冲突。"""
from concurrent.futures import ThreadPoolExecutor
import multiprocessing
import os
import sys

import pytest

pytest.importorskip("flask")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "web"))

import io_utils  # noqa: E402


def _thread_competing_write(path, value, expected, barrier):
    barrier.wait(timeout=10)
    try:
        io_utils.atomic_write_json(path, {"value": value}, expected)
        return "written"
    except io_utils.WriteConflictError:
        return "conflict"


def _process_competing_write(path, value, expected, start, results):
    start.wait(10)
    try:
        io_utils.atomic_write_json(path, {"value": value}, expected)
        results.put("written")
    except io_utils.WriteConflictError:
        results.put("conflict")


def test_stale_version_preserves_current_file_and_cleans_temp(tmp_path):
    target = tmp_path / "record.json"
    io_utils.atomic_write_json(target, {"value": "base"})
    expected = io_utils.file_version(target)
    io_utils.atomic_write_json(target, {"value": "external"})

    with pytest.raises(io_utils.WriteConflictError):
        io_utils.atomic_write_json(target, {"value": "stale"}, expected)

    assert io_utils.read_versioned_json(target)[0] == {"value": "external"}
    assert list(tmp_path.glob(".tmp-*")) == []


def test_write_lock_is_reentrant_for_record_and_draft(tmp_path):
    target = tmp_path / "record.json"
    draft = tmp_path / ".wizard.json"
    with io_utils.write_lock(tmp_path):
        io_utils.atomic_write_json(target, {"value": "record"}, None)
        io_utils.atomic_write_json(draft, {"value": "draft"}, None)
        io_utils.remove_file(draft, io_utils.file_version(draft))
    assert target.exists() and not draft.exists()


def test_threads_with_same_version_only_allow_one_write(tmp_path):
    target = tmp_path / "record.json"
    io_utils.atomic_write_json(target, {"value": "base"})
    expected = io_utils.file_version(target)
    import threading
    barrier = threading.Barrier(2)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(
            lambda value: _thread_competing_write(str(target), value, expected, barrier),
            ("first", "second")))
    assert sorted(results) == ["conflict", "written"]
    assert io_utils.read_versioned_json(target)[0]["value"] in ("first", "second")


def test_processes_with_same_version_only_allow_one_write(tmp_path):
    target = tmp_path / "record.json"
    io_utils.atomic_write_json(target, {"value": "base"})
    expected = io_utils.file_version(target)
    ctx = multiprocessing.get_context("spawn")
    start = ctx.Event()
    results = ctx.Queue()
    processes = [ctx.Process(target=_process_competing_write,
                            args=(str(target), value, expected, start, results))
                 for value in ("first", "second")]
    for process in processes:
        process.start()
    start.set()
    for process in processes:
        process.join(15)
        if process.is_alive():
            process.terminate()
            process.join()
    assert all(process.exitcode == 0 for process in processes)
    outcomes = sorted(results.get(timeout=2) for _ in processes)
    results.close()
    results.join_thread()
    assert outcomes == ["conflict", "written"]
    assert io_utils.read_versioned_json(target)[0]["value"] in ("first", "second")


def test_atomic_write_json_preserves_original_on_error(tmp_path):
    target = tmp_path / "record.json"
    target.write_text('{"old": true}', encoding="utf-8")

    with pytest.raises(TypeError):
        io_utils.atomic_write_json(target, {"bad": object()})

    assert target.read_text(encoding="utf-8") == '{"old": true}'
    assert list(tmp_path.glob(".tmp-*")) == []


def test_atomic_write_text_replaces_content(tmp_path):
    target = tmp_path / ".env"
    io_utils.atomic_write_text(target, "A=1\n")
    io_utils.atomic_write_text(target, "A=2\n")

    assert target.read_text(encoding="utf-8") == "A=2\n"
    assert list(tmp_path.glob(".tmp-*")) == []


def test_write_temp_json_uses_unique_paths(tmp_path):
    target = tmp_path / "record.json"
    first = io_utils.write_temp_json(target, {"value": 1})
    second = io_utils.write_temp_json(target, {"value": 2})
    try:
        assert first != second
        assert not os.path.exists(target)
    finally:
        os.unlink(first)
        os.unlink(second)
