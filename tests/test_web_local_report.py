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
