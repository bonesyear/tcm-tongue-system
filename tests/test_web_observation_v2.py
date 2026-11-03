"""形状 B v2：舌面/皮肤采集与真实 Flask 工作流。"""
import io
import json
import os
import sys

import pytest

pytest.importorskip("flask")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "web"))
sys.path.insert(0, os.path.join(_ROOT, "scripts"))

import wizard_store
from app import create_app

from test_web_wizard import PNG


@pytest.fixture
def data_root(tmp_path):
    root = tmp_path / "data"
    (root / "records" / "daily").mkdir(parents=True)
    (root / "records" / "photos").mkdir(parents=True)
    return str(root)


@pytest.fixture
def client(tmp_path, data_root, monkeypatch):
    monkeypatch.setenv("VISION_API_KEY", "sk-test")
    monkeypatch.setenv("VISION_DISABLED", "0")
    monkeypatch.setenv("LLM_DISABLED", "1")
    monkeypatch.delenv("WEB_ADMIN_TOKEN", raising=False)
    monkeypatch.delenv("WEB_HOST", raising=False)
    app = create_app(env_file=str(tmp_path / "missing.env"), data_root=data_root)
    app.config["TESTING"] = True
    client = app.test_client()
    client.post("/welcome", headers={"Origin": "http://localhost"})
    return client


def _upload(client, part, extra=None):
    data = {"part": part, "file": (io.BytesIO(PNG), "photo.jpg")}
    data.update(extra or {})
    return client.post("/wizard/photo", data=data, content_type="multipart/form-data")


def _finish_remaining(client, completed):
    for part in wizard_store.PART_BY_NAME:
        if part not in completed:
            response = client.post("/wizard/skip", json={"part": part, "mode": "normal"})
            assert response.status_code == 200


def _submit(client, data_root):
    response = client.post("/wizard/submit", json={"mode": "new"})
    data = response.get_json()
    assert data["ok"] is True, data
    path = os.path.join(data_root, "records", "daily", f"{data['date']}_analysis.json")
    with open(path, encoding="utf-8") as f:
        return path, json.load(f)


def test_tongue_mock_photo_writes_v2_metadata_and_declarations(client, data_root, monkeypatch):
    monkeypatch.setattr(wizard_store, "observe_photo", lambda part, path, **options: ({
        "复合舌苔": "白厚腻苔，偏干", "舌质颜色": "淡红",
    }, []))
    response = _upload(client, "舌面")
    assert response.status_code == 200, response.get_json()
    observation = response.get_json()["observation"]
    assert observation["coating"]["color"] == "白"
    assert observation["coating"]["thickness"] == "厚腻"
    assert observation["coating"]["moisture"] == "偏干"
    assert response.get_json()["observation_meta"]["tongue.coating.thickness"]["raw"] == "白厚腻苔，偏干"
    _finish_remaining(client, {"舌面"})
    path, raw = _submit(client, data_root)
    assert raw["schema_version"] == 2
    meta = raw["observation_meta"]["tongue.coating.thickness"]
    assert meta["raw"] == "白厚腻苔，偏干"
    assert meta["value"] == "厚腻"
    assert meta["source"] == "vision" and meta["method"] == "photo"
    assert raw["observations"]["tongue"]["coating"]["thickness"] == "厚腻"
    assert raw["declarations"]
    assert all(item["kind"] == "declared_normal" for item in raw["declarations"])
    assert "未拍摄（用户声明正常）" not in json.dumps(raw["observations"], ensure_ascii=False)
    assert raw["derived_meta"]["input_hash"]
    import input_validator
    _, errors, _ = input_validator.validate_record(path)
    assert errors == []


def test_skin_manual_sources_are_enforced_and_saved(client, data_root):
    accepted = client.post("/wizard/manual", json={
        "part": "皮肤", "indicator": "edema", "value": "凹陷", "method": "palpation"})
    assert accepted.status_code == 200
    rejected = client.post("/wizard/manual", json={
        "part": "皮肤", "indicator": "edema", "value": "凹陷"})
    assert rejected.status_code == 400
    assert client.post("/wizard/manual", json={
        "part": "皮肤", "indicator": "yellow_sweat", "value": "色正黄",
        "method": "inquiry"}).status_code == 200
    assert client.post("/wizard/manual", json={
        "part": "皮肤", "indicator": "yellow_sweat", "value": "色正黄",
        "method": "photo"}).status_code == 400
    assert client.post("/wizard/manual", json={
        "part": "皮肤", "indicator": "yellow_sweat", "value": "色正黄",
        "method": "photo", "evidence": {"kind": "clothing"}}).status_code == 200
    assert client.post("/wizard/manual", json={
        "part": "舌面", "indicator": "body_color", "value": "淡红"}).status_code == 200
    _finish_remaining(client, {"舌面", "皮肤"})
    path, raw = _submit(client, data_root)
    assert raw["observations"]["skin"]["edema"] == "凹陷"
    assert raw["observations"]["skin"]["yellow_sweat"] == "色正黄"
    assert raw["observation_meta"]["skin.edema"]["method"] == "palpation"
    assert raw["observation_meta"]["skin.yellow_sweat"]["method"] == "photo"
    assert raw["observation_meta"]["skin.yellow_sweat"]["evidence"]["kind"] == "clothing"
    assert raw["schema_version"] == 2 and raw["declarations"]
    import input_validator
    _, errors, _ = input_validator.validate_record(path)
    assert errors == []


