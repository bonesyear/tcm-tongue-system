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
    c.post("/welcome", headers={"Origin": "http://localhost"})
    return c


def test_trends_renders_week_charts(client):
    resp = client.get("/trends?week=2026-06-25")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "chart-dims" in html and "chart-radar" in html and "chart-heat" in html
    assert "本周摘要" in html
    assert "舌诊" in html  # 折线系列名进入嵌入 JSON


def test_trends_and_record_mark_scores_as_unvalidated_interface_metrics(client):
    for path in ("/trends?week=2026-06-25", "/record/2026-06-25"):
        resp = client.get(path)
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert "未经验证的界面指标" in html
        assert "不作为疾病严重度或处方依据" in html
        assert "总分及历史重算结果未获独立医学验证" in html


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
        "lifestyle": {"作息": "亥时前入睡，午后小憩半刻",
                      "情志": "少思虑，饭后散步十五分钟",
                      "预期改善": "舌体回缩、齿痕变浅"},
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
    assert rep["lifestyle"]["作息"] == "亥时前入睡，午后小憩半刻"
    assert rep["lifestyle"]["预期改善"]
    assert "太阴" in rep["markdown"]

    html = client.get("/record/2026-06-25").get_data(as_text=True)
    assert "饮食建议" in html and "山药" in html
    assert "忌口" in html and "生冷" in html
    assert "太阴病" in html  # 第一张卡的结构化六经
    # 起居情志由 structured.lifestyle 经 Jinja 渲染进提要卡
    assert ">起居情志<" in html and "亥时前入睡" in html and "舌体回缩" in html
    # 四证 / 药食同源药材层 / 方剂块均不在第一张卡（细节只在完整报告卡）；
    # 数据仍存档（上方 asserts），只是不渲染
    assert "水证 · 有" not in html
    assert "此为药材，非日常食材" not in html
    assert "方义：" not in html
    assert 'class="herbs"' not in html


def test_template_dose_single_value_and_flat_care():
    """任务书收口（2026-10-21）：剂量确定量禁区间；调理建议段退出 markdown；
    起居情志入 structured.lifestyle 契约。"""
    with open(os.path.join(_ROOT, "templates", "adaptive_analysis_prompt.md"),
              encoding="utf-8") as f:
        t = f.read()
    assert "[剂量范围]" not in t                    # 旧区间占位符已去
    assert "确定剂量" in t and "X–Yg" in t          # 单值规则 + 区间禁令
    assert "不得超过《中国药典》常用量上限" in t      # 药典上限硬约束（防汉制大换算）
    assert "禁止缩进嵌套子列表" in t                  # mdmini 只支持顶层列表
    assert "**煎服法**" in t                           # 方剂建议含煎服法字段（v1.8.24）
    assert "须执业中医师面诊后使用" in t             # 警示语保留且紧靠
    assert "**调理建议**" not in t                   # markdown 不再输出调理段
    assert '"lifestyle"' in t                        # 契约含起居情志字段


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
    c.post("/welcome", headers={"Origin": "http://localhost"})
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
    """候选条文随输入和报告保存，但不宣称为模型实际引用。"""
    monkeypatch.setattr(llm_client, "chat",
                        lambda *a, **k: _contract("# 报告\n\n饮食参考库内条文。"))
    monkeypatch.setenv("LLM_API_KEY", "sk-x")
    monkeypatch.setenv("LLM_MODEL", "m")
    monkeypatch.setenv("LLM_BASE_URL", "https://x.com/v1/chat/completions")
    resp = client.post("/record/2026-06-25/report")
    assert resp.status_code == 200, resp.get_json()
    with open(os.path.join(data_root, "records", "daily",
                           "2026-06-25_analysis.json"), encoding="utf-8") as f:
        raw = json.load(f)
    rep = raw["diagnosis"]["report"]
    import trends_store
    import records_store
    rec = records_store.load_record(os.path.join(data_root, "records", "daily"),
                                    "2026-06-25")
    text = trends_store.build_report_input(rec, rep.get("kb_refs"))
    assert rep["kb_refs"], "通用锚词应保证候选参考非空"
    assert "知识库候选参考" in text
    assert "不等同模型实际引用" in text
    assert rep["kb_status"] == "retrieved"
    assert rep["kb_root"] and rep["kb_revision"]
    assert rep["kb_refs"][0]["file"]
    assert rep["kb_refs"][0]["line"] > 0
    html = client.get("/record/2026-06-25").get_data(as_text=True)
    assert "知识库候选参考" in html
    assert "不等同实际引用" in html


