"""B13：医学执行闸门的核心与真实写入路径；全部使用合成数据。"""
import json

import pytest

import input_validator
import llm_client
import records_store
import wizard_store
from src.record import DailyRecord, has_formula_content
from test_record_integrity import client, data_root, _write


FORMULA_MD = "## 方剂建议\n- 桂枝汤：桂枝９ｇ，茯苓三钱。"
DIRECTION_MD = "## 方剂类别方向\n- 解表剂、和解剂方向，供鉴别。"
DOSE_MD = "## 剂量建议\n- 桂枝９ｇ。"


def _raw(confidence="LOW", markdown=None):
    raw = {
        "date": "2026-06-25",
        "confidence": confidence,
        "observations": {"tongue": {"body": {"color": "红"}}},
        "danger_flags": {"triggered": [], "not_triggered": [], "unknown": []},
    }
    if confidence == "MEDIUM":
        raw["observations"]["eye"] = {"redness": "红血丝"}
    if markdown is not None:
        raw["diagnosis"] = {"report": {"markdown": markdown}}
    return raw


def _validate(tmp_path, raw):
    path = tmp_path / "2026-06-25_analysis.json"
    _write(path, raw)
    return input_validator.validate_record(str(path))


def test_low_formula_in_report_is_validator_error(tmp_path):
    _, errors, _ = _validate(tmp_path, _raw(markdown=FORMULA_MD))
    assert any("LOW" in error and "方剂" in error for error in errors)


@pytest.mark.parametrize("markdown,blocked", [
    (DIRECTION_MD, False),
    (DOSE_MD, True),
])
def test_medium_direction_allowed_but_dosage_blocked(tmp_path, markdown, blocked):
    _, errors, _ = _validate(tmp_path, _raw("MEDIUM", markdown))
    assert any("剂量" in error for error in errors) is blocked


def test_low_direction_is_not_specific_prescription(tmp_path):
    _, errors, _ = _validate(tmp_path, _raw(markdown=DIRECTION_MD))
    assert not any("方剂" in error for error in errors)


@pytest.mark.parametrize("text", ["桂枝９ｇ", "桂枝三克", "桂枝三钱", "茯苓二两", "生姜三枚"])
def test_formula_content_recognizes_units_and_unicode(text):
    assert has_formula_content({"note": text}) is True


def test_formula_material_aggregates_locations_and_skips_empty_containers():
    rec = DailyRecord(_raw(markdown=FORMULA_MD) | {
        "formula": None, "formula_adjust": {},
        "formula_with_dosage": {"方名": "合成汤", "组成": [{"药": "茯苓", "剂量": "三钱"}]},
    })
    material = rec.get_formula_material()
    assert any(has_formula_content(item) for item in material)


def test_mixed_danger_flags_are_united_and_rejected(tmp_path):
    raw = _raw() | {"danger_flags": {
        "triggered": [], "daiyang": {"triggered": True, "finding": "合成红旗"}}}
    assert DailyRecord(raw).get_triggered_danger_flags() == ["daiyang"]
    _, errors, _ = _validate(tmp_path, raw)
    assert any("混合" in error and "danger_flags" in error for error in errors)


def test_correction_blocks_new_safety_error(client, data_root):
    path = data_root / "records" / "daily" / "2026-06-25_analysis.json"
    _write(path, _raw("MEDIUM", "## 方剂建议\n- 桂枝汤。"))
    before = path.read_bytes()
    resp = client.post("/record/2026-06-25/field", json={
        "dim": "eye", "indicator": "redness", "action": "clear"})
    assert resp.status_code == 400
    assert "安全边界" in resp.get_json()["errors"][0]
    assert path.read_bytes() == before


def test_correction_allows_preexisting_safety_error_with_warning(client, data_root):
    path = data_root / "records" / "daily" / "2026-06-25_analysis.json"
    _write(path, _raw(markdown=FORMULA_MD))
    resp = client.post("/record/2026-06-25/field", json={
        "dim": "tongue", "indicator": "body_color", "value": "淡红"})
    assert resp.status_code == 200, resp.get_json()
    assert any("安全边界" in warning for warning in resp.get_json()["warnings"])


