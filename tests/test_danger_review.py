"""B15：红线裁决生命周期；所有观察和问诊均为合成输入。"""
import json

import pytest

import trends_store
import wizard_store
from src.alerts import danger_flags_for
from src.danger import detect_danger
from src.record import DailyRecord
from test_record_integrity import client, data_root, _write


def _draft(data_root, observation=None):
    today = wizard_store.datetime.date.today().isoformat()
    daily = data_root / "records" / "daily"
    draft = {"date": today, "inquiry": {}, "parts": {
        part["part"]: {"status": "skip_normal"} for part in wizard_store.PARTS}}
    draft["parts"]["舌面"] = {
        "status": "manual", "source": "manual", "method": "manual",
        "observation": observation or {"coating": {"peeling": "镜面"}},
    }
    wizard_store.save_draft(str(daily), draft)
    return today, daily


def _submit(client, **payload):
    return client.post("/wizard/submit", json={"mode": "new", **payload})


def _review(client):
    resp = _submit(client)
    data = resp.get_json()
    assert data["need_danger_ack"] is True, data
    assert data["danger_token"]
    return data


def _read(daily, today):
    return json.loads((daily / f"{today}_analysis.json").read_text(encoding="utf-8"))


def test_dismiss_preserves_evidence_audit_and_does_not_revive(client, data_root):
    today, daily = _draft(data_root)
    review = _review(client)
    resp = _submit(client, acknowledge={"mirror_tongue": "dismiss"},
                   danger_token=review["danger_token"])
    assert resp.status_code == 200, resp.get_json()
    raw = _read(daily, today)
    assert raw["observations"]["tongue"]["coating"]["peeling"] == "镜面"
    assert raw["danger_review"][-1]["decision"] == "dismiss"
    assert raw["danger_review"][-1]["key"] == "mirror_tongue"
    assert raw["danger_review"][-1]["original_triggered"] == ["mirror_tongue"]
    assert raw["danger_review"][-1]["evidence"]
    assert "mirror_tongue" not in raw["danger_flags"]["not_triggered"]
    assert "mirror_tongue" in raw["danger_flags"]["dismissed"]
    report = trends_store.build_report_input(DailyRecord(raw))
    assert "误报" in report and "均未触发" not in report

    resp = client.post(f"/record/{today}/field", json={
        "dim": "tongue", "indicator": "body_color", "value": "红"})
    assert resp.status_code == 200, resp.get_json()
    raw = _read(daily, today)
    assert "mirror_tongue" in raw["danger_flags"]["dismissed"]
    assert "mirror_tongue" not in raw["danger_flags"]["triggered"]


def test_first_or_stale_confirmation_cannot_clear_flags(client, data_root):
    today, daily = _draft(data_root)
    resp = _submit(client, acknowledge={"mirror_tongue": "dismiss"})
    assert resp.status_code == 409
    assert not (daily / f"{today}_analysis.json").exists()
    resp = _submit(client, acknowledge="fix")
    assert resp.status_code == 409
    assert not (daily / f"{today}_analysis.json").exists()

    review = _review(client)
    draft = wizard_store.load_draft(str(daily), today)
    draft["parts"]["舌面"]["observation"]["coating"]["thickness"] = "焦黑"
    wizard_store.save_draft(str(daily), draft)
    changed = _review(client)
    assert changed["danger_token"] != review["danger_token"]
    resp = _submit(client, acknowledge={"mirror_tongue": "keep"},
                   danger_token=review["danger_token"])
    assert resp.status_code == 409
    assert resp.get_json()["need_danger_ack"] is True
    assert not (daily / f"{today}_analysis.json").exists()


def test_keep_merge_does_not_reprompt_or_dismiss_untouched_old(client, data_root):
    today, daily = _draft(data_root)
    review = _review(client)
    assert _submit(client, acknowledge={"mirror_tongue": "keep"},
                   danger_token=review["danger_token"]).status_code == 200
    _draft(data_root)
    draft = wizard_store.load_draft(str(daily), today)
    draft["parts"]["皮肤"] = {
        "status": "manual", "source": "manual", "method": "manual",
        "observation": {"color": "正常"},
    }
    wizard_store.save_draft(str(daily), draft)
    resp = client.post("/wizard/submit", json={"mode": "merge"})
    assert resp.status_code == 200, resp.get_json()

    draft["parts"]["皮肤"]["observation"]["color"] = "黄如橘皮"
    draft["parts"]["目"] = {
        "status": "manual", "source": "manual", "method": "manual",
        "observation": {"scleral_jaundice": "黄染明显"},
    }
    wizard_store.save_draft(str(daily), draft)
    resp = client.post("/wizard/submit", json={"mode": "merge"})
    data = resp.get_json()
    assert data["need_danger_ack"] is True, data
    assert [item["key"] for item in data["danger"]] == ["acute_jaundice"]
    resp = client.post("/wizard/submit", json={
        "mode": "merge", "acknowledge": {"mirror_tongue": "dismiss"},
        "danger_token": data["danger_token"]})
    assert resp.status_code == 400
    assert _read(daily, today)["danger_review"][0]["decision"] == "keep"


