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

import llm_client  # noqa: E402
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


def test_inquiry_multiple_questions_written(client, data_root, monkeypatch):
    """15 项问诊放开：多问多答按模板契约写入（含手足温凉）。"""
    _finish_all_parts(client, monkeypatch)
    client.post("/wizard/inquiry", json={"question": "手足温凉", "answer": "厥冷（冰冷）"})
    client.post("/wizard/inquiry", json={"question": "大便？", "answer": "便溏"})
    client.post("/wizard/inquiry", json={"question": "口苦？", "answer": "无"})
    resp = client.post("/wizard/submit", json={"mode": "new"})
    assert resp.get_json()["ok"] is True
    import records_store
    raw = records_store.load_record(
        os.path.join(data_root, "records", "daily"),
        resp.get_json()["date"]).raw
    assert raw["inquiry"]["手足温凉"]["answer"] == "厥冷（冰冷）"
    assert raw["inquiry"]["大便？"] == {"asked": True, "answer": "便溏"}
    assert raw["inquiry"]["口苦？"]["answer"] == "无"
    # 未答项不得出现（不编造）
    assert "目眩？" not in raw["inquiry"]


def test_tongue_score_max_dominant():
    """v1.7.21 舌诊口径：最重单项主导，不被多项正常稀释（原著审查 P1）。"""
    from src.scoring import score
    from src.dimensions import VisionDimension
    obs = {"body_color": "紫暗", "coating_thickness": "略厚", "coating_greasy": "微腻"}
    assert score(VisionDimension.TONGUE, obs) == 9.0  # 旧均值口径为 4.7；青紫已并入紫暗


def test_detect_danger_negation_guard():
    """否定守卫：「无苔」前 4 字内有「无/不/未/没」即不触发。"""
    assert wizard_store.detect_danger(
        {"tongue": {"coating": {"peeling": "局部无苔"}}}) == []
    assert wizard_store.detect_danger(
        {"skin": {"sweat": "无冷汗"}}) == []
    assert wizard_store.detect_danger(
        {"tongue": {"coating": {"peeling": "光剥无苔"}}}) == ["mirror_tongue"]


def test_report_input_contains_inquiry_answers(client, data_root, monkeypatch):
    """辨证输入：问诊答案全量进入，分母固定 16，未答项不出现。"""
    monkeypatch.setattr(llm_client, "chat", lambda *a, **k: "# ok")
    monkeypatch.setenv("LLM_API_KEY", "sk-x")
    monkeypatch.setenv("LLM_MODEL", "m")
    monkeypatch.setenv("LLM_BASE_URL", "https://x.com/v1/chat/completions")
    _finish_all_parts(client, monkeypatch)
    client.post("/wizard/inquiry", json={"question": "手足温凉", "answer": "厥冷（冰冷）"})
    client.post("/wizard/inquiry", json={"question": "大便？", "answer": "便溏"})
    client.post("/wizard/submit", json={"mode": "new"})
    today = wizard_store.datetime.date.today().isoformat()
    resp = client.post(f"/record/{today}/report")
    assert resp.status_code == 200, resp.get_json()
    # 检查传给 LLM 的用户输入
    import trends_store
    import records_store
    rec = records_store.load_record(
        os.path.join(data_root, "records", "daily"), today)
    text = trends_store.build_report_input(rec)
    assert "问诊覆盖：2/" + str(wizard_store.INQUIRY_TOTAL) in text
    assert "手足温凉 厥冷（冰冷）" in text
    assert "大便？ 便溏" in text
    assert "目眩？" not in text
    # 禁忌核对能扫到问诊里的「厥冷」
    assert "已观测：厥冷" in text


# ---------------- 2026-10-16 教材复查修复（P0/P1/P2） ----------------

def test_dynamics_options_include_suosuo_tunong():
    """P0：舌体动态选项补短缩/吐弄（教材六种病理舌态齐全）。"""
    import records_store
    opts = records_store.FIELD_OPTIONS["body_dynamics"]
    assert "短缩" in opts and "吐弄" in opts
    assert "危重" in records_store.GLOSSARY["短缩"]


def test_critical_tongue_flags_detected():
    """P1：危重舌象 8 项文本探测（含否定守卫）。"""
    assert wizard_store.detect_danger({"tongue": {"body": {"texture": "砂皮"}}}) \
        == ["sandy_tongue"]
    assert wizard_store.detect_danger({"tongue": {"note": "未见砂皮样改变"}}) == []
    got = wizard_store.detect_danger({"tongue": {"body": {"color": "赭黑"}}})
    assert got == ["ochre_tongue"]


