"""web 层切片 4 测试：拍照向导（上传识图 / 双跳过 / 组装形状 B / danger 拦截 / 合并）。

vision 识图一律 mock，无真实网络调用。
"""
import io
import json
import os
import sys

import pytest

pytest.importorskip("flask")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "web"))

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


def _mock_observe(monkeypatch):
    """把识图换成固定输出（舌面给嵌套中文键，其余给简单键）。"""
    def fake(part, img_path):
        if part == "舌面":
            return {"舌质颜色": "淡红", "舌质润燥": "润泽",
                    "舌体": {"胖瘦": "正常", "齿痕": "无"},
                    "舌苔": {"颜色": "白", "厚薄": "薄白"}}, []
        return {"耳色": "淡红"} if part == "耳" else {"肤色": "正常"}, []
    monkeypatch.setattr(wizard_store, "observe_photo", fake)


def _upload(client, part):
    return client.post("/wizard/photo", data={
        "part": part, "file": (io.BytesIO(PNG), "photo.jpg"),
    }, content_type="multipart/form-data")


def test_wizard_page_renders(client):
    html = client.get("/wizard").get_data(as_text=True)
    assert "拍照向导" in html and "舌面" in html and "皮肤" in html
    assert "拍摄纪律" in html


def test_photo_upload_observes_and_saves(client, data_root, monkeypatch):
    _mock_observe(monkeypatch)
    resp = _upload(client, "舌面")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    # 中文识图键 → 形状 B 英文路径映射
    assert data["observation"]["body"]["color"] == "淡红"
    assert data["observation"]["coating"]["thickness"] == "薄白"
    today = wizard_store.datetime.date.today().isoformat()
    assert os.path.exists(os.path.join(
        data_root, "records", "photos", today, "舌面.jpg"))


def test_unmapped_keys_preserved_not_dropped(monkeypatch):
    """识图返回词表外键时不静默丢弃：进 _raw 并报告。"""
    node, unmapped = wizard_store.map_observation(
        "舌面", {"舌质颜色": "淡红", "神秘字段": "某值"})
    assert node["body"]["color"] == "淡红"
    assert unmapped == ["神秘字段"]
    assert node["_raw"]["神秘字段"] == "某值"


def _finish_all_parts(client, monkeypatch, skip_rest=True):
    _mock_observe(monkeypatch)
    _upload(client, "舌面")
    for part in ALL_PARTS[1:]:
        client.post("/wizard/skip", json={"part": part, "mode": "normal"})


def test_full_wizard_produces_shape_b_record(client, data_root, monkeypatch):
    _finish_all_parts(client, monkeypatch)
    resp = client.post("/wizard/submit", json={"mode": "new"})
    data = resp.get_json()
    assert data["ok"] is True
    today = data["date"]

    import records_store
    raw = records_store.load_record(
        os.path.join(data_root, "records", "daily"), today).raw
    assert raw["record_id"] == f"{today}-web"
    assert raw["observations"]["tongue"]["body"]["color"] == "淡红"
    # 声明正常的部位：占位写入首指标路径，计入覆盖
    assert "未拍摄（用户声明正常）" in json.dumps(
        raw["observations"]["head_face"], ensure_ascii=False)
    # P1（原著审查）：声明正常占位不计覆盖度——仅舌诊实观测 → LOW
    assert raw["confidence"] == "LOW"
    assert raw["danger_flags"]["triggered"] == []
    # 草稿已清
    assert not os.path.exists(wizard_store.draft_path(
        os.path.join(data_root, "records", "daily"), today))
    # 详情页能打开
    assert client.get(f"/record/{today}").status_code == 200


def test_submit_blocked_with_pending_parts(client, monkeypatch):
    _mock_observe(monkeypatch)
    _upload(client, "舌面")
    resp = client.post("/wizard/submit", json={"mode": "new"})
    assert resp.status_code == 400
    assert "未处理" in resp.get_json()["error"]