def test_report_http_uses_unified_and_scopes_category_refs(client, data_root, monkeypatch):
    import kb_evidence
    seen = {}
    original = kb_evidence._kb_references_unified

    def capture(rec, kb_roots, anchor_terms=None, cache_root=None):
        seen['roots'] = kb_roots
        seen['cache_root'] = cache_root
        return original(rec, kb_roots, anchor_terms=anchor_terms, cache_root=cache_root)

    monkeypatch.setattr(kb_evidence, '_kb_references_unified', capture)
    monkeypatch.setattr(llm_client, 'chat', lambda *args, **kwargs: _contract('# 合成报告'))
    monkeypatch.setenv('LLM_API_KEY', 'sk-x')
    monkeypatch.setenv('LLM_MODEL', 'm')
    monkeypatch.setenv('LLM_BASE_URL', 'https://x.com/v1/chat/completions')
    resp = client.post('/record/2026-06-25/report')
    assert resp.status_code == 200, resp.get_json()
    assert set(seen['roots']) == {'constitution', 'diet', 'formula'}
    with open(os.path.join(data_root, 'records', 'daily',
                           '2026-06-25_analysis.json'), encoding='utf-8') as f:
        report = json.load(f)['diagnosis']['report']
    for category, info in report['kb_categories'].items():
        expected = [ref for ref in report['kb_refs'] if ref['category'] == category]
        assert info['refs'] == expected
        assert info['status'] == ('retrieved' if expected else 'no_hits')


def test_kb_references_fail_safe(client, data_root, monkeypatch):
    """检索失败不阻断报告，但明确保存并展示 error 状态。"""
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
        report = json.load(f)["diagnosis"]["report"]
    assert "kb_refs" not in report
    assert report["kb_status"] == "error" and report["kb_error"] == "boom"
    html = client.get("/record/2026-06-25").get_data(as_text=True)
    assert "知识库不可用" in html and "报告未经库内校核" in html


def test_env_file_kb_root_drives_report_and_staleness(tmp_path, data_root, monkeypatch):
    first = tmp_path / 'first-kb'
    second = tmp_path / 'second-kb'
    for root, text in ((first, '第一份合成资料'), (second, '第二份合成资料')):
        root.mkdir()
        (root / 'custom.md').write_text(f'忌口：{text}\n', encoding='utf-8')
    monkeypatch.delenv('TCM_KB_ROOT', raising=False)
    monkeypatch.setenv('LLM_API_KEY', 'sk-x')
    monkeypatch.setenv('LLM_MODEL', 'm')
    monkeypatch.setenv('LLM_BASE_URL', 'https://x.com/v1/chat/completions')
    monkeypatch.setattr(llm_client, 'chat', lambda *a, **k: _contract('# ok'))
    import envfile
    env = tmp_path / '.env'
    envfile.write_env(str(env), {'TCM_KB_ROOT': str(first)})
    app = create_app(env_file=str(env), data_root=data_root)
    app.config['TESTING'] = True
    client = app.test_client()
    client.post('/welcome', headers={'Origin': 'http://localhost'})
    response = client.post('/record/2026-06-25/report')
    assert response.status_code == 200, response.get_json()
    with open(os.path.join(data_root, 'records', 'daily',
                           '2026-06-25_analysis.json'), encoding='utf-8') as f:
        report = json.load(f)['diagnosis']['report']
    assert report['kb_status'] == 'retrieved'
    assert report['kb_root'] == str(first)
    assert report['kb_refs'][0]['excerpt'].endswith('第一份合成资料')

    envfile.write_env(str(env), {'TCM_KB_ROOT': str(second)})
    html = client.get('/record/2026-06-25').get_data(as_text=True)
    assert '报告已过期' in html
    assert '知识库目录或内容已变化' in html


