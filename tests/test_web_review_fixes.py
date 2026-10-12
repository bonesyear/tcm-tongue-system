"""web 层审查修复的回归测试（2026-10-12 双轴审查发现项）。"""
import io
import json
import os
import sys

import pytest

pytest.importorskip("flask")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "web"))

import records_store  # noqa: E402
import wizard_store  # noqa: E402
from app import create_app  # noqa: E402

PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d494844520000000100000001080600000"
    "01f15c4890000000d4944415478da63fc3f40401f0005fb018a845d3d")
ALL_PARTS = [p["part"] for p in wizard_store.PARTS]


@pytest.fixture
def data_root(tmp_path):
    d = tmp_path / "data"
    (d / "records" / "daily").mkdir(parents=True)
    (d / "records" / "photos").mkdir(parents=True)
    return str(d)


@pytest.fixture
def client(tmp_path, data_root, monkeypatch):
    monkeypatch.setenv("VISION_API_KEY", "sk-test")
    app = create_app(env_file=str(tmp_path / ".env"), data_root=data_root)
    app.config["TESTING"] = True
    c = app.test_client()
    c.post("/welcome")
    return c


def _upload(client, part):
    return client.post("/wizard/photo", data={
        "part": part, "file": (io.BytesIO(PNG), "p.jpg"),
    }, content_type="multipart/form-data")


def test_danger_detected_from_observation_text(client, monkeypatch):
    """真实路径可达：识图文本含「焦黑」→ 提交时弹拦截层（无需注入草稿）。"""
    monkeypatch.setattr(wizard_store, "observe_photo",
                        lambda part, p: ({"舌质颜色": "紫暗", "舌苔": {"颜色": "焦黑"}}, []))
    _upload(client, "舌面")
    for part in ALL_PARTS[1:]:
        client.post("/wizard/skip", json={"part": part, "mode": "normal"})
    resp = client.post("/wizard/submit", json={"mode": "new"})
    data = resp.get_json()
    assert data["ok"] is False and data["need_danger_ack"] is True
    assert data["danger"][0]["key"] == "tongue_critical"
    assert data["danger"][0]["sign"]      # 体征字段不为空


def test_danger_fix_exit_moves_flag_out_of_triggered(client, data_root, monkeypatch):
    """「误判，去修正」：落盘时红线移入 not_triggered（与「保留警示」分岔）。"""
    monkeypatch.setattr(wizard_store, "observe_photo",
                        lambda part, p: ({"舌质颜色": "紫暗", "舌苔": {"颜色": "焦黑"}}, []))
    _upload(client, "舌面")
    for part in ALL_PARTS[1:]:
        client.post("/wizard/skip", json={"part": part, "mode": "normal"})
    # 先触发拦截再选 fix
    resp = client.post("/wizard/submit", json={"mode": "new"})
    assert resp.get_json()["need_danger_ack"] is True
    resp = client.post("/wizard/submit", json={"mode": "new", "acknowledge": "fix"})
    assert resp.get_json()["ok"] is True
    raw = records_store.load_record(
        os.path.join(data_root, "records", "daily"),
        resp.get_json()["date"]).raw
    assert raw["danger_flags"]["triggered"] == []
    assert "tongue_critical" in raw["danger_flags"]["not_triggered"]


def test_merge_rejects_non_shape_b(client, data_root):
    """当日记录为形状 C（旧格式）时，「补充」明确报错而不是丢数据。"""
    today = wizard_store.datetime.date.today().isoformat()
    daily = os.path.join(data_root, "records", "daily")
    with open(os.path.join(daily, f"{today}_analysis.json"), "w",
              encoding="utf-8") as f:
        json.dump({"date": today, "tongue": {"body_color": "淡红"}}, f,
                  ensure_ascii=False)  # 形状 C（顶层维度键）
    for part in ALL_PARTS:
        client.post("/wizard/skip", json={"part": part, "mode": "normal"})
    resp = client.post("/wizard/submit", json={"mode": "merge"})
    assert resp.status_code == 400
    assert "重新分析" in resp.get_json()["error"]
    # 旧档未被破坏
    with open(os.path.join(daily, f"{today}_analysis.json"), encoding="utf-8") as f:
        assert json.load(f)["tongue"]["body_color"] == "淡红"


def test_merge_preserves_existing_extras(client, data_root, monkeypatch):
    """merge 形状 B：旧记录的 tags/辨证字段保留，只补未覆盖维度。"""
    today = wizard_store.datetime.date.today().isoformat()
    daily = os.path.join(data_root, "records", "daily")
    with open(os.path.join(daily, f"{today}_analysis.json"), "w",
              encoding="utf-8") as f:
        json.dump({"date": today, "tags": ["晨起"], "custom_note": "旧注记",
                   "observations": {"tongue": {"body": {"color": "红绛"}}}},
                  f, ensure_ascii=False)
    _mock = lambda part, p: ({"肤色": "偏淡"}, [])  # noqa: E731
    monkeypatch.setattr(wizard_store, "observe_photo", _mock)
    _upload(client, "皮肤")
    for part in ALL_PARTS[:-1]:
        client.post("/wizard/skip", json={"part": part, "mode": "normal"})
    resp = client.post("/wizard/submit", json={"mode": "merge"})
    assert resp.get_json()["ok"] is True
    raw = records_store.load_record(daily, today).raw
    assert raw["tags"] == ["晨起"] and raw["custom_note"] == "旧注记"
    assert raw["observations"]["tongue"]["body"]["color"] == "红绛"
    assert raw["observations"]["skin"]["color"] == "偏淡"


def test_skip_uncovered_is_marked(client, data_root, monkeypatch):
    """「跳过（未覆盖）」在记录中显式标注（双跳过都留痕）。"""
    monkeypatch.setattr(wizard_store, "observe_photo",
                        lambda part, p: ({"舌质颜色": "淡红"}, []))
    _upload(client, "舌面")
    client.post("/wizard/skip", json={"part": "舌底", "mode": "uncovered"})
    for part in ALL_PARTS[2:]:
        client.post("/wizard/skip", json={"part": part, "mode": "normal"})
    resp = client.post("/wizard/submit", json={"mode": "new"})
    raw = records_store.load_record(
        os.path.join(data_root, "records", "daily"),
        resp.get_json()["date"]).raw
    assert raw["skipped_dimensions"]["uncovered"] == ["tongue"] or \
        "tongue" in raw["skipped_dimensions"]["uncovered"]
    assert "head_face" in raw["skipped_dimensions"]["declared_normal"]


def test_corrupted_draft_warns_not_silent(tmp_path, capsys):
    daily = tmp_path / "daily"
    daily.mkdir()
    (daily / ".wizard-2026-10-12.json").write_text("{损坏", encoding="utf-8")
    draft = wizard_store.load_draft(str(daily), "2026-10-12")
    assert draft["parts"] == {}
    assert "草稿" in capsys.readouterr().err
    assert os.path.exists(str(daily / ".wizard-2026-10-12.json.corrupt"))
