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


# ---------------- 修正选项化（封闭词表按钮直选） ----------------

def test_detail_exposes_scored_options(client, data_root):
    """评分词表 key 直接作为修正选项下发（body_color 含 0 分基线，无兜底词）。"""
    import records_store
    html = client.get("/record/2026-06-25").get_data(as_text=True)
    assert "data-opts" in html  # tojson 转义非 ASCII，选项内容走视图模型断言
    rec = records_store.load_record(
        os.path.join(data_root, "records", "daily"), "2026-06-25")
    detail = records_store.record_detail(rec)
    tongue = next(d for d in detail["dims"] if d["key"] == "tongue")
    fields = {f["ind"]: f for g in tongue["groups"] for f in g["fields"]}
    assert fields["body_color"]["opts"][:2] == ["淡红", "红润"]
    assert "紫暗" in fields["body_color"]["opts"]
    assert "未见异常" not in fields["body_color"]["opts"]  # 自带 0 分基线不补兜底
    # 点刺：评分层退出，但留存词表复活为参考项选项
    assert fields["prickles"]["opts"] == ["无", "少量", "点刺", "芒刺"]


def test_detail_normal_option_when_map_has_no_zero(client, data_root):
    """词表无 0 分基线词的字段（如面色）补「未见异常」选项。"""
    import records_store
    rec = records_store.load_record(
        os.path.join(data_root, "records", "daily"), "2026-06-25")
    detail = records_store.record_detail(rec)
    face = next(d for d in detail["dims"] if d["key"] == "head_face")
    face_color = next(f for g in face["groups"] for f in g["fields"]
                      if f["ind"] == "face_color")
    assert face_color["opts"][0] == records_store.NORMAL_OPTION


def test_option_value_scores_directly(client):
    """词表 key 作为值提交：选中即得分，无静默归零。"""
    resp = client.post("/record/2026-06-25/field", json={
        "dim": "tongue", "indicator": "body_color", "value": "紫暗"})
    assert resp.status_code == 200
    assert resp.get_json()["field_score"] == 9


def test_normal_option_scores_zero_and_passes(client, data_root):
    """「未见异常」提交：validator 豁免区措辞，0 分且不触发 ❌ 拦截。"""
    resp = client.post("/record/2026-06-25/field", json={
        "dim": "head_face", "indicator": "face_color", "value": "未见异常"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert data["field_score"] == 0


def test_glossary_shipped_with_options(client, data_root):
    """术语白话注解随选项下发：舌体动态的「强硬」「痿软」带悬浮注解。"""
    import records_store
    rec = records_store.load_record(
        os.path.join(data_root, "records", "daily"), "2026-06-25")
    detail = records_store.record_detail(rec)
    tongue = next(d for d in detail["dims"] if d["key"] == "tongue")
    fields = {f["ind"]: f for g in tongue["groups"] for f in g["fields"]}
    assert "中风" in fields["body_dynamics"]["gloss"]["强硬"]
    assert "痿软" in fields["body_dynamics"]["gloss"]
    # 常用词（如「无」）不注解，避免噪音
    assert "无" not in fields["prickles"]["gloss"]
    html = client.get("/record/2026-06-25").get_data(as_text=True)
    assert "data-gloss" in html