def test_no_kb_report_discloses_state_in_prompt_metadata_and_page(
        tmp_path, data_root, monkeypatch):
    monkeypatch.delenv('TCM_KB_ROOT', raising=False)
    monkeypatch.setenv('LLM_API_KEY', 'sk-x')
    monkeypatch.setenv('LLM_MODEL', 'm')
    monkeypatch.setenv('LLM_BASE_URL', 'https://x.com/v1/chat/completions')
    captured = {}

    def fake_chat(user_input, *args, **kwargs):
        captured['input'] = user_input
        return _contract('# ok')

    monkeypatch.setattr(llm_client, 'chat', fake_chat)
    app = create_app(env_file=str(tmp_path / '.env'), data_root=data_root)
    app.config['TESTING'] = True
    client = app.test_client()
    client.post('/welcome', headers={'Origin': 'http://localhost'})
    response = client.post('/record/2026-06-25/report')
    assert response.status_code == 200, response.get_json()
    with open(os.path.join(data_root, 'records', 'daily',
                           '2026-06-25_analysis.json'), encoding='utf-8') as f:
        report = json.load(f)['diagnosis']['report']
    assert report['kb_status'] == 'unconfigured' and report['kb_revision'] == ''
    assert captured['input'].count('状态：未配置') == 3
    assert '不得输出体质、四证、六经等辨证内容' in captured['input']
    assert '不得输出饮食宜忌或食疗建议' in captured['input']
    assert '不得输出具体方剂、方义或剂量' in captured['input']
    html = client.get('/record/2026-06-25').get_data(as_text=True)
    assert '缺少中医体质辨证知识库' in html
    assert '缺少食疗知识库' in html and '缺少方剂知识库' in html
    assert '辨证报告·全案' not in html


def test_missing_formula_rejects_formula_output_without_saving(
        tmp_path, data_root, monkeypatch):
    constitution = tmp_path / 'constitution'
    diet = tmp_path / 'diet'
    for root in (constitution, diet):
        root.mkdir()
    (constitution / 'body.md').write_text('体质合成内容\n', encoding='utf-8')
    (diet / 'food.md').write_text('忌口：合成食材\n', encoding='utf-8')
    monkeypatch.delenv('TCM_KB_ROOT', raising=False)
    monkeypatch.setenv('LLM_API_KEY', 'sk-x')
    monkeypatch.setenv('LLM_MODEL', 'm')
    monkeypatch.setenv('LLM_BASE_URL', 'https://x.com/v1/chat/completions')
    structured = {
        'three_views': {'表里': '里'}, 'four_patterns': {},
        'six_diseases': '太阴', 'core_pathomechanism': '合成病机',
        'diet_advice': {'daily_foods': [
            {'name': '合成食材', 'nature': '平', 'purpose': '测试',
             'amount': '1份', 'note': '合成'}]},
        'lifestyle': {},
    }
    monkeypatch.setattr(llm_client, 'chat',
                        lambda *a, **k: _contract('# 全案\n## 五、方剂建议\n桂枝汤 9g', structured))
    import envfile
    env = tmp_path / '.env'
    envfile.write_env(str(env), {
        'TCM_KB_CONSTITUTION_ROOT': str(constitution),
        'TCM_KB_DIET_ROOT': str(diet)})
    app = create_app(env_file=str(env), data_root=data_root)
    app.config['TESTING'] = True
    client = app.test_client()
    client.post('/welcome', headers={'Origin': 'http://localhost'})
    response = client.post('/record/2026-06-25/report')
    assert response.status_code == 400
    assert '缺少方剂知识库' in response.get_json()['error']
    with open(os.path.join(data_root, 'records', 'daily',
                           '2026-06-25_analysis.json'), encoding='utf-8') as f:
        raw = json.load(f)
    assert 'diagnosis' not in raw
    html = client.get('/record/2026-06-25').get_data(as_text=True)
    assert '桂枝汤' not in html and '辨证报告·全案' not in html
    assert '缺少方剂知识库' in html


