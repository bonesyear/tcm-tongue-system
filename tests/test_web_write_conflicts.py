"""记录与草稿的并发写冲突及真实 Flask 路径。"""
from concurrent.futures import ThreadPoolExecutor
import datetime
import json
import os
import shutil
import sys
import threading

import pytest

pytest.importorskip("flask")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "web"))

import io_utils  # noqa: E402
import llm_client  # noqa: E402
import records_store  # noqa: E402
import wizard_store  # noqa: E402
from app import create_app  # noqa: E402

FIXTURE = os.path.join(_ROOT, "tests", "fixtures", "2026-06-25_analysis.json")


@pytest.fixture
def data_root(tmp_path):
    daily = tmp_path / "records" / "daily"
    daily.mkdir(parents=True)
    shutil.copyfile(FIXTURE, daily / "2026-06-25_analysis.json")
    return tmp_path


@pytest.fixture
def client(tmp_path, data_root, monkeypatch):
    for key in ("VISION_API_KEY", "VISION_DISABLED", "LLM_API_KEY", "LLM_MODEL",
                "LLM_BASE_URL", "LLM_DISABLED", "WEB_ADMIN_TOKEN", "WEB_HOST"):
        monkeypatch.delenv(key, raising=False)
    app = create_app(env_file=str(tmp_path / ".env"), data_root=str(data_root))
    app.config["TESTING"] = True
    client = app.test_client()
    client.post("/welcome", headers={"Origin": "http://localhost"})
    return client


def _daily(data_root):
    return data_root / "records" / "daily"


def _record_path(data_root, date="2026-06-25"):
    return _daily(data_root) / f"{date}_analysis.json"


def _raw(data_root, date="2026-06-25"):
    return io_utils.read_versioned_json(_record_path(data_root, date))[0]


def _external_change(path, marker):
    raw, _ = io_utils.read_versioned_json(path)
    raw["external_marker"] = marker
    io_utils.atomic_write_json(path, raw)


def _assert_conflict(resp):
    assert resp.status_code == 409, resp.get_data(as_text=True)
    payload = resp.get_json()
    assert payload["ok"] is False and payload["conflict"] is True
    assert "刷新" in payload["error"]


def test_record_updates_conflict_then_retry_merges(data_root, monkeypatch):
    original_backup = records_store.backup_file
    barrier = threading.Barrier(2)

    def synchronized_backup(filepath, backup_dir):
        barrier.wait(timeout=10)
        return original_backup(filepath, backup_dir)

    monkeypatch.setattr(records_store, "backup_file", synchronized_backup)
    updates = [("body_color", "淡白"), ("tooth_marks", "重度")]

    def update(item):
        indicator, value = item
        try:
            result = records_store.update_observation(
                str(_daily(data_root)), str(data_root / "records" / "_backup"),
                "2026-06-25", "tongue", indicator, value)
            return "written" if result["ok"] else "error"
        except io_utils.WriteConflictError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(update, updates))
    assert sorted(outcomes) == ["conflict", "written"]

    monkeypatch.setattr(records_store, "backup_file", original_backup)
    indicator, value = updates[outcomes.index("conflict")]
    retry = records_store.update_observation(
        str(_daily(data_root)), str(data_root / "records" / "_backup"),
        "2026-06-25", "tongue", indicator, value)
    assert retry["ok"] is True
    body = _raw(data_root)["observations"]["tongue"]["body"]
    assert body["color"] == "淡白"
    assert body["tooth_marks"] == "重度"


def test_record_field_conflict_returns_409_and_keeps_current(client, data_root, monkeypatch):
    original_backup = records_store.backup_file

    def competing_backup(filepath, backup_dir):
        _external_change(filepath, "other-window")
        return original_backup(filepath, backup_dir)

    monkeypatch.setattr(records_store, "backup_file", competing_backup)
    resp = client.post("/record/2026-06-25/field", json={
        "dim": "tongue", "indicator": "tooth_marks", "value": "重度"})

    _assert_conflict(resp)
    raw = _raw(data_root)
    assert raw["external_marker"] == "other-window"
    assert raw["observations"]["tongue"]["body"]["tooth_marks"] == "轻度"


def test_restore_conflict_does_not_overwrite_newer_current(client, data_root, monkeypatch):
    target = _record_path(data_root)
    backup_dir = data_root / "records" / "_backup"
    records_store.backup_file(str(target), str(backup_dir))
    original_backup = records_store.backup_file

    def competing_backup(filepath, backup_dir, **kwargs):
        _external_change(filepath, "newer-current")
        return original_backup(filepath, backup_dir, **kwargs)

    monkeypatch.setattr(records_store, "backup_file", competing_backup)
    resp = client.post("/record/2026-06-25/restore")

    _assert_conflict(resp)
    assert _raw(data_root)["external_marker"] == "newer-current"


