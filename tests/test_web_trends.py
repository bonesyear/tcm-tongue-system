"""web 层切片 5 测试：趋势页（ECharts 数据装配）+ 辨证报告生成 + mdmini。"""
import json
import os

import sys

import pytest

pytest.importorskip("flask")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "web"))

import llm_client  # noqa: E402
import mdmini  # noqa: E402
import trends_store  # noqa: E402
from app import create_app  # noqa: E402

FIXTURE = os.path.join(_ROOT, "tests", "fixtures", "2026-06-25_analysis.json")


@pytest.fixture
def data_root(tmp_path):
    d = tmp_path / "data"
    (d / "records" / "daily").mkdir(parents=True)
    # 铺一周记录（同一 fixture 复制三天并改写内部 date，够出图）
    with open(FIXTURE, encoding="utf-8") as f:
        base = json.load(f)
    for day in ("2026-06-23", "2026-06-24", "2026-06-25"):
        raw = dict(base, date=day)
        with open(os.path.join(d / "records" / "daily", f"{day}_analysis.json"),
                  "w", encoding="utf-8") as f:
            json.dump(raw, f, ensure_ascii=False)
    return str(d)


@pytest.fixture
def client(tmp_path, data_root, monkeypatch):
    for k in ("VISION_API_KEY", "WEB_ADMIN_TOKEN", "WEB_HOST"):
        monkeypatch.delenv(k, raising=False)
    app = create_app(env_file=str(tmp_path / ".env"), data_root=data_root)
    app.config["TESTING"] = True
    c = app.test_client()
    c.post("/welcome")
    return c


def test_trends_renders_week_charts(client):
    resp = client.get("/trends?week=2026-06-25")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "chart-dims" in html and "chart-radar" in html and "chart-heat" in html
    assert "本周摘要" in html
    assert "舌诊" in html  # 折线系列名进入嵌入 JSON


def test_trends_empty_week(client):
    resp = client.get("/trends?week=2025-01-01")
    assert resp.status_code == 200
    assert "没有任何记录" in resp.get_data(as_text=True)


def test_week_payload_structure(data_root):
    """数据装配直接来自纯函数：连续 7 天轴，无记录日为 None；热力无观测位留空。"""
    payload = trends_store.week_payload(
        os.path.join(data_root, "records", "daily"), "2026-06-25")
    assert payload["count"] == 3
    assert payload["dates"] == ["06-19", "06-20", "06-21", "06-22",
                                "06-23", "06-24", "06-25"]
    assert len(payload["radar"]["axes"]) == 9
    assert set(payload["dim_series"].keys()) == {
        "舌诊", "头面诊", "目诊", "耳诊", "手诊", "皮肤诊"}
    assert payload["dim_series"]["舌诊"] == [None, None, None, None,
                                             7.0, 7.0, 7.0]
    # 趋势解读标签完整映射（服务端装配，不在模板里猜）
    labels = {r["k"] for r in payload["trend_rows"]}
    assert "体质总览" in labels and "舌质" in labels


def test_report_generation_writes_back(client, data_root, monkeypatch):
    """LLM 报告：生成 → 写回 diagnosis_report → 详情页渲染 markdown。"""
    monkeypatch.setattr(llm_client, "chat",
                        lambda *a, **k: "# 辨证结论\n\n**太阴**水饮。")
    resp = client.post("/record/2026-06-25/report")
    assert resp.status_code == 200, resp.get_json()

    with open(os.path.join(data_root, "records", "daily",
                           "2026-06-25_analysis.json"), encoding="utf-8") as f:
        raw = json.load(f)
    rep = raw["diagnosis"]["report"]  # 形状 A diagnosis 容器约定
    assert "太阴" in rep["markdown"]
    assert rep["prompt_template_version"].startswith(
        "adaptive_analysis_prompt.md@")  # 模板内容哈希，非工程版本号
    assert rep["generated_at"]

    html = client.get("/record/2026-06-25").get_data(as_text=True)
    assert "辨证报告（LLM 生成）" in html
    assert "<strong>太阴</strong>" in html  # mdmini 渲染生效
    # 旧版已备份
    assert os.listdir(os.path.join(data_root, "records", "_backup"))


def test_report_requires_llm_config(client):
    resp = client.post("/record/2026-06-25/report")
    assert resp.status_code == 400
    assert "LLM" in resp.get_json()["error"]


def test_mdmini_renders_and_escapes():
    html = mdmini.render("# 标题\n\n**粗** 与 `代码`\n\n- 甲\n- 乙\n\n| A | B |\n|---|---|\n| 1 | 2 |\n\n<script>xss</script>")
    assert "<h3>标题</h3>" in html
    assert "<strong>粗</strong>" in html and "<code>代码</code>" in html
    assert "<li>甲</li>" in html
    assert "<th>A</th>" in html and "<td>2</td>" in html
    assert "<script>" not in html  # 先转义，XSS 不过堂


def test_trends_empty_week_offers_latest_link(client):
    """空周且库内有历史记录 → 显示「去看看」跳转链接，落在最近记录日所在周。"""
    import datetime as _dt
    html = client.get("/trends?week=2025-01-01").get_data(as_text=True)
    assert "没有任何记录" in html
    assert "/trends?week=2026-06-25" in html  # fixture 最近记录日


def test_trends_all_empty_keeps_original_guidance(tmp_path, monkeypatch):
    """全库无记录 → 维持原文案，无跳转链接。"""
    d = tmp_path / "empty_data"
    (d / "records" / "daily").mkdir(parents=True)
    app = create_app(env_file=str(tmp_path / ".env"), data_root=str(d))
    app.config["TESTING"] = True
    c = app.test_client()
    c.post("/welcome")
    html = c.get("/trends?week=2025-01-01").get_data(as_text=True)
    assert "没有任何记录" in html
    assert "去看看" not in html


def test_template_danger_flags_keys_in_sync():
    """形状 A 模板 danger_flags 与 records_store 红线键一致（11 + 危重舌象 8）。"""
    import json as _json
    tpl = _json.load(open(os.path.join(
        _ROOT, "templates", "multi_dim_record_template.json"), encoding="utf-8"))
    import records_store
    assert set(tpl["danger_flags"].keys()) == set(records_store.DANGER_FLAGS.keys())


def test_lower_lid_baseline_no_vocab_warning():
    """lower_lid 正常值「淡红」落词表（0 分基线），不再触发词表外告警。"""
    from src.scoring import score_indicators
    from src.dimensions import VisionDimension
    got = score_indicators(VisionDimension.EYE, {"lower_lid": "淡红"})
    assert got["lower_lid"] == 0