def test_collapse_yang_detects_juehan_tuple_pattern():
    """P2：collapse_yang 支持多模式（冷汗/绝汗）。"""
    assert wizard_store.detect_danger({"skin": {"sweat": "冷汗如油"}}) == ["collapse_yang"]
    assert wizard_store.detect_danger({"inquiry": {"汗出时间特征？": "绝汗(大汗淋漓如油)"}}) \
        == ["collapse_yang"]


def test_inquiry_sweat_item_in_list():
    """P2：问诊骨架含汗出时间特征（第 16 项）。"""
    qs = [i["q"] for i in wizard_store.INQUIRY_ITEMS]
    assert "汗出时间特征？" in qs and len(qs) == 16


def test_inquiry_juehan_triggers_danger_on_submit(client, data_root, monkeypatch):
    """P2 端到端：问诊自陈绝汗 → 提交后 collapse_yang 红线触发。"""
    _finish_all_parts(client, monkeypatch)
    client.post("/wizard/inquiry",
                json={"question": "汗出时间特征？", "answer": "绝汗(大汗淋漓如油)"})
    # 红线拦截层：未确认不直接落盘
    resp = client.post("/wizard/submit", json={"mode": "new"})
    d = resp.get_json()
    assert d["need_danger_ack"] is True
    assert any(f["key"] == "collapse_yang" for f in d["danger"])
    resp = client.post("/wizard/submit", json={"mode": "new", "acknowledge": "keep"})
    assert resp.get_json()["ok"] is True
    import records_store
    raw = records_store.load_record(
        os.path.join(data_root, "records", "daily"),
        resp.get_json()["date"]).raw
    assert raw["inquiry"]["汗出时间特征？"]["answer"] == "绝汗(大汗淋漓如油)"
    assert "collapse_yang" in raw["danger_flags"]["triggered"]


def test_detect_danger_no_cross_field_negation_bleed():
    """审查高危修复：否定窗口不再跨字段出血（无汗+绝汗 → 绝汗仍触发）。"""
    assert wizard_store.detect_danger({
        "inquiry": {"有汗or无汗？": "无汗", "汗出时间特征？": "绝汗(大汗淋漓如油)"}
    }) == ["collapse_yang"]
    # 观察值侧同样：前字段以「无」结尾不抑制后字段红线词
    assert "tongue_rigid" in wizard_store.detect_danger(
        {"tongue": {"prickles": "无", "dynamics": "强硬"}})
    # 字段内否定语义保持抑制
    assert wizard_store.detect_danger({"skin": {"sweat": "无冷汗"}}) == []


def test_sweat_question_has_healthy_exit():
    """「有汗or无汗」含退出项「没有外感不适」（主人批准②）。"""
    item = next(i for i in wizard_store.INQUIRY_ITEMS
                if i["q"] == "有汗or无汗？")
    assert item["options"] == ["有汗", "无汗", "没有外感不适"]


def test_prompt_has_healthy_exit_branch():
    """模板含「平人出口」明文分支（主人批准③）：六维全 0 + 四证皆无不出方。"""
    import io as _io
    prompt = _io.open(os.path.join(
        _ROOT, "templates", "adaptive_analysis_prompt.md"),
        encoding="utf-8").read()
    assert "平人出口" in prompt
    assert "未见明显病证" in prompt
    assert prompt.count("平人出口") >= 2  # HIGH 与 MEDIUM 两处


def test_inquiry_clear_all(client, data_root, monkeypatch):
    """清除全部已选：clear_all 清空草稿问诊答案。"""
    _finish_all_parts(client, monkeypatch)
    client.post("/wizard/inquiry", json={"question": "手足温凉", "answer": "凉"})
    client.post("/wizard/inquiry", json={"question": "大便？", "answer": "便溏"})
    today = wizard_store.datetime.date.today().isoformat()
    daily = os.path.join(data_root, "records", "daily")
    draft = wizard_store.load_draft(daily, today)
    assert len(draft["inquiry"]) == 2

    resp = client.post("/wizard/inquiry", json={"clear_all": True})
    assert resp.get_json()["ok"] is True
    draft = wizard_store.load_draft(daily, today)
    assert draft["inquiry"] == {}


def test_inquiry_unknown_question_rejected(client):
    """审查修复：问诊键名白名单——任意键不得注入记录。"""
    resp = client.post("/wizard/inquiry",
                       json={"question": "随便编的问题", "answer": "x"})
    assert resp.status_code == 400


