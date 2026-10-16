"""web 层切片 3 测试：修正流（校验拦截 / 形状感知写回 / 备份 / 打标 / 重评分）。"""
import json
import os
import sys

import pytest

pytest.importorskip("flask")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "web"))

from app import create_app  # noqa: E402

FIXTURE = os.path.join(_ROOT, "tests", "fixtures", "2026-06-25_analysis.json")


@pytest.fixture
def data_root(tmp_path):
    d = tmp_path / "data"
    (d / "records" / "daily").mkdir(parents=True)
    return str(d)


@pytest.fixture
def client(tmp_path, data_root, monkeypatch):
    for k in ("VISION_API_KEY", "WEB_ADMIN_TOKEN", "WEB_HOST"):
        monkeypatch.delenv(k, raising=False)
    app = create_app(env_file=str(tmp_path / ".env"), data_root=data_root)
    app.config["TESTING"] = True
    c = app.test_client()
    c.post("/welcome")
    c.post("/demo")  # 载入合成示例记录 2026-06-25
    return c


def _read_raw(data_root, date="2026-06-25"):
    with open(os.path.join(data_root, "records", "daily",
                           f"{date}_analysis.json"), encoding="utf-8") as f:
        return json.load(f)


def test_correction_full_flow(client, data_root):
    """改齿痕 轻度→重度：写回形状 B 正确路径、备份落盘、打标、重评分。"""
    resp = client.post("/record/2026-06-25/field", json={
        "dim": "tongue", "indicator": "tooth_marks", "value": "重度"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert data["field_score"] == 10          # 重度=10（评分词表真实输出）
    # 总分 = 原总分 − 舌诊旧分 + 舌诊新分（sparse 均值口径，不手算硬编码）
    assert data["summary"]["total"] == pytest.approx(
        28.0 - 7.0 + data["dim_score"], abs=0.05)

    raw = _read_raw(data_root)
    # 形状感知：fixture 是形状 B → observations.tongue.body.tooth_marks
    assert raw["observations"]["tongue"]["body"]["tooth_marks"] == "重度"
    assert raw["manually_corrected"] is True
    assert raw.get("corrected_at")

    backup_dir = os.path.join(data_root, "records", "_backup")
    backups = os.listdir(backup_dir)
    assert len(backups) == 1 and backups[0].startswith("2026-06-25_analysis.json")
    # 备份里是修正前的旧值
    with open(os.path.join(backup_dir, backups[0]), encoding="utf-8") as f:
        assert json.load(f)["observations"]["tongue"]["body"]["tooth_marks"] == "轻度"

    # 详情页出现「含人工修正」与新分数
    html = client.get("/record/2026-06-25").get_data(as_text=True)
    assert "含人工修正" in html
    assert "重度" in html


def test_correction_unknown_indicator_rejected(client):
    resp = client.post("/record/2026-06-25/field", json={
        "dim": "tongue", "indicator": "nonsense", "value": "x"})
    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False


def test_correction_unknown_date(client):
    resp = client.post("/record/2026-01-01/field", json={
        "dim": "tongue", "indicator": "tooth_marks", "value": "重度"})
    assert resp.status_code == 400
    assert "无记录" in resp.get_json()["errors"][0]


def test_correction_lan_readonly(client):
    resp = client.post("/record/2026-06-25/field",
                       json={"dim": "tongue", "indicator": "tooth_marks",
                             "value": "重度"},
                       environ_overrides={"REMOTE_ADDR": "192.168.3.20"})
    assert resp.status_code == 403


def test_correction_warning_does_not_block(client, data_root):
    """⚠️ 级问题（如值夹带注记）不拦截保存，仅回传展示。"""
    resp = client.post("/record/2026-06-25/field", json={
        "dim": "tongue", "indicator": "tooth_marks",
        "value": "轻度（与昨日一致）"})
    assert resp.status_code == 200
    raw = _read_raw(data_root)
    assert raw["observations"]["tongue"]["body"]["tooth_marks"] == "轻度（与昨日一致）"