def test_report_conflict_preserves_edit_made_during_model_call(client, data_root, monkeypatch):
    target = _record_path(data_root)

    def fake_chat(*args, **kwargs):
        _external_change(target, "during-report")
        return json.dumps({"structured": {}, "markdown": "# 不应写入的旧报告"},
                          ensure_ascii=False)

    monkeypatch.setattr(llm_client, "chat", fake_chat)
    resp = client.post("/record/2026-06-25/report")

    _assert_conflict(resp)
    raw = _raw(data_root)
    assert raw["external_marker"] == "during-report"
    report = raw.get("diagnosis", {}).get("report", {})
    assert "不应写入的旧报告" not in report.get("markdown", "")


def test_draft_conflict_then_retry_merges_other_answer(client, data_root, monkeypatch):
    today = datetime.date.today().isoformat()
    daily = _daily(data_root)
    wizard_store.save_draft(str(daily), {"date": today, "parts": {}, "inquiry": {}})
    draft_file = wizard_store.draft_path(str(daily), today)
    original_write = io_utils.atomic_write_json
    fired = []

    def competing_write(path, raw, expected=io_utils.VERSION_NOT_PROVIDED):
        if not fired and os.path.abspath(path) == os.path.abspath(draft_file):
            fired.append(True)
            external = io_utils.read_versioned_json(draft_file)[0]
            external.setdefault("inquiry", {})["恶寒or恶热？"] = "恶寒"
            original_write(path, external)
        return original_write(path, raw, expected)

    monkeypatch.setattr(io_utils, "atomic_write_json", competing_write)
    resp = client.post("/wizard/inquiry", json={"question": "手足温凉", "answer": "凉"})

    _assert_conflict(resp)
    saved, _ = io_utils.read_versioned_json(draft_file)
    assert saved["inquiry"] == {"恶寒or恶热？": "恶寒"}

    monkeypatch.setattr(io_utils, "atomic_write_json", original_write)
    retry = client.post("/wizard/inquiry", json={"question": "手足温凉", "answer": "凉"})
    assert retry.status_code == 200
    saved, _ = io_utils.read_versioned_json(draft_file)
    assert saved["inquiry"] == {"恶寒or恶热？": "恶寒", "手足温凉": "凉"}


@pytest.mark.parametrize("stale", ["draft", "record"])
def test_submit_conflict_preserves_record_and_draft(client, data_root, monkeypatch, stale):
    today = datetime.date.today().isoformat()
    daily = _daily(data_root)
    target = daily / f"{today}_analysis.json"
    existing = io_utils.read_versioned_json(FIXTURE)[0]
    existing["date"] = today
    existing["external_marker"] = "original-record"
    io_utils.atomic_write_json(target, existing, None)
    draft = {"date": today, "inquiry": {}, "parts": {
        part["part"]: {"status": "skip_uncovered"} for part in wizard_store.PARTS}}
    wizard_store.save_draft(str(daily), draft)
    draft_file = wizard_store.draft_path(str(daily), today)
    original_validate = records_store.validate_candidate

    def competing_validate(raw, workdir, **kwargs):
        if stale == "draft":
            latest = wizard_store.load_draft(str(daily), today)
            latest["inquiry"] = {"手足温凉": "温"}
            wizard_store.save_draft(str(daily), latest)
        else:
            _external_change(target, "other-record")
        return original_validate(raw, workdir, **kwargs)

    monkeypatch.setattr(records_store, "validate_candidate", competing_validate)
    resp = client.post("/wizard/submit", json={"mode": "new"})

    _assert_conflict(resp)
    assert os.path.exists(draft_file)
    current_record = io_utils.read_versioned_json(target)[0]
    current_draft = io_utils.read_versioned_json(draft_file)[0]
    if stale == "draft":
        assert current_record["external_marker"] == "original-record"
        assert current_draft["inquiry"] == {"手足温凉": "温"}
    else:
        assert current_record["external_marker"] == "other-record"

    monkeypatch.setattr(records_store, "validate_candidate", original_validate)
    retry = client.post("/wizard/submit", json={"mode": "new"})
    assert retry.status_code == 200, retry.get_json()
    assert not os.path.exists(draft_file)


def test_wizard_conflict_responses_have_visible_error_handlers():
    with open(os.path.join(_ROOT, "web", "templates", "wizard.html"), encoding="utf-8") as handle:
        template = handle.read()
    skip = template[template.index("function skip(m)"):
                    template.index('document.getElementById("file-input").addEventListener("change"')]
    inquiry = template[template.index('postJSON("/wizard/inquiry", {question:'):
                       template.index("chips.appendChild(b)", template.index(
                           'postJSON("/wizard/inquiry", {question:'))]
    clear = template[template.index('document.getElementById("inquiry-clear-all")'):
                     template.index("function updateNav")]
    for block in (skip, inquiry, clear):
        assert 'showError(d.error || "保存失败")' in block
        assert ".catch(showError)" in block