@pytest.mark.parametrize("confidence,markdown,expected", [
    ("LOW", FORMULA_MD, 400),
    ("MEDIUM", DOSE_MD, 400),
    ("MEDIUM", DIRECTION_MD, 200),
])
def test_report_gate_preserves_file_on_violation(client, data_root, monkeypatch,
                                                 confidence, markdown, expected):
    path = data_root / "records" / "daily" / "2026-06-25_analysis.json"
    _write(path, _raw(confidence))
    monkeypatch.setattr(llm_client, "chat", lambda *args, **kwargs: json.dumps(
        {"structured": {}, "markdown": markdown}, ensure_ascii=False))
    before = path.read_bytes()
    resp = client.post("/record/2026-06-25/report")
    assert resp.status_code == expected, resp.get_json()
    if expected == 400:
        assert path.read_bytes() == before


def test_wizard_rejects_new_mixed_danger_structure(client, data_root):
    today = wizard_store.datetime.date.today().isoformat()
    daily = data_root / "records" / "daily"
    for part in wizard_store.PARTS:
        client.post("/wizard/skip", json={"part": part["part"], "mode": "normal"})
    draft = wizard_store.load_draft(str(daily), today)
    draft["danger_flags"] = {
        "triggered": [], "daiyang": {"triggered": True, "finding": "合成红旗"}}
    wizard_store.save_draft(str(daily), draft)
    resp = client.post("/wizard/submit", json={"mode": "new", "acknowledge": "keep"})
    assert resp.status_code == 400
    assert not (daily / f"{today}_analysis.json").exists()


def test_wizard_merge_preserves_old_violation_as_warning(client, data_root):
    today = wizard_store.datetime.date.today().isoformat()
    daily = data_root / "records" / "daily"
    _write(daily / f"{today}_analysis.json", _raw(markdown=FORMULA_MD))
    for part in wizard_store.PARTS:
        client.post("/wizard/skip", json={"part": part["part"], "mode": "normal"})
    resp = client.post("/wizard/submit", json={"mode": "merge"})
    assert resp.status_code == 200, resp.get_json()
    assert any("安全边界" in warning for warning in resp.get_json()["warnings"])


def test_danger_probe_failure_is_diagnosed(tmp_path, monkeypatch):
    import src.danger
    monkeypatch.setattr(src.danger, "detect_danger",
                        lambda *args: (_ for _ in ()).throw(ValueError("合成探测异常")))
    _, _, warnings = _validate(tmp_path, _raw())
    assert any("红线探测失败" in warning for warning in warnings)


def test_report_allows_direction_with_preexisting_violation(client, data_root, monkeypatch):
    path = data_root / "records" / "daily" / "2026-06-25_analysis.json"
    _write(path, _raw(markdown=FORMULA_MD))
    monkeypatch.setattr(llm_client, "chat", lambda *args, **kwargs: json.dumps(
        {"structured": {}, "markdown": DIRECTION_MD}, ensure_ascii=False))
    resp = client.post("/record/2026-06-25/report")
    assert resp.status_code == 200, resp.get_json()
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["diagnosis"]["report"]["markdown"] == DIRECTION_MD


def test_formula_material_checks_legacy_diagnosis_despite_empty_new_container():
    rec = DailyRecord(_raw() | {
        "diagnosis": {},
        "deepseek_diagnosis": {"方剂建议": {"方名": "麻黄细辛附子汤"}},
    })
    assert any(has_formula_content(item) for item in rec.get_formula_material())


@pytest.mark.parametrize("formula", [
    {"note": "桂枝加附子汤"},
    {"方名": "麻黄细辛附子汤"},
    {"prescription": "当归芍药散 当归三两"},
])
def test_formula_content_recognizes_general_formula_names(formula):
    assert has_formula_content(formula) is True


def test_empty_danger_flag_name_is_rejected(tmp_path):
    raw = _raw() | {"danger_flags": {"triggered": [""]}}
    _, errors, _ = _validate(tmp_path, raw)
    assert any("非空红线键名" in error for error in errors)