def test_correction_clears_automatic_flag_with_audit(client, data_root):
    today = wizard_store.datetime.date.today().isoformat()
    daily = data_root / "records" / "daily"
    raw = {"date": today, "observations": {"tongue": {"coating": {"peeling": "镜面"}}}}
    raw["danger_flags"] = danger_flags_for(raw)
    _write(daily / f"{today}_analysis.json", raw)
    resp = client.post(f"/record/{today}/field", json={
        "dim": "tongue", "indicator": "coating_peeling", "value": "无"})
    assert resp.status_code == 200, resp.get_json()
    raw = _read(daily, today)
    assert "mirror_tongue" not in raw["danger_flags"]["triggered"]
    assert raw["danger_review"][-1]["decision"] == "clear"
    assert raw["danger_review"][-1]["key"] == "mirror_tongue"
    assert raw["danger_review"][-1]["source"] == "correction"


def test_inquiry_change_clears_flag_with_audit(client, data_root):
    today, daily = _draft(data_root)
    assert client.post("/wizard/context", data={
        "chief_complaint": "神昏"}).status_code == 302
    assert client.post("/wizard/inquiry", json={
        "question": "汗出时间特征？", "answer": "绝汗(大汗淋漓如油)"}
    ).status_code == 200
    draft = wizard_store.load_draft(str(daily), today)
    assert "collapse_yang" in detect_danger(draft)
    assert client.post("/wizard/inquiry", json={
        "question": "汗出时间特征？", "answer": "无异常"}).status_code == 200
    draft = wizard_store.load_draft(str(daily), today)
    assert "collapse_yang" not in draft["danger_flags"]["triggered"]
    assert draft["danger_review"][-1]["decision"] == "clear"
    assert draft["danger_review"][-1]["source"] == "inquiry"


def test_detail_marks_dismissed_separately(client, data_root):
    today, daily = _draft(data_root)
    review = _review(client)
    _submit(client, acknowledge={"mirror_tongue": "dismiss"},
            danger_token=review["danger_token"])
    html = client.get(f"/record/{today}").get_data(as_text=True)
    assert "误报" in html
    assert "均未触发" not in html
    import records_store
    detail = records_store.record_detail(DailyRecord(_read(daily, today)))
    assert detail["dims"][0]["covered"] is True
    assert detail["dims"][0]["declared_normal"] is False


def test_external_flag_without_automatic_evidence_is_preserved():
    from src.danger_review import refresh_danger
    raw = {"observations": {}, "danger_flags": {
        "triggered": ["external_review"], "not_triggered": []}}
    refresh_danger(raw)
    assert "external_review" in raw["danger_flags"]["triggered"]
    assert raw["danger_review"] == []


def test_clear_is_not_duplicated_on_next_refresh():
    from src.danger_review import refresh_danger
    raw = {"observations": {"tongue": {"coating": {"peeling": "镜面"}}}}
    refresh_danger(raw)
    raw["observations"]["tongue"]["coating"]["peeling"] = "无"
    refresh_danger(raw)
    assert len(raw["danger_review"]) == 1
    refresh_danger(raw)
    assert len(raw["danger_review"]) == 1


def test_evidence_change_requires_new_confirmation():
    from src.danger_review import (
        DangerReviewConflict, apply_decision, refresh_danger, review_snapshot,
    )
    raw = {"observations": {"tongue": {"coating": {"peeling": "镜面"}}}}
    refresh_danger(raw)
    first = review_snapshot(raw)
    apply_decision(raw, first["token"], {"mirror_tongue": "keep"})
    assert review_snapshot(raw)["pending"] == []
    raw["observations"]["tongue"]["coating"].update({
        "peeling": "无", "thickness": "焦黑"})
    raw["observations"]["tongue"]["body"] = {"luster": "干裂"}
    refresh_danger(raw)
    changed = review_snapshot(raw)
    assert changed["token"] != first["token"]
    assert changed["pending"] == ["tongue_critical"]
    try:
        apply_decision(raw, first["token"], {"tongue_critical": "keep"})
    except DangerReviewConflict:
        pass
    else:
        raise AssertionError("旧令牌不应确认新证据")
    assert any(item["decision"] == "clear" for item in raw["danger_review"])


def test_invalid_review_history_is_rejected():
    from src.danger_review import validate_history
    assert validate_history([{"decision": "dismiss"}])


def test_native_dialog_binds_token_and_safe_default(client):
    html = client.get("/wizard").get_data(as_text=True)
    assert '<dialog id="danger-modal"' in html
    assert "dialog.showModal()" in html
    assert "body.danger_token = pendingSubmit ? pendingSubmit.danger_token : \"\";" in html
    assert 'pendingSubmit.decisions[f.key] = "keep"' in html
    assert 'button.setAttribute("aria-pressed"' in html


def test_decision_changes_report_input_hash():
    from src.derived import observation_input_hash
    from src.danger_review import apply_decision, refresh_danger, review_snapshot
    raw = {"observations": {"tongue": {"coating": {"peeling": "镜面"}}}}
    refresh_danger(raw)
    before = observation_input_hash(DailyRecord(raw))
    snapshot = review_snapshot(raw)
    apply_decision(raw, snapshot["token"], {"mirror_tongue": "keep"})
    assert observation_input_hash(DailyRecord(raw)) != before
