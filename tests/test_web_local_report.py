"""本地规则「四证倾向速览」测试：聚合逻辑 + 设置页启用开关 + 详情页双模式。

对应 web/local_report.py 与 app.py 的 LLM_DISABLED 分支。
"""
import json
import os
import sys

import pytest

pytest.importorskip("flask")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "web"))
sys.path.insert(0, os.path.join(_ROOT, "src"))

import envfile  # noqa: E402
import local_report  # noqa: E402
from app import create_app  # noqa: E402
from src.record import DailyRecord  # noqa: E402

FIXTURE = os.path.join(_ROOT, "tests", "fixtures", "2026-06-25_analysis.json")


@pytest.fixture
def data_root(tmp_path):
    d = tmp_path / "data"
    (d / "records" / "daily").mkdir(parents=True)
    (d / "records" / "photos").mkdir(parents=True)
    import shutil
    shutil.copyfile(FIXTURE, os.path.join(
        d / "records" / "daily", "2026-06-25_analysis.json"))
    return str(d)


@pytest.fixture
def client(tmp_path, data_root, monkeypatch):
    for k in ("VISION_API_KEY", "WEB_ADMIN_TOKEN", "WEB_HOST", "LLM_DISABLED"):
        monkeypatch.delenv(k, raising=False)
    app = create_app(env_file=str(tmp_path / ".env"), data_root=data_root)
    app.config["TESTING"] = True
    c = app.test_client()
    c.post("/welcome")
    c.post("/demo")  # 确保记录存在（fixture 同名覆盖也无妨）
    return c


def _fixture_overview():
    with open(FIXTURE, encoding="utf-8") as f:
        return local_report.build_pattern_overview(DailyRecord(json.load(f)))


def test_pattern_overview_aggregates_fixture():
    """fixture 阳性体征聚为 水/血/火/气 四倾向，分值降序，出处注记随行。"""
    ov = _fixture_overview()
    assert ov["positive_n"] == 8
    names = [d["name"] for d in ov["directions"]]
    assert names == ["水证", "血证", "火证", "气证"]  # 11/11/6/6，同分按 PATTERNS 序
    assert ov["directions"][0]["total"] == 11
    water_signs = {(e["dim"], e["label"], e["s"]) for e in ov["directions"][0]["signs"]}
    assert ("舌诊", "形态", 7) in water_signs
    blood = ov["directions"][1]
    assert any(e["label"] == "面色" and e["v"] == "晦暗" and "KB L97" in e["note"]
               for e in blood["signs"])
    # 皮肤干燥（2 分）四证刻意未映射——positive_n 不含它（宁缺毋滥）
    all_labels = [e["label"] for d in ov["directions"] for e in d["signs"]]
    assert "干燥" not in all_labels


def test_pattern_overview_constitution_diet_inquiry():
    """①体质格局两轴陈述；②饮食宜忌带行号出处；③问诊优先项跳过已答。"""
    ov = _fixture_overview()
    zx = ov["constitution"]["zheng_xie"]
    assert "虚" in zx["text"] and "正虚证据" in zx["detail"] and "邪实证据" in zx["detail"]
    fl = ov["constitution"]["fluid"]
    assert fl["text"] == "水饮内停，津不上承"  # 水停 11 + 津亏 10 双轴皆在
    diet = {d["name"]: d for d in ov["diet"]}
    assert diet["水证"]["宜"].startswith("甘淡利湿")
    assert "diet-therapy.md:52" in diet["水证"]["src"]
    assert set(diet) == {"水证", "血证", "火证", "气证"}
    qs = [i["q"] for i in ov["inquiry"]]
    assert len(qs) <= 3 and "口渴？" in qs  # 水/血两名倾向的鉴别项
    assert all(i["why"] for i in ov["inquiry"])


def test_pattern_overview_all_zero_is_empty():
    """平人记录：四段皆空（页面只显示「未见阳性倾向」）。"""
    rec = DailyRecord({"date": "2026-10-23",
                       "observations": {"tongue": {"body": {"color": "淡红"}}},
                       "inquiry": {}})
    ov = local_report.build_pattern_overview(rec)
    assert ov["directions"] == [] and ov["positive_n"] == 0
    assert ov["constitution"] is None and ov["diet"] == []


def _rec(obs_tongue=None, **extra_dims):
    obs = {}
    if obs_tongue is not None:
        obs["tongue"] = obs_tongue
    obs.update(extra_dims)
    return DailyRecord({"date": "2026-10-23", "observations": obs, "inquiry": {}})


def test_thickness_direction_split():
    """苔厚薄按值分向：无苔=气证正（胃气阴伤）、焦黑=火证邪（热极）、白厚=水证——
    钉住审查 P0（原 catch-all 全部反向记水证邪实）。"""
    cases = {"无苔": ("气证", "正"), "焦黑": ("火证", "邪"), "白厚": ("水证", "邪")}
    for v, (pat, zx) in cases.items():
        ov = local_report.build_pattern_overview(
            _rec({"coating": {"thickness": v}}))
        assert ov["directions"][0]["name"] == pat, (v, ov["directions"])
        assert ov["directions"][0]["signs"][0]["rule"][2] == zx


def test_body_size_split():
    """瘦小→血证·正+津亏（原 catch-all 记水证邪实+水停，双重反向）。"""
    ov = local_report.build_pattern_overview(_rec({"body": {"shape": "瘦小"}}))
    assert ov["directions"][0]["name"] == "血证"
    assert ov["directions"][0]["signs"][0]["rule"][2] == "正"
    assert ov["constitution"]["fluid"]["text"] == "津液不足"  # 瘦小 6 分 ≥ 强度阈值