def test_missing_diet_or_constitution_rejects_structured_output(tmp_path, monkeypatch):
    monkeypatch.delenv('TCM_KB_ROOT', raising=False)
    daily = tmp_path / 'records' / 'daily'
    daily.mkdir(parents=True)
    with open(FIXTURE, encoding='utf-8') as f:
        raw = json.load(f)
    with open(daily / '2026-06-25_analysis.json', 'w', encoding='utf-8') as f:
        json.dump(raw, f, ensure_ascii=False)
    cases = [
        ({'diet_advice': {'daily_foods': []}}, '缺少食疗知识库'),
        ({'six_diseases': '太阴'}, '缺少中医体质辨证知识库'),
    ]
    for structured, expected in cases:
        monkeypatch.setattr(llm_client, 'chat', lambda *a, **k: _contract('# ok', structured))
        result = trends_store.generate_and_store_report(
            str(daily), str(tmp_path / 'records' / '_backup'), '2026-06-25',
            lambda: ('m', 'u', 'k'))
        assert result['ok'] is False and expected in result['error']


def test_configured_kb_without_hits_has_distinct_status(tmp_path, data_root, monkeypatch):
    root = tmp_path / 'kb'
    root.mkdir()
    (root / 'custom.md').write_text('没有相关锚词的合成内容\n', encoding='utf-8')
    monkeypatch.delenv('TCM_KB_ROOT', raising=False)
    monkeypatch.setenv('LLM_API_KEY', 'sk-x')
    monkeypatch.setenv('LLM_MODEL', 'm')
    monkeypatch.setenv('LLM_BASE_URL', 'https://x.com/v1/chat/completions')
    monkeypatch.setattr(llm_client, 'chat', lambda *a, **k: _contract('# ok'))
    import envfile
    env = tmp_path / '.env'
    envfile.write_env(str(env), {'TCM_KB_ROOT': str(root)})
    app = create_app(env_file=str(env), data_root=data_root)
    app.config['TESTING'] = True
    client = app.test_client()
    client.post('/welcome', headers={'Origin': 'http://localhost'})
    response = client.post('/record/2026-06-25/report')
    assert response.status_code == 200, response.get_json()
    with open(os.path.join(data_root, 'records', 'daily',
                           '2026-06-25_analysis.json'), encoding='utf-8') as f:
        report = json.load(f)['diagnosis']['report']
    assert report['kb_status'] == 'no_hits' and 'kb_refs' not in report
    html = client.get('/record/2026-06-25').get_data(as_text=True)
    assert '本次未命中知识库条文' in html


def test_kb_reference_excerpts_have_per_item_and_total_limits(data_root, monkeypatch):
    import records_store
    rec = records_store.load_record(os.path.join(data_root, 'records', 'daily'),
                                    '2026-06-25')
    calls = []

    def fake_retrieve(term, **kwargs):
        calls.append((term, kwargs.get('kb_root')))
        return {'results': [{'file': 'long.md', 'line': len(calls),
                             'content': 'x' * 5000}]}

    monkeypatch.setattr('src.retrieval.retrieve', fake_retrieve)
    refs = trends_store._kb_references(rec, kb_root='synthetic-root')
    assert len(refs) == 10
    assert all(len(ref['excerpt']) <= trends_store.MAX_KB_EXCERPT_CHARS for ref in refs)
    assert sum(len(ref['excerpt']) for ref in refs) <= trends_store.MAX_KB_TOTAL_CHARS
    assert calls and all(root == 'synthetic-root' for _, root in calls)