def test_danger_interception_two_exits(client, data_root, monkeypatch):
    """构造 danger 草稿：无确认 → 拦截；keep → 落盘保留警示。"""
    _finish_all_parts(client, monkeypatch)
    today = wizard_store.datetime.date.today().isoformat()
    daily = os.path.join(data_root, "records", "daily")
    draft = wizard_store.load_draft(daily, today)
    draft["danger_flags"] = {"triggered": ["daiyang"], "not_triggered": []}
    wizard_store.save_draft(daily, draft)

    resp = client.post("/wizard/submit", json={"mode": "new"})
    data = resp.get_json()
    assert data["ok"] is False and data["need_danger_ack"] is True
    assert data["danger"][0]["name"] == "戴阳证"
    assert not os.path.exists(os.path.join(daily, f"{today}_analysis.json"))

    resp = client.post("/wizard/submit", json={"mode": "new", "acknowledge": "keep"})
    assert resp.get_json()["ok"] is True
    import records_store
    raw = records_store.load_record(daily, today).raw
    assert raw["danger_flags"]["triggered"] == ["daiyang"]
    html = client.get(f"/record/{today}").get_data(as_text=True)
    assert "戴阳证" in html


def test_merge_mode_only_fills_uncovered(client, data_root, monkeypatch):
    """当日已有记录（舌已覆盖）→ 补充模式只写未覆盖维度，旧数据不动。"""
    import records_store
    daily = os.path.join(data_root, "records", "daily")
    # 预置一条舌诊已覆盖的当日记录
    today = wizard_store.datetime.date.today().isoformat()
    existing = {"date": today, "observations": {
        "tongue": {"body": {"color": "红绛"}}}}
    with open(os.path.join(daily, f"{today}_analysis.json"), "w",
              encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False)

    _mock_observe(monkeypatch)
    _upload(client, "舌面")  # 识图返回 body.color=淡红（与旧值冲突）
    for part in ALL_PARTS[1:]:
        client.post("/wizard/skip", json={"part": part, "mode": "normal"})
    resp = client.post("/wizard/submit", json={"mode": "merge"})
    assert resp.get_json()["ok"] is True
    raw = records_store.load_record(daily, today).raw
    assert raw["observations"]["tongue"]["body"]["color"] == "红绛"  # 旧值不动
    assert "head_face" in raw["observations"]                       # 未覆盖补上了


def test_vision_unconfigured_saves_photo_but_no_observe(tmp_path, data_root, monkeypatch):
    monkeypatch.delenv("VISION_API_KEY", raising=False)
    app = create_app(env_file=str(tmp_path / ".env"), data_root=data_root)
    c = app.test_client()
    c.post("/welcome")
    resp = c.post("/wizard/photo", data={
        "part": "舌面", "file": (io.BytesIO(PNG), "p.jpg"),
    }, content_type="multipart/form-data")
    data = resp.get_json()
    assert resp.status_code == 400
    assert data["photo_saved"] is True  # 照片不丢，识图待配置后重试


def test_inquiry_answer_written_into_record(client, data_root, monkeypatch):
    """问诊步（手足温凉）：答案按模板 inquiry 契约写入记录。"""
    _finish_all_parts(client, monkeypatch)
    resp = client.post("/wizard/inquiry", json={"answer": "厥冷（冰冷）"})
    assert resp.get_json()["ok"] is True
    resp = client.post("/wizard/submit", json={"mode": "new"})
    assert resp.get_json()["ok"] is True
    import records_store
    raw = records_store.load_record(
        os.path.join(data_root, "records", "daily"),
        resp.get_json()["date"]).raw
    assert raw["inquiry"]["手足温凉"] == {"asked": True, "answer": "厥冷（冰冷）"}


def test_declared_normal_dim_scores_none(client, data_root, monkeypatch):
    """声明正常占位维度：列表/详情按未覆盖（None）处理，不再呈 0 分。"""
    _finish_all_parts(client, monkeypatch)
    client.post("/wizard/submit", json={"mode": "new"})
    today = wizard_store.datetime.date.today().isoformat()
    html = client.get(f"/record/{today}").get_data(as_text=True)
    assert "未拍摄（用户声明正常）" in html
    assert "按未覆盖处理" in html


def test_mirror_tongue_pattern_no_false_positive():
    """「局部剥落」不得命中镜面舌探测（pattern 为「无苔」）。"""
    assert "无苔" not in "局部剥落"
    assert wizard_store.detect_danger(
        {"tongue": {"coating": {"peeling": "局部剥落"}}}) == []
    assert wizard_store.detect_danger(
        {"tongue": {"coating": {"peeling": "光剥无苔"}}}) == ["mirror_tongue"]


def test_new_danger_patterns_detected():
    """新增两条红线：直视→阳明危重、冷汗→脱阳前兆。"""
    got = wizard_store.detect_danger({"skin": {"note": "微喘直视"}})
    assert got == ["yangming_critical"]
    got = wizard_store.detect_danger({"skin": {"sweat": "冷汗如油"}})
    assert got == ["collapse_yang"]