def test_moisture_vocab_current():
    """苔润燥按现行词表：滑→水证+水停；干裂→火证+津亏。"""
    ov = local_report.build_pattern_overview(_rec({"coating": {"moisture": "滑"}}))
    assert ov["directions"][0]["name"] == "水证"
    assert "水停" in ov["constitution"]["fluid"]["detail"]
    ov2 = local_report.build_pattern_overview(_rec({"coating": {"moisture": "干裂"}}))
    assert ov2["directions"][0]["name"] == "火证"
    assert "津亏" in ov2["constitution"]["fluid"]["text"] or \
        "津亏" in ov2["constitution"]["fluid"]["detail"]


def test_statement_single_side_light():
    """单边弱证据：给「倾向（轻）」，不称「为主」也不称「夹杂」（措辞对称钉住）。"""
    ov = local_report.build_pattern_overview(
        _rec(None, hand={"palm_color": "淡白"}))
    # palm 淡白 2 分 → 血证·正，单边正虚
    assert ov["constitution"]["zheng_xie"]["text"] == "正虚倾向（轻）"
    ov2 = local_report.build_pattern_overview(
        _rec(None, ear={"color": "红赤"}))
    assert ov2["constitution"]["zheng_xie"]["text"] == "邪实倾向（轻）"


def test_inquiry_non_dict_no_500():
    """inquiry 为字符串/列表等畸形时聚合不崩（审查 P1-7）。"""
    rec = DailyRecord({"date": "2026-10-23",
                       "observations": {"tongue": {"body": {"shape": "胖大"}}},
                       "inquiry": "无"})
    ov = local_report.build_pattern_overview(rec)
    assert ov["directions"][0]["name"] == "水证" and ov["inquiry"]


def test_inquiry_shape_c_answered_skipped():
    """形状 C 扁平问答（{问: "答"}）计为已答，不再重复推荐。"""
    rec = DailyRecord({"date": "2026-10-23",
                       "observations": {"tongue": {"body": {"shape": "胖大"}}},
                       "inquiry": {"小便？": "正常", "口渴？": "口不渴",
                                   "大便？": "正常"}})
    ov = local_report.build_pattern_overview(rec)
    assert ov["inquiry"] == []  # 水证鉴别三问皆已答


def test_settings_toggle_persists(client, tmp_path):
    """启用开关：不勾 → LLM_DISABLED=1；勾选 → 置空（恢复启用）。"""
    env_path = str(tmp_path / ".env")
    resp = client.post("/settings", data={
        "FORM_LLM": "1",
        "LLM_BASE_URL": "https://x.com/v1/chat/completions", "LLM_MODEL": "m"})
    assert resp.status_code == 302
    assert envfile.read_env(env_path).get("LLM_DISABLED") == "1"
    resp = client.post("/settings", data={
        "FORM_LLM": "1",
        "LLM_BASE_URL": "https://x.com/v1/chat/completions", "LLM_MODEL": "m",
        "LLM_ENABLED": "1"})
    assert resp.status_code == 302
    assert envfile.read_env(env_path).get("LLM_DISABLED") == ""


def test_detail_local_mode_replaces_report_cards(client, tmp_path):
    """LLM_DISABLED=1：报告区改本地速览；提要/全案卡与重新生成按钮都不出现。"""
    with open(str(tmp_path / ".env"), "a", encoding="utf-8") as f:
        f.write("\nLLM_DISABLED=1\n")
    html = client.get("/record/2026-06-25").get_data(as_text=True)
    assert ">四证倾向速览<" in html
    assert "本地规则引擎" in html and "不是辨证结论" in html
    assert "体质格局倾向" in html and "正邪观" in html and "津液观" in html
    assert "水证倾向" in html and "血证倾向" in html
    assert "偏胖大" in html and "KB L50" in html  # 证据行带出处注记
    assert "饮食宜忌方向" in html and "甘淡利湿" in html
    assert "明日问诊优先项" in html and "口渴？" in html
    assert "辨证报告·提要" not in html and "辨证报告·全案" not in html
    assert 'id="btn-report"' not in html


def test_detail_llm_mode_keeps_cards(tmp_path, data_root, monkeypatch):
    """三要素齐全且未禁用：提要卡在，本地速览卡不出现。"""
    for k in ("VISION_API_KEY", "WEB_ADMIN_TOKEN", "WEB_HOST", "LLM_DISABLED"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("LLM_API_KEY", "sk-x")
    monkeypatch.setenv("LLM_MODEL", "m")
    monkeypatch.setenv("LLM_BASE_URL", "https://x.com/v1/chat/completions")
    app = create_app(env_file=str(tmp_path / ".env"), data_root=data_root)
    app.config["TESTING"] = True
    c = app.test_client()
    c.post("/welcome")
    c.post("/demo")
    html = c.get("/record/2026-06-25").get_data(as_text=True)
    assert "辨证报告·提要" in html
    assert ">四证倾向速览<" not in html


def test_report_endpoint_refused_when_disabled(client, tmp_path):
    """开关关闭时生成端点明确拒绝（不误调 LLM）。"""
    with open(str(tmp_path / ".env"), "a", encoding="utf-8") as f:
        f.write("\nLLM_DISABLED=1\n")
    resp = client.post("/record/2026-06-25/report")
    assert resp.status_code == 400
    assert "关闭" in resp.get_json()["error"]
