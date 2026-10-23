"""手动录入模式测试：VISION_DISABLED 开关 + /wizard/manual 通道 + 组装审计。

对应 app.py 的 vision_disabled 分支、/wizard/manual 端点与
wizard_store.assemble_record 的 manual 处理。
"""
import datetime
import io
import os
import sys

import pytest

pytest.importorskip("flask")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "web"))

import envfile  # noqa: E402
import wizard_store  # noqa: E402
from app import create_app  # noqa: E402

PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d494844520000000100000001080600000"
    "01f15c4890000000d4944415478da63fc3f40401f0005fb018a845d3d")


@pytest.fixture
def data_root(tmp_path):
    d = tmp_path / "data"
    (d / "records" / "daily").mkdir(parents=True)
    (d / "records" / "photos").mkdir(parents=True)
    return str(d)


@pytest.fixture
def client(tmp_path, data_root, monkeypatch):
    monkeypatch.setenv("VISION_API_KEY", "sk-test")
    monkeypatch.delenv("VISION_DISABLED", raising=False)
    app = create_app(env_file=str(tmp_path / ".env"), data_root=data_root)
    app.config["TESTING"] = True
    c = app.test_client()
    c.post("/welcome")
    return c


def _draft(data_root):
    today = datetime.date.today().isoformat()
    return wizard_store.load_draft(
        os.path.join(data_root, "records", "daily"), today)


def test_settings_toggle_vision_persists(client, tmp_path):
    env_path = str(tmp_path / ".env")
    client.post("/settings", data={"VISION_BASE_URL": "https://x.com/v1/chat/completions",
                                   "VISION_MODEL": "m"})
    assert envfile.read_env(env_path).get("VISION_DISABLED") == "1"
    client.post("/settings", data={"VISION_BASE_URL": "https://x.com/v1/chat/completions",
                                   "VISION_MODEL": "m", "VISION_ENABLED": "1"})
    assert envfile.read_env(env_path).get("VISION_DISABLED") == ""


def test_manual_field_writes_draft(client, data_root):
    resp = client.post("/wizard/manual", json={
        "part": "舌面", "indicator": "body_color", "value": "淡红"})
    assert resp.status_code == 200, resp.get_json()
    assert "danger_names" in resp.get_json()
    st = _draft(data_root)["parts"]["舌面"]
    assert st["status"] == "manual"
    assert st["observation"]["body"]["color"] == "淡红"


def test_manual_field_closed_vocab_rejected(client):
    resp = client.post("/wizard/manual", json={
        "part": "舌面", "indicator": "body_color", "value": "不存在词"})
    assert resp.status_code == 400
    assert "封闭词表" in resp.get_json()["error"]


def test_manual_field_part_prefix_guard(client):
    """舌底不可写舌面字段（部位级白名单防跨部位静默顶值）。"""
    resp = client.post("/wizard/manual", json={
        "part": "舌底", "indicator": "body_color", "value": "淡红"})
    assert resp.status_code == 400
    assert "不可写" in resp.get_json()["error"]


def test_wizard_field_accepts_manual_status(client):
    """第 8 步复核修正（/wizard/field）对手动录入部位同样可用。"""
    client.post("/wizard/manual", json={
        "part": "舌面", "indicator": "body_color", "value": "淡红"})
    resp = client.post("/wizard/field", json={
        "part": "舌面", "indicator": "body_color", "value": "红"})
    assert resp.status_code == 200, resp.get_json()


def test_assemble_record_includes_manual_with_audit(data_root):
    draft = {"date": "2026-10-23",
             "parts": {"舌面": {"status": "manual",
                                "observation": {"body": {"color": "淡红"}}}},
             "inquiry": {}}
    raw = wizard_store.assemble_record(draft, "1.8.30")
    assert raw["observations"]["tongue"]["body"]["color"] == "淡红"
    assert raw["manual_entry"] == ["tongue"]            # 手动录入审计标记
    assert "tongue" not in raw.get("photo_coverage", [])  # 不计入识图覆盖


def test_wizard_manual_mode_banner(client, tmp_path):
    with open(str(tmp_path / ".env"), "a", encoding="utf-8") as f:
        f.write("\nVISION_DISABLED=1\n")
    html = client.get("/wizard").get_data(as_text=True)
    assert "手动录入模式" in html and "视觉模型未启用" in html
    assert "用肉眼逐项观察" in html


def test_wizard_normal_mode_no_banner(client):
    html = client.get("/wizard").get_data(as_text=True)
    assert "手动录入模式" not in html and "用肉眼逐项观察" not in html


def test_photo_refused_when_vision_disabled(client, tmp_path):
    with open(str(tmp_path / ".env"), "a", encoding="utf-8") as f:
        f.write("\nVISION_DISABLED=1\n")
    resp = client.post("/wizard/photo", data={
        "part": "舌面", "file": (io.BytesIO(PNG), "photo.jpg")},
        content_type="multipart/form-data")
    assert resp.status_code == 400
    assert "未启用" in resp.get_json()["error"]