# ---------------- 第 8 步草稿就地修正（/wizard/field） ----------------

def test_wizard_field_updates_draft_at_b_path(client, data_root, monkeypatch):
    """草稿修正写到形状 B 正确路径，提交后值进记录。"""
    _finish_all_parts(client, monkeypatch)
    resp = client.post("/wizard/field", json={
        "part": "舌面", "indicator": "body_color", "value": "紫暗"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    draft = wizard_store.load_draft(
        os.path.join(data_root, "records", "daily"),
        __import__("datetime").date.today().isoformat())
    assert draft["parts"]["舌面"]["observation"]["body"]["color"] == "紫暗"
    resp = client.post("/wizard/submit", json={"mode": "new"})
    assert resp.get_json()["ok"] is True
    import records_store
    raw = records_store.load_record(
        os.path.join(data_root, "records", "daily"),
        resp.get_json()["date"]).raw
    assert raw["observations"]["tongue"]["body"]["color"] == "紫暗"


def test_wizard_field_rejects_unknown(client):
    resp = client.post("/wizard/field", json={
        "part": "舌面", "indicator": "nonsense", "value": "x"})
    assert resp.status_code == 400
    resp = client.post("/wizard/field", json={
        "part": "不存在", "indicator": "body_color", "value": "红"})
    assert resp.status_code == 400


def test_wizard_field_danger_feedback(client, data_root, monkeypatch):
    """改成红线词 → 响应带 danger；提交时拦截层同口径触发。"""
    _finish_all_parts(client, monkeypatch)
    resp = client.post("/wizard/field", json={
        "part": "舌面", "indicator": "body_dynamics", "value": "强硬"})
    assert "tongue_rigid" in resp.get_json()["danger"]
    resp = client.post("/wizard/submit", json={"mode": "new"})
    d = resp.get_json()
    assert d["need_danger_ack"] is True
    assert any(f["key"] == "tongue_rigid" for f in d["danger"])


def test_wizard_field_rejects_non_observed_part(client, data_root, monkeypatch):
    """复审修复：跳过/未拍部位不可写——防凭空造「无照片伪观察」。"""
    _finish_all_parts(client, monkeypatch)
    resp = client.post("/wizard/field", json={
        "part": "耳", "indicator": "color", "value": "红赤"})
    assert resp.status_code == 400
    assert "未识图" in resp.get_json()["error"]


def test_wizard_field_rejects_cross_part_write(client, data_root, monkeypatch):
    """复审修复：舌底不可写舌面字段（共享舌诊维度，防静默顶值）。"""
    _finish_all_parts(client, monkeypatch)
    # 给舌底造一个 observed 状态（ mock 识图）
    client.post("/wizard/skip", json={"part": "舌底", "mode": "uncovered"})
    draft = wizard_store.load_draft(
        os.path.join(data_root, "records", "daily"),
        __import__("datetime").date.today().isoformat())
    draft["parts"]["舌底"] = {"status": "observed",
                              "observation": {"sublingual": {"vein_color": "淡紫"}}}
    wizard_store.save_draft(os.path.join(data_root, "records", "daily"), draft)
    resp = client.post("/wizard/field", json={
        "part": "舌底", "indicator": "body_color", "value": "红"})
    assert resp.status_code == 400
    # 但舌底本域（sublingual）可写
    resp = client.post("/wizard/field", json={
        "part": "舌底", "indicator": "sublingual_color", "value": "紫暗"})
    assert resp.status_code == 200


def test_wizard_field_rejects_out_of_vocab_value(client, data_root, monkeypatch):
    """复审修复：封闭选项即时校验——词表外措辞 400。"""
    _finish_all_parts(client, monkeypatch)
    resp = client.post("/wizard/field", json={
        "part": "舌面", "indicator": "body_color", "value": "随便描述"})
    assert resp.status_code == 400
    assert "词表" in resp.get_json()["error"]


def test_wizard_field_adds_missing_field(client, data_root, monkeypatch):
    """复审修复：模型漏报的字段（如裂纹）可在第 8 步补录。"""
    _finish_all_parts(client, monkeypatch)
    resp = client.post("/wizard/field", json={
        "part": "舌面", "indicator": "fissure", "value": "深裂"})
    assert resp.status_code == 200
    draft = wizard_store.load_draft(
        os.path.join(data_root, "records", "daily"),
        __import__("datetime").date.today().isoformat())
    assert draft["parts"]["舌面"]["observation"]["body"]["cracks"] == "深裂"
