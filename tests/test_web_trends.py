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


def _contract(md, structured=None):
    """把 Markdown 包进 5.0 JSON 双件契约（structured + markdown）。"""
    return json.dumps({"structured": structured or {}, "markdown": md},
                      ensure_ascii=False)


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
                        lambda *a, **k: _contract("# 辨证结论\n\n**太阴**水饮。"))
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
    assert "辨证报告·全案" in html
    assert "<strong>太阴</strong>" in html  # mdmini 渲染生效
    # 旧版已备份
    assert os.listdir(os.path.join(data_root, "records", "_backup"))


def test_report_requires_llm_config(client):
    resp = client.post("/record/2026-06-25/report")
    assert resp.status_code == 400
    assert "LLM" in resp.get_json()["error"]


def test_report_contract_writes_structured_and_diet(client, data_root,
                                                    monkeypatch):
    """JSON 双件契约：structured 回写 pattern_differentiation，diet_advice 落
    report；第一张卡渲染结构化结论 + 饮食建议，且不再出现方剂块。"""
    structured = {
        "three_views": {"表里观": "里", "正邪观": "邪实", "津液观": "津亏"},
        "four_patterns": {"水证": "有", "火证": "无", "气证": "无", "血证": "无"},
        "six_diseases": "太阴病",
        "core_pathomechanism": "太阴虚寒，水饮内停",
        "diet_advice": {
            "daily_foods": [{"name": "山药", "nature": "平", "purpose": "健脾",
                             "amount": "50-100克/日", "note": "煮粥"}],
            "med_foods": [{"name": "黄芪", "nature": "微温", "purpose": "补气",
                           "amount": "5-10克/日", "note": "煎水"}],
            "avoid": [{"item": "生冷", "reason": "伤脾阳"}],
        },
    }
    monkeypatch.setattr(
        llm_client, "chat",
        lambda *a, **k: _contract("# 报告\n\n**太阴**水饮，宜山药。", structured))
    resp = client.post("/record/2026-06-25/report")
    assert resp.status_code == 200, resp.get_json()

    with open(os.path.join(data_root, "records", "daily",
                           "2026-06-25_analysis.json"), encoding="utf-8") as f:
        raw = json.load(f)
    pat = raw["pattern_differentiation"]
    assert pat["six_diseases"] == "太阴病"
    assert pat["four_patterns"]["水证"] == "有"
    assert pat["core_pathomechanism"]
    rep = raw["diagnosis"]["report"]
    assert rep["diet_advice"]["daily_foods"][0]["name"] == "山药"
    assert rep["diet_advice"]["med_foods"][0]["name"] == "黄芪"
    assert "太阴" in rep["markdown"]

    html = client.get("/record/2026-06-25").get_data(as_text=True)
    assert "饮食建议" in html and "山药" in html
    assert "忌口" in html and "生冷" in html
    assert "太阴病" in html  # 第一张卡的结构化六经
    # 四证 / 药食同源药材层 / 方剂块均不在第一张卡（细节只在完整报告卡）；
    # 数据仍存档（上方 asserts），只是不渲染
    assert "水证 · 有" not in html
    assert "此为药材，非日常食材" not in html
    assert "方义：" not in html
    assert 'class="herbs"' not in html


def test_report_non_json_rejected(client, data_root, monkeypatch):
    """模型不遵守 JSON 双件契约 → 400 且记录文件原样不动（可诊断不静默）。"""
    monkeypatch.setattr(llm_client, "chat", lambda *a, **k: "# 纯 Markdown")
    path = os.path.join(data_root, "records", "daily", "2026-06-25_analysis.json")
    with open(path, encoding="utf-8") as f:
        before = f.read()
    resp = client.post("/record/2026-06-25/report")
    assert resp.status_code == 400
    assert "JSON" in resp.get_json()["error"]
    with open(path, encoding="utf-8") as f:
        assert f.read() == before


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


def test_inquiry_denominator_dynamic_17(tmp_path, monkeypatch):
    """问诊分母 = INQUIRY_TOTAL（1 + 骨架数）：全答记录输出 17/17，不含 /16。"""
    import sys as _sys
    _sys.path.insert(0, os.path.join(_ROOT, "web"))
    import trends_store
    import wizard_store

    # 构造 17 项全答记录
    inquiry = {wizard_store.INQUIRY_SPEC["key"]: {"asked": True, "answer": "温"}}
    for item in wizard_store.INQUIRY_ITEMS:
        inquiry[item["q"]] = {"asked": True, "answer": item["options"][0]}
    raw = {"date": "2026-10-20", "observations": {}, "inquiry": inquiry}

    class Rec:
        pass
    rec = Rec()
    rec.raw = raw
    from src.record import DailyRecord
    rec = DailyRecord(raw)
    text = trends_store.build_report_input(rec)
    assert f"问诊覆盖：17/{wizard_store.INQUIRY_TOTAL}" in text
    assert "17/17" in text
    assert "/16" not in text