def test_dynamic_photo_rejected_and_lower_lid_unknown(client, data_root, monkeypatch):
    monkeypatch.setattr(wizard_store, "observe_photo", lambda part, path, **options: ({"舌体动态": "强硬"}, []))
    rejected = _upload(client, "舌面")
    assert rejected.status_code == 400
    assert rejected.get_json()["photo_saved"] is True
    monkeypatch.setattr(wizard_store, "observe_photo", lambda part, path, **options: ({"下睑结膜颜色": "淡白"}, []))
    accepted = _upload(client, "目")
    assert accepted.status_code == 200
    _finish_remaining(client, {"目"})
    _, raw = _submit(client, data_root)
    meta = raw["observation_meta"]["eye.lower_lid_color"]
    assert meta["certainty"] == "unknown" and meta["raw"] == "淡白"
    assert not raw["observations"].get("eye", {}).get("lower_lid_color")
    from src.record import DailyRecord
    from src.dimensions import VisionDimension as V
    assert DailyRecord(raw).get_dimension_coverage()[V.EYE] is False
    from src.observations import UNKNOWN_OBSERVATION_MARK
    assert DailyRecord(raw).get_observation(V.EYE)["lower_lid"] == UNKNOWN_OBSERVATION_MARK


def test_exposed_lower_lid_and_scaled_measurement_are_allowed(client, data_root, monkeypatch):
    monkeypatch.setattr(wizard_store, "observe_photo", lambda part, path, **options: ({"下睑结膜颜色": "淡白"}, []))
    response = _upload(client, "目", {"exposed": "1"})
    assert response.status_code == 200
    assert response.get_json()["observation"]["lower_lid_color"] == "淡白"
    assert client.post("/wizard/manual", json={
        "part": "舌底", "indicator": "sublingual_thickness", "value": "3mm",
        "method": "photo", "evidence": {"has_scale": False}}).status_code == 200
    assert client.post("/wizard/manual", json={
        "part": "舌底", "indicator": "sublingual_thickness", "value": "3mm",
        "method": "measurement", "evidence": {"has_scale": True}}).status_code == 200
    _finish_remaining(client, {"目", "舌底"})
    path, raw = _submit(client, data_root)
    assert raw["observations"]["eye"]["lower_lid_color"] == "淡白"
    assert raw["observations"]["tongue"]["sublingual"]["vein_thickness"] == "3mm"
    assert raw["observation_meta"]["tongue.sublingual.vein_thickness"]["method"] == "measurement"
    assert raw["observation_meta"]["tongue.sublingual.vein_thickness"]["evidence"]["has_scale"] is True
    import input_validator
    _, errors, _ = input_validator.validate_record(path)
    assert errors == []


def test_refused_and_unavailable_are_independent_declarations(client, data_root):
    assert client.post("/wizard/skip", json={
        "part": "皮肤", "mode": "refused", "reason": "不愿拍摄"}).status_code == 200
    assert client.post("/wizard/skip", json={
        "part": "目", "mode": "unavailable", "reason": "无法暴露"}).status_code == 200
    _finish_remaining(client, {"皮肤", "目"})
    _, raw = _submit(client, data_root)
    kinds = {item["kind"] for item in raw["declarations"]}
    assert kinds == {"declared_normal", "refused", "unavailable"}
    assert "未拍摄（用户声明正常）" not in json.dumps(raw["observations"], ensure_ascii=False)


def test_optional_minimal_context_is_saved_and_hashed(client, data_root):
    page = client.get("/wizard").get_data(as_text=True)
    assert "最小上下文" in page and "不收集姓名" in page
    response = client.post("/wizard/context", data={
        "age_band": "成年", "chief_complaint": "口干", "duration": "3天",
        "recent_dyes": "咖啡", "medications": "无", "sweating_medication": "未使用",
        "history_allergies": "无", "sleep": "睡眠不足", "congenital_signs": "无",
    })
    assert response.status_code in (301, 302)
    today = wizard_store.datetime.date.today().isoformat()
    draft = wizard_store.load_draft(
        os.path.join(data_root, "records", "daily"), today)
    assert draft["context"]["chief_complaint"] == "口干"
    assert draft["context"]["age_band"] == "成年"
    _finish_remaining(client, set())
    _, raw = _submit(client, data_root)
    assert raw["context"]["recent_dyes"] == "咖啡"
    assert raw["context"]["sleep"] == "睡眠不足"
    from src.derived import observation_input_hash
    from src.record import DailyRecord
    without_context = dict(raw)
    without_context["context"] = {}
    assert observation_input_hash(DailyRecord(raw)) != observation_input_hash(
        DailyRecord(without_context))
    rejected = client.post("/wizard/context", data={"age_band": "1970-01-01"})
    assert rejected.status_code == 400