def test_chat_truncation_fails_loudly(monkeypatch):
    """截断即失败（可诊断不静默）：finish_reason=length → RuntimeError 指明提额。"""
    import io
    import safe_fetch

    class TruncatedResp:
        def __init__(self):
            self.stream = io.BytesIO(json.dumps(
                {"choices": [{"message": {"content": "写了一半"},
                              "finish_reason": "length"}]}).encode())
        def read(self, size=-1): return self.stream.read(size)
        def __enter__(self): return self
        def __exit__(self, *a): return False

    monkeypatch.setattr(safe_fetch, "urlopen",
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


def test_trends_uses_filename_date_when_record_date_differs(client, data_root):
    daily = os.path.join(data_root, "records", "daily")
    for name in os.listdir(daily):
        os.unlink(os.path.join(daily, name))
    with open(FIXTURE, encoding="utf-8") as f:
        raw = json.load(f)
    with open(os.path.join(daily, "2026-06-30_analysis.json"), "w",
              encoding="utf-8") as f:
        json.dump(raw, f, ensure_ascii=False)

    resp = client.get("/trends?week=2026-06-30")

    assert resp.status_code == 200
    assert "chart-radar" in resp.get_data(as_text=True)


def test_kb_references_reserve_space_for_daily_signs(client, data_root, monkeypatch):
    def fake_retrieve(term, **kwargs):
        return {"results": [
            {"file": f"{term}.md", "line": line, "content": f"{term} 条文"}
            for line in (1, 2)
        ]}

    monkeypatch.setattr("src.retrieval.retrieve", fake_retrieve)
    monkeypatch.setenv("LLM_API_KEY", "sk-x")
    monkeypatch.setenv("LLM_MODEL", "m")
    monkeypatch.setenv("LLM_BASE_URL", "https://x.com/v1/chat/completions")
    monkeypatch.setattr(llm_client, "chat", lambda *a, **k: _contract("# ok"))

    resp = client.post("/record/2026-06-25/report")

    assert resp.status_code == 200, resp.get_json()
    with open(os.path.join(data_root, "records", "daily",
                           "2026-06-25_analysis.json"), encoding="utf-8") as f:
        refs = json.load(f)["diagnosis"]["report"]["kb_refs"]
    anchor_terms = {"忌口", "适宜", "食疗", "煎服", "温覆"}
    assert refs
    assert {h["term"] for h in refs} - anchor_terms


def test_radar_uses_actual_record_dates(client, data_root):
    payload = trends_store.week_payload(
        os.path.join(data_root, "records", "daily"), "2026-06-25")

    assert payload["radar"]["first_date"] == "2026-06-23"
    assert payload["radar"]["last_date"] == "2026-06-25"
    html = client.get("/trends?week=2026-06-25").get_data(as_text=True)
    assert "周首日" not in html and "周末日" not in html
    assert "WEEK.radar.first_date" in html
    assert "WEEK.radar.last_date" in html


def test_report_input_lists_unknown_and_blocks_healthy_exit():
    from src.record import DailyRecord
    rec = DailyRecord({"date": "2026-06-25", "observations": {
        "tongue": {"coating": {"moisture": "无法判读的描述"}},
    }, "inquiry": {}})

    text = trends_store.build_report_input(rec)

    assert "未知指标：coating_moisture" in text
    assert "不得进入平人出口" in text


@pytest.mark.parametrize("raw", [
    {"date": "2026-06-26", "observations": {"tongue": {"body": {"color": "淡红"}}},
     "inquiry": {"恶寒or恶热？": {"asked": True, "answer": "恶寒"}},
     "danger_flags": {"triggered": [], "not_triggered": []}},
    {"date": "2026-06-26", "observations": {"tongue": {"body": {"color": "无法判读"}}},
     "inquiry": {}, "danger_flags": {"triggered": [], "not_triggered": []}},
], ids=["positive-inquiry", "unknown-observation"])
def test_report_guard_does_not_treat_non_eligible_as_healthy(data_root, monkeypatch, raw):
    daily = os.path.join(data_root, "records", "daily")
    with open(os.path.join(daily, "2026-06-26_analysis.json"), "w",
              encoding="utf-8") as f:
        json.dump(raw, f, ensure_ascii=False)
    monkeypatch.setattr(llm_client, "chat",
                        lambda *a, **k: _contract("桂枝汤 12g"))

    result = trends_store.generate_and_store_report(
        daily, os.path.join(data_root, "records", "_backup"), "2026-06-26",
        lambda: ("m", "u", "k"))

    assert result["ok"] is True
    assert "warning" not in result


def test_report_state_legacy_only_stale_after_modification():
    from src.record import DailyRecord
    raw = {"date": "2026-06-25", "observations": {"tongue": {"body": {"color": "淡红"}}},
           "diagnosis": {"report": {"markdown": "OLD", "generated_at": "2026-01-01T00:00:00"}}}
    rec = DailyRecord(raw)
    assert trends_store.report_state(rec)["stale"] is False

    raw["manually_corrected"] = True
    raw["corrected_at"] = "2026-02-01T00:00:00"
    rec = DailyRecord(raw)
    state = trends_store.report_state(rec)
    assert state["stale"] is True
    assert state["reasons"]

    raw["corrected_at"] = "2025-12-01T00:00:00"
    raw["derived_meta"] = {"updated_at": "2026-03-01T00:00:00"}
    rec = DailyRecord(raw)
    assert trends_store.report_state(rec)["stale"] is True


def test_report_state_compares_hash_and_ruleset():
    from src.derived import observation_input_hash
    from src.record import DailyRecord
    from src.scoring import SCORING_RULESET_VERSION
    raw = {"date": "2026-06-25", "observations": {"tongue": {"body": {"color": "淡红"}}},
           "diagnosis": {"report": {"markdown": "CURRENT", "generated_at": "2026-01-01T00:00:00"}}}
    rec = DailyRecord(raw)
    report = raw["diagnosis"]["report"]
    report["input_hash"] = observation_input_hash(rec)
    report["ruleset_version"] = SCORING_RULESET_VERSION
    report["prompt_template_version"] = trends_store._template_version(
        os.path.join(_ROOT, "templates", "adaptive_analysis_prompt.md"))

    assert trends_store.report_state(rec)["stale"] is False
    rec = DailyRecord({**raw, "observations": {"tongue": {"body": {"color": "红"}}}})
    assert trends_store.report_state(rec)["stale"] is True


def test_generate_report_stores_derived_metadata(client, data_root, monkeypatch):
    import records_store
    from src.derived import observation_input_hash
    from src.scoring import SCORING_RULESET_VERSION
    monkeypatch.setattr(llm_client, "chat", lambda *a, **k: _contract("# current"))

    resp = client.post("/record/2026-06-25/report")

    assert resp.status_code == 200, resp.get_json()
    with open(os.path.join(data_root, "records", "daily",
                           "2026-06-25_analysis.json"), encoding="utf-8") as f:
        raw = json.load(f)
    rep = raw["diagnosis"]["report"]
    rec = records_store.load_record(
        os.path.join(data_root, "records", "daily"), "2026-06-25")
    assert rep["input_hash"] == observation_input_hash(rec)
    assert rep["ruleset_version"] == SCORING_RULESET_VERSION
    assert rep["generator_version"]
    assert raw["derived_meta"]["input_hash"] == rep["input_hash"]
    assert raw["derived_meta"]["scoring_ruleset_version"] == SCORING_RULESET_VERSION


def test_merge_marks_existing_report_stale():
    import wizard_store
    existing = {
        "date": "2026-06-25",
        "observations": {"tongue": {"body": {"color": "淡红"}}},
        "diagnosis": {"report": {"markdown": "OLD-REPORT",
                                 "generated_at": "2026-01-01T00:00:00"}},
        "danger_flags": {"triggered": [], "not_triggered": []},
    }
    parts = {}
    for part in wizard_store.PARTS:
        name = part["part"]
        if name == "头面":
            parts[name] = {"status": "manual", "observation": {"face": {"color": "苍白"}}}
        else:
            parts[name] = {"status": "skip_uncovered"}

    merged = wizard_store.assemble_record(
        {"date": "2026-06-25", "parts": parts}, "test",
        existing_raw=existing, merge_only_uncovered=True)

    assert trends_store.report_state(merged)["stale"] is True


def test_stale_report_hidden_from_current_detail(client, data_root):
    raw = {
        "date": "2026-06-25",
        "observations": {"tongue": {"body": {"color": "淡红"}}},
        "pattern_differentiation": {"six_diseases": "OLD-PATTERN"},
        "diagnosis": {"report": {"markdown": "OLD-REPORT",
                                 "generated_at": "2026-01-01T00:00:00"}},
        "manually_corrected": True,
        "corrected_at": "2026-02-01T00:00:00",
    }
    with open(os.path.join(data_root, "records", "daily",
                           "2026-06-25_analysis.json"), "w", encoding="utf-8") as f:
        json.dump(raw, f, ensure_ascii=False)

    html = client.get("/record/2026-06-25").get_data(as_text=True)

    assert "报告已过期" in html
    assert "OLD-REPORT" not in html
    assert "OLD-PATTERN" not in html


def test_current_report_with_matching_metadata_is_visible(client, data_root):
    from src.derived import DERIVED_GENERATOR_VERSION, observation_input_hash
    from src.record import DailyRecord
    from src.scoring import SCORING_RULESET_VERSION
    raw = {
        "date": "2026-06-25",
        "observations": {"tongue": {"body": {"color": "淡红"}}},
        "pattern_differentiation": {"six_diseases": "CURRENT-PATTERN"},
        "diagnosis": {"report": {"markdown": "CURRENT-REPORT",
                                 "generated_at": "2026-01-01T00:00:00"}},
    }
    rec = DailyRecord(raw)
    report = raw["diagnosis"]["report"]
    report.update({
        "input_hash": observation_input_hash(rec),
        "ruleset_version": SCORING_RULESET_VERSION,
        "generator_version": DERIVED_GENERATOR_VERSION,
        "prompt_template_version": trends_store._template_version(
            os.path.join(_ROOT, "templates", "adaptive_analysis_prompt.md")),
    })
    with open(os.path.join(data_root, "records", "daily",
                           "2026-06-25_analysis.json"), "w", encoding="utf-8") as f:
        json.dump(raw, f, ensure_ascii=False)

    html = client.get("/record/2026-06-25").get_data(as_text=True)

    assert "CURRENT-REPORT" in html
    assert "CURRENT-PATTERN" in html
    assert "报告已过期" not in html


def test_stale_report_offers_regeneration_when_llm_ready(client, data_root):
    import envfile
    raw = {
        "date": "2026-06-25",
        "observations": {"tongue": {"body": {"color": "淡红"}}},
        "pattern_differentiation": {"six_diseases": "OLD-PATTERN"},
        "diagnosis": {"report": {"markdown": "OLD-REPORT",
                                 "generated_at": "2026-01-01T00:00:00"}},
        "manually_corrected": True,
        "corrected_at": "2026-02-01T00:00:00",
    }
    with open(os.path.join(data_root, "records", "daily",
                           "2026-06-25_analysis.json"), "w", encoding="utf-8") as f:
        json.dump(raw, f, ensure_ascii=False)
    envfile.write_env(os.path.join(os.path.dirname(data_root), ".env"), {
        "LLM_API_KEY": "sk-x", "LLM_MODEL": "m",
        "LLM_BASE_URL": "https://x.com/v1/chat/completions",
    })

    html = client.get("/record/2026-06-25").get_data(as_text=True)

    assert "报告已过期" in html
    assert 'id="btn-report"' in html
    assert "重新生成" in html


def test_trends_payload_and_page_expose_unknown_and_versions(client, data_root):
    from src.scoring import SCORING_RULESET_VERSION
    payload = trends_store.week_payload(
        os.path.join(data_root, "records", "daily"), "2026-06-25")

    assert payload["unknown_count"] == 6
    assert payload["rule_versions"] == ["legacy"]
    assert payload["mixed_rule_versions"] is False
    assert payload["scoring_ruleset_version"] == SCORING_RULESET_VERSION

    html = client.get("/trends?week=2026-06-25").get_data(as_text=True)
    assert "6 项评分未知" in html
    assert "legacy" in html


def test_report_uses_env_limits_and_shared_json_extraction(client, tmp_path, monkeypatch):
    import envfile
    envfile.write_env(str(tmp_path / ".env"), {
        "LLM_MAX_TOKENS": "4321", "LLM_TIMEOUT": "17"})
    seen = {}

    def fake_chat(*args, **kwargs):
        seen.update(kwargs)
        return "<think>推理</think>前置说明\n```json\n" + _contract("# 报告") + "\n```"

    monkeypatch.setattr(llm_client, "chat", fake_chat)
    resp = client.post("/record/2026-06-25/report")
    assert resp.status_code == 200, resp.get_json()
    assert seen["max_tokens"] == 4321
    assert seen["timeout"] == 17


def test_report_invalid_llm_limit_returns_400_without_call(client, tmp_path, data_root,
                                                            monkeypatch):
    import envfile
    envfile.write_env(str(tmp_path / ".env"), {"LLM_MAX_TOKENS": "not-a-number"})
    path = os.path.join(data_root, "records", "daily", "2026-06-25_analysis.json")
    with open(path, "rb") as file:
        before = file.read()
    monkeypatch.setattr(llm_client, "chat",
                        lambda *args, **kwargs: (_ for _ in ()).throw(
                            AssertionError("非法配置不应发起调用")))
    resp = client.post("/record/2026-06-25/report")
    assert resp.status_code == 400
    assert "LLM_MAX_TOKENS" in resp.get_json()["error"]
    with open(path, "rb") as file:
        assert file.read() == before


def test_report_does_not_fallback_to_ignored_external_env(
        tmp_path, data_root, monkeypatch):
    external = tmp_path / "external"
    external.mkdir()
    marker = "DISABLED_EXTERNAL_MARKER"
    (external / "old.md").write_text(
        f"{marker} 舌 食疗 忌口 煎服 方证\n", encoding="utf-8")
    monkeypatch.setenv("TCM_KB_ROOT", str(external))
    monkeypatch.delenv("TCM_KB_ALLOW_EXTERNAL_KB", raising=False)
    monkeypatch.setenv("LLM_API_KEY", "sk-x")
    monkeypatch.setenv("LLM_MODEL", "m")
    monkeypatch.setenv("LLM_BASE_URL", "https://x.com/v1/chat/completions")
    captured = {}

    def fake_chat(user_input, *args, **kwargs):
        captured["input"] = user_input
        return _contract("# ok")

    monkeypatch.setattr(llm_client, "chat", fake_chat)
    app = create_app(env_file=str(tmp_path / ".env"), data_root=data_root)
    app.config["TESTING"] = True
    client = app.test_client()
    client.post("/welcome", headers={"Origin": "http://localhost"})

    response = client.post("/record/2026-06-25/report")

    assert response.status_code == 200, response.get_json()
    with open(os.path.join(data_root, "records", "daily",
                           "2026-06-25_analysis.json"), encoding="utf-8") as file:
        report = json.load(file)["diagnosis"]["report"]
    assert report["kb_status"] == "unconfigured"
    assert all(info["status"] == "unconfigured"
               for info in report["kb_categories"].values())
    assert "kb_refs" not in report
    assert marker not in captured["input"]
    assert captured["input"].count("状态：未配置") == 3