def test_report_guard_warns_formula_on_all_zero(tmp_path, monkeypatch):
    """审查修复：平人出口第二道防线——全 0 无红线而报告含方剂剂量 → warning。"""
    daily = tmp_path / "records" / "daily"
    daily.mkdir(parents=True)
    raw = {"date": "2026-10-20",
           "observations": {"tongue": {"body": {"color": "淡红"}}},
           "inquiry": {}}
    (daily / "2026-10-20_analysis.json").write_text(
        __import__("json").dumps(raw, ensure_ascii=False), encoding="utf-8")
    import llm_client
    monkeypatch.setattr(llm_client, "chat",
                        lambda *a, **k: _contract(
                            "辨证：建议桂枝汤 桂枝9克 白芍6克 煎服"))
    import trends_store
    result = trends_store.generate_and_store_report(
        str(daily), str(tmp_path / "records" / "_backup"),
        "2026-10-20", lambda: ("m", "u", "k"))
    assert result["ok"] is True, result
    assert "平人出口" in result.get("warning", ""), result
    # 报告仍落盘（告警不拦截，可诊断哲学）
    saved = __import__("json").loads(
        (daily / "2026-10-20_analysis.json").read_text(encoding="utf-8"))
    assert "桂枝汤" in saved["diagnosis"]["report"]["markdown"]


def test_report_includes_kb_refs(client, data_root, monkeypatch):
    """辨证输入含知识库参考段；报告落 kb_refs 溯源（命中词/文件/行号）。"""
    monkeypatch.setattr(llm_client, "chat",
                        lambda *a, **k: _contract("# 报告\n\n饮食参考库内条文。"))
    monkeypatch.setenv("LLM_API_KEY", "sk-x")
    monkeypatch.setenv("LLM_MODEL", "m")
    monkeypatch.setenv("LLM_BASE_URL", "https://x.com/v1/chat/completions")
    # fixture 有 面色晦暗 5 分（≥4 分体征词会进检索词条）
    resp = client.post("/record/2026-06-25/report")
    assert resp.status_code == 200, resp.get_json()
    with open(os.path.join(data_root, "records", "daily",
                           "2026-06-25_analysis.json"), encoding="utf-8") as f:
        raw = json.load(f)
    rep = raw["diagnosis"]["report"]
    # 有命中则带 kb_refs 溯源；无命中（冷门词）也合法，但结构须在
    import trends_store
    import records_store
    rec = records_store.load_record(os.path.join(data_root, "records", "daily"),
                                    "2026-06-25")
    text = trends_store.build_report_input(rec, rep.get("kb_refs"))
    if rep.get("kb_refs"):
        assert "知识库参考" in text
        assert rep["kb_refs"][0]["file"]
        assert rep["kb_refs"][0]["line"] > 0
        html = client.get("/record/2026-06-25").get_data(as_text=True)
        assert "知识库引用" in html


def test_kb_references_fail_safe(client, data_root, monkeypatch):
    """检索失败不阻断报告（告警后照出，无 KB 段）。"""
    import trends_store
    monkeypatch.setattr("src.retrieval.retrieve",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setenv("LLM_API_KEY", "sk-x")
    monkeypatch.setenv("LLM_MODEL", "m")
    monkeypatch.setenv("LLM_BASE_URL", "https://x.com/v1/chat/completions")
    monkeypatch.setattr(llm_client, "chat", lambda *a, **k: _contract("# ok"))
    resp = client.post("/record/2026-06-25/report")
    assert resp.status_code == 200, resp.get_json()
    with open(os.path.join(data_root, "records", "daily",
                           "2026-06-25_analysis.json"), encoding="utf-8") as f:
        assert "kb_refs" not in json.load(f)["diagnosis"]["report"]


def test_chat_truncation_fails_loudly(monkeypatch):
    """截断即失败（可诊断不静默）：finish_reason=length → RuntimeError 指明提额。"""
    class TruncatedResp:
        def read(self):
            return json.dumps({"choices": [{"message": {"content": "写了一半"},
                                            "finish_reason": "length"}]}).encode()
        def __enter__(self): return self
        def __exit__(self, *a): return False

    monkeypatch.setattr(llm_client.urllib.request, "urlopen",
                        lambda req, timeout=None: TruncatedResp())
    with pytest.raises(RuntimeError) as e:
        llm_client.chat("hi", "", "m", "https://x.com/v1/chat/completions", "sk-x")
    assert "截断" in str(e.value)
    assert "max_tokens" in str(e.value)


def test_mdmini_blockquote_and_hr_and_h4():
    """mdmini 补齐：引用块/分割线/四级标题（LLM 报告常见结构）。"""
    html = mdmini.render("> **声明**：只有望诊\n\n---\n\n#### 小节标题\n")
    assert "<blockquote" in html and "只有望诊" in html
    assert "<hr" in html
    assert "<h5>" in html or "<h6>" in html  # #### → h5 以上
    assert "####" not in html
