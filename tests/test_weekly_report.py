"""集成测试：周报生成器在样例记录（形状 B）上产出非全零输出（核心 bug 修复回归）。

fixture 说明见 test_record.py 模块 docstring。
"""
import json
import os
import re

import pytest

import generate_weekly_report as g

RECORD_PATH = os.path.join(
    os.path.dirname(__file__), "fixtures", "2026-06-25_analysis.json"
)


@pytest.fixture
def real_raw():
    with open(RECORD_PATH, encoding="utf-8") as f:
        return json.load(f)


def test_compute_dimension_deviation_non_zero(real_raw):
    """形状 B 记录的维度偏离度不应全零（修复前为全零静默 bug）。"""
    dev = g.compute_dimension_deviation(real_raw)
    assert any(v > 0 for v in dev.values()), f"偏离度不应全零: {dev}"
    # 头面诊面色萎黄应被命中
    assert dev["头面诊"] > 0
    # 舌诊（胖大/齿痕轻度）应 > 0；淡红/润为正常基线 0，不再抬分
    assert dev["舌诊"] > 0


def test_extract_tongue_metrics_non_zero(real_raw):
    metrics = g.extract_tongue_metrics(real_raw)
    assert any(v > 0 for v in metrics.values()), f"舌象指标不应全零: {metrics}"
    # 九项指标齐全（轮次 3 新增「舌苔剥落」轴）
    assert set(metrics.keys()) == {
        "舌质颜色", "舌苔厚度", "舌苔润燥", "齿痕",
        "瘀斑", "舌下络脉", "裂纹", "舌体胖瘦", "舌苔剥落",
    }
    # fixture 舌苔 "花剥" 应命中剥落轴（轮次 3 新增口径）
    assert metrics["舌苔剥落"] == 6.0


def test_weekly_report_data_valid_output(real_raw):
    """周报能产出一次有效输出（非全零）。"""
    data = g.generate_weekly_report_data([real_raw])
    assert data["daily_records_count"] == 1
    assert data["start_date"] == "2026-06-25"
    # 摘要应包含非零的舌诊偏离度数值（fixture：齿痕 4 + 胖大 7 → 均值 5.5）
    assert "5.5" in data["summary"]
    # week_id 为 ISO 周格式（%G-W%V）
    assert re.fullmatch(r"\d{4}-W\d{2}", data["week_id"])
    # confidence 校验断言已写入
    checks = data["confidence_checks"]
    assert len(checks) == 1
    assert checks[0]["consistent"] is True
    assert checks[0]["expected"] == "HIGH"
    # 无违规时摘要不应出现安全警示
    assert "安全边界警示" not in data["summary"]


def test_validator_passes_real_record(real_raw, capsys):
    """validator 对真实记录（形状 B）不应误报全部必填字段缺失。"""
    import input_validator as v
    record, errors, warnings = v.validate_record(RECORD_PATH)
    assert record is not None
    # 不应有"全部必填字段缺失"式的严重错误
    assert errors == [], f"真实记录不应有严重错误: {errors}"
    assert record.get_covered_dimension_count() == 6


def test_low_confidence_formula_flagged():
    """LOW 置信度却给方剂必须被 validator 判为严重错误（退出码 1 强制执行）。"""
    import input_validator as v
    raw = {
        "date": "2026-01-01",
        "confidence": "LOW",
        "observations": {"tongue": {"body": {"color": "淡红"}}},
        "formula": {"name": "不应给出的方"},
        "danger_flags": {"triggered": [], "not_triggered": []},
    }
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump(raw, f, ensure_ascii=False)
        path = f.name
    try:
        _, errors, warnings = v.validate_record(path)
        # 安全边界违反是 error 级（历史 Bug 7：曾只是警告，违规记录照样通过）
        assert any("安全边界" in e or "不应输出方剂" in e for e in errors)
    finally:
        os.remove(path)


def _validate_raw(raw):
    """把 raw dict 写入临时文件并跑 validator，返回 (record, errors, warnings)。"""
    import tempfile
    import input_validator as v
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                     encoding="utf-8") as f:
        json.dump(raw, f, ensure_ascii=False)
        path = f.name
    try:
        return v.validate_record(path)
    finally:
        os.remove(path)


def test_low_confidence_ingredients_only_formula_flagged():
    """不写方名、只带药材+剂量的方剂同样必须被拦截（对抗验证发现）。"""
    raw = {
        "date": "2026-01-01",
        "confidence": "LOW",
        "observations": {"tongue": {"body": {"color": "红"}}},
        "formula": {"ingredients": [{"herb": "党参", "dosage": "15g"},
                                    {"herb": "白术", "dosage": "10g"}]},
        "danger_flags": {"triggered": [], "not_triggered": []},
    }
    _, errors, _ = _validate_raw(raw)
    assert any("安全边界" in e for e in errors)


def test_unreported_confidence_does_not_bypass_safety():
    """省略 confidence 字段（形状 A 常态）不可绕过 LOW 禁方剂铁律（对抗验证发现）。"""
    raw = {
        "date": "2026-01-01",
        "doubao_vision_analysis": {"舌诊": {"舌质颜色": "红"}},
        "deepseek_diagnosis": {"方剂建议": {"主方": "不应给出的方"}},
        "danger_flags": {},
    }
    _, errors, _ = _validate_raw(raw)
    assert any("安全边界" in e for e in errors)


def test_unparseable_confidence_does_not_bypass_safety():
    """自报无法解析的置信度值时按覆盖度推断等级照样执行安全检查。"""
    raw = {
        "date": "2026-01-01",
        "confidence": "说不清",
        "observations": {"tongue": {"body": {"color": "红"}}},
        "formula": {"name": "不应给出的方"},
        "danger_flags": {"triggered": [], "not_triggered": []},
    }
    _, errors, warnings = _validate_raw(raw)
    assert any("安全边界" in e for e in errors)
    assert any("无法识别的置信度" in w for w in warnings)


def test_malformed_record_reports_error_not_traceback():
    """畸形输入必须产出 error 报告，而非未捕获异常（对抗验证发现）。"""
    # observations 为字符串
    _, errors, _ = _validate_raw({
        "date": "2026-01-01", "observations": "坏数据", "danger_flags": {},
    })
    assert any("observations" in e and "应为对象" in e for e in errors)
    # 顶层 JSON 为数组
    record, errors2, _ = _validate_raw([1, 2, 3])
    assert record is None
    assert errors2 and any("无法解析" in e for e in errors2)


def test_danger_flags_type_errors_are_errors():
    """红线状态被类型错误静默"清零"必须报 error（对抗验证发现）。"""
    # 形状 B：triggered 给字符串而非列表
    _, errors, _ = _validate_raw({
        "date": "2026-01-01", "observations": {},
        "danger_flags": {"triggered": "acute_jaundice", "not_triggered": []},
    })
    assert any("triggered" in e and "列表" in e for e in errors)
    # 形状 A：triggered 给真值意图的字符串
    _, errors2, _ = _validate_raw({
        "date": "2026-01-01", "observations": {},
        "danger_flags": {"daiyang": {"triggered": "yes", "finding": "面红如妆"}},
    })
    assert any("布尔" in e for e in errors2)


def test_load_week_records_tolerates_numeric_date(monkeypatch, tmp_path):
    """某条记录 date 为数值时不得让整周周报崩溃（对抗验证发现）。"""
    daily = tmp_path / "daily"
    daily.mkdir()
    (daily / "2026-06-24_analysis.json").write_text(
        json.dumps({"date": 20260624, "observations": {}}), encoding="utf-8")
    (daily / "2026-06-25_analysis.json").write_text(
        json.dumps({"date": "2026-06-25", "observations": {}}), encoding="utf-8")
    monkeypatch.setattr(g, "RECORDS_DIR", str(daily))
    from datetime import datetime
    records = g.load_week_records(datetime(2026, 6, 25))
    assert len(records) == 2  # 混合类型 date 排序不抛 TypeError


def test_weekly_summary_flags_safety_violation():
    """周报摘要必须显式标注 LOW+方剂 的安全边界违反，不能只藏在 stderr。"""
    raw = {
        "date": "2026-01-01",
        "confidence": "LOW",
        "observations": {"tongue": {"body": {"color": "红"}}},
        "formula": {"name": "不应给出的方"},
        "danger_flags": {"triggered": [], "not_triggered": []},
    }
    data = g.generate_weekly_report_data([raw])
    assert any("safety_violation" in c for c in data["confidence_checks"])
    assert "安全边界警示" in data["summary"]


def test_select_daily_file_prefers_canonical_name(monkeypatch, tmp_path, capsys):
    """同日存在 _b 副本时，规范名 {date}_analysis.json 优先（实测 07-15 曾
    被 sorted()[-1] 静默选中 _b 副本而丢弃正档）。"""
    daily = tmp_path / "daily"
    daily.mkdir()
    (daily / "2026-07-15_analysis.json").write_text(
        json.dumps({"date": "2026-07-15", "tag": "canonical"}), encoding="utf-8")
    (daily / "2026-07-15_b_analysis.json").write_text(
        json.dumps({"date": "2026-07-15", "tag": "copy_b"}), encoding="utf-8")
    monkeypatch.setattr(g, "RECORDS_DIR", str(daily))
    chosen = g._select_daily_file("2026-07-15")
    assert chosen.endswith("2026-07-15_analysis.json")
    assert capsys.readouterr().err == ""  # 规范名命中即无歧义，不打 warning


def test_select_daily_file_warns_on_multiple_noncanonical(
        monkeypatch, tmp_path, capsys):
    """无规范名且有多份非规范候选时：打 warning（列出全部候选与选用者），
    取 mtime 最新者。"""
    daily = tmp_path / "daily"
    daily.mkdir()
    older = daily / "2026-07-15_b_analysis.json"
    newer = daily / "2026-07-15_c_analysis.json"
    older.write_text(json.dumps({"date": "2026-07-15"}), encoding="utf-8")
    newer.write_text(json.dumps({"date": "2026-07-15"}), encoding="utf-8")
    os.utime(older, (1000000000, 1000000000))
    os.utime(newer, (1000000100, 1000000100))
    # .bak 备份不参与竞争（选上会读到旧口径数据）
    bak = daily / "2026-07-15_analysis.bak.json"
    bak.write_text(json.dumps({"date": "2026-07-15"}), encoding="utf-8")
    os.utime(bak, (1000000200, 1000000200))  # mtime 最新但被排除
    monkeypatch.setattr(g, "RECORDS_DIR", str(daily))
    chosen = g._select_daily_file("2026-07-15")
    assert chosen.endswith("2026-07-15_c_analysis.json")
    err = capsys.readouterr().err
    assert "2026-07-15_b_analysis.json" in err
    assert "2026-07-15_c_analysis.json" in err
    assert "mtime" in err


def test_select_daily_file_no_match_silent(monkeypatch, tmp_path, capsys):
    """无候选时返回 None 且静默跳过（不报错、不打 warning）。"""
    daily = tmp_path / "daily"
    daily.mkdir()
    (daily / "2026-07-14_analysis.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(g, "RECORDS_DIR", str(daily))
    assert g._select_daily_file("2026-07-15") is None
    assert capsys.readouterr().err == ""


def test_empty_records_report_structure():
    """空记录列表返回完整结构（含 confidence_checks 空列表）。"""
    data = g.generate_weekly_report_data([])
    assert data["daily_records_count"] == 0
    assert data["confidence_checks"] == []
    assert data["dimension_deviation_detail"] == {}


# ---- 多维输出（mean/max/n）与趋势双门槛 ----


def test_compute_dimension_deviation_detail(real_raw):
    """多维输出：每维度携带 mean/max/n，mean 与旧口径 compute_dimension_deviation 一致。"""
    detail = g.compute_dimension_deviation_detail(real_raw)
    dev = g.compute_dimension_deviation(real_raw)
    assert set(detail.keys()) == set(dev.keys())
    for dim_cn, d in detail.items():
        assert set(d.keys()) == {"mean", "max", "n"}
        assert d["mean"] == dev[dim_cn]
    # fixture 舌诊：齿痕 4 + 胖大 7 + 剥落 6 + 点刺 5 → 均值 5.5、最重单项 7、共 4 项异常
    assert detail["舌诊"] == {"mean": 5.5, "max": 7.0, "n": 4}


def test_describe_trend_dual_gate_allows_real_improvement():
    """max 降 ≥0.5 且 n 不增 → 允许报"异常程度减轻"。"""
    text = g.describe_trend("舌诊偏离度", 6.0, 5.0,
                            first_max=7.0, last_max=5.0, first_n=3, last_n=3)
    assert "异常程度减轻" in text
    # n 减少（负荷下降）同样允许
    text2 = g.describe_trend("舌诊偏离度", 6.0, 5.0,
                             first_max=7.0, last_max=5.0, first_n=3, last_n=2)
    assert "异常程度减轻" in text2


def test_describe_trend_dual_gate_blocks_denominator_dilution():
    """均值下降纯属分母变大（max 未降、n 增加）→ 不得报"减轻"（08-28 实测场景）。"""
    text = g.describe_trend("舌诊偏离度", 6.0, 5.3,
                            first_max=7.0, last_max=7.0, first_n=3, last_n=6)
    assert "异常程度减轻" not in text
    assert "暂不判为好转" in text
    assert "最重单项未同步减轻" in text


def test_describe_trend_max_down_but_n_up_is_neutral():
    """max 下降但 n 增加 → 中性描述"最重单项减轻但异常项增多"。"""
    text = g.describe_trend("舌诊偏离度", 6.0, 4.0,
                            first_max=7.0, last_max=6.0, first_n=3, last_n=5)
    assert "异常程度减轻" not in text
    assert "异常项增多（3→5 项）" in text
    assert "暂不判为好转" in text


def test_describe_trend_worsening_ungated():
    """加重方向不设门槛：均值升高即报加重（从严叙述）。"""
    text = g.describe_trend("舌诊偏离度", 5.0, 6.0,
                            first_max=5.0, last_max=4.0, first_n=3, last_n=6)
    assert "异常程度加重" in text


def test_describe_trend_no_valid_observation():
    """n=0 为"无有效观测"，不作趋势判定、不写 0.0 正常。"""
    text = g.describe_trend("舌诊偏离度", 0.0, 0.0,
                            first_max=0.0, last_max=0.0, first_n=0, last_n=0)
    assert "无有效观测" in text
    assert "整体稳定" not in text
    text2 = g.describe_trend("舌诊偏离度", 0.0, 5.3,
                             first_max=0.0, last_max=7.0, first_n=0, last_n=6)
    assert "不作趋势判定" in text2


def test_describe_trend_scalar_call_backward_compatible():
    """不传 max/n 的旧调用方式（逐指标标量）保持原口径。"""
    text = g.describe_trend("齿痕程度", 4.0, 2.0)
    assert "异常程度减轻" in text
    assert g.describe_trend("齿痕程度", 4.0, 4.2) == "齿痕程度整体稳定（4.0 → 4.2）"


def test_weekly_report_detail_keys_additive(real_raw):
    """周报 JSON 纯增量加键：dimension_deviation_detail 含首末 mean/max/n，旧键不动。"""
    data = g.generate_weekly_report_data([real_raw])
    detail = data["dimension_deviation_detail"]
    assert detail["舌诊"]["first"] == {"mean": 5.5, "max": 7.0, "n": 4}
    assert detail["舌诊"]["last"] == {"mean": 5.5, "max": 7.0, "n": 4}
    # 旧键一个不少
    for key in ("week_id", "start_date", "end_date", "daily_records_count",
                "trend_analysis", "weekly_comparison", "summary",
                "next_week_suggestion", "confidence_checks"):
        assert key in data


def test_weekly_summary_shows_mean_max_n(real_raw):
    """摘要舌诊偏离度同时呈现均值/最重单项/异常项数三个数（中文可读）。"""
    data = g.generate_weekly_report_data([real_raw])
    assert "舌诊综合偏离度均值由 5.5 变化至 5.5（最重单项 7 分，共 4 项异常）" \
        in data["summary"]


def test_weekly_summary_marks_no_valid_observation():
    """舌诊 n=0（解析不到观测）的档案：摘要标注"无有效观测"，不写 0.0 假正常。"""
    raw = {"date": "2026-01-01", "observations": {"tongue": {}}}
    data = g.generate_weekly_report_data([raw])
    assert "无有效观测" in data["summary"]
    assert "舌诊综合偏离度均值由 0.0" not in data["summary"]
    assert data["dimension_deviation_detail"]["舌诊"]["last"]["n"] == 0


# ---- 轮次 5：逐指标观测标注 / 全 n=0 时 summary 与建议联动 / 雷达图无观测 ----


def test_extract_tongue_observation_flags(real_raw):
    """观测 flag 判据 = 观测文本非空（score 无法区分"正常 0"与"无数据"）。"""
    flags = g.extract_tongue_observation_flags(real_raw)
    assert set(flags.keys()) == set(g.TONGUE_RADAR_METRIC_KEYS.keys())
    # fixture 2026-06-25（形状 B）舌诊 18 项指标齐全 → 9 个雷达轴全有观测
    assert all(flags.values())
    empty = g.extract_tongue_observation_flags(
        {"date": "2026-01-01", "observations": {"tongue": {}}})
    assert not any(empty.values())


def test_metric_trend_group_short_circuit_when_unobserved():
    """组内全部轴两端均无观测 → 整组只输出一句，不刷多条长文案；
    且不得再出现"整体稳定（0.0 → 0.0）"式的假正常。"""
    raw = {"date": "2026-01-01", "observations": {"tongue": {}}}
    data = g.generate_weekly_report_data([raw])
    ta = data["trend_analysis"]
    assert ta["舌质变化"] == "本周无有效观测（舌质颜色未解析到）"
    assert ta["舌苔变化"] == "本周无有效观测（舌苔厚度/舌苔润燥/舌苔剥落均未解析到）"
    assert ta["舌形变化"] == "本周无有效观测（齿痕/舌体胖瘦/裂纹均未解析到）"
    assert ta["舌下络脉变化"] == "本周无有效观测（舌下络脉未解析到）"
    for key in ("舌质变化", "舌苔变化", "舌形变化", "舌下络脉变化"):
        assert "整体稳定" not in ta[key]


def test_metric_trend_observed_normal_zero_verbatim_compatible():
    """有观测但正常 0 分（淡红）时必须与旧标量调用逐字一致——
    "整体稳定（0.0 → 0.0）"只在确有观测时出现。"""
    raw = {"date": "2026-01-01",
           "observations": {"tongue": {"body": {"color": "淡红"}}}}
    data = g.generate_weekly_report_data([raw])
    assert data["trend_analysis"]["舌质变化"] == "舌质颜色偏离度整体稳定（0.0 → 0.0）"
    # 同档案未观测的分组仍走分组短路
    assert data["trend_analysis"]["舌苔变化"] == \
        "本周无有效观测（舌苔厚度/舌苔润燥/舌苔剥落均未解析到）"


def test_metric_trend_one_end_observed():
    """仅一端有观测 → 走 describe_trend 既有"仅一端有有效观测"分支。"""
    first = {"date": "2026-01-01", "observations": {"tongue": {}}}
    last = {"date": "2026-01-02",
            "observations": {"tongue": {"body": {"color": "淡红"}}}}
    data = g.generate_weekly_report_data([first, last])
    assert "仅一端有有效观测" in data["trend_analysis"]["舌质变化"]


def test_summary_no_ranking_when_all_dims_unobserved():
    """全维度周末 n=0：不作偏离度排名，且建议不得把"无数据"叙述为
    "偏离度总体较低"（实测 W32 曾输出自相矛盾的 summary 与错误建议）。"""
    raw = {"date": "2026-01-01", "observations": {"tongue": {}}}
    data = g.generate_weekly_report_data([raw])
    assert "本周各维度均无有效观测，不作偏离度排名" in data["summary"]
    assert "当前偏离度最高的维度" not in data["summary"]
    assert "本周未解析到有效观测" in data["next_week_suggestion"]
    assert "偏离度总体较低" not in data["next_week_suggestion"]


def test_summary_short_circuit_sentence_has_group_prefix():
    """无观测周的 summary：组级短路句须带"舌质变化："前缀，不出现孤立句
    （实测 W32 summary 曾出现无前缀的"本周无有效观测（舌质颜色未解析到）"）。
    trend_analysis 字典里的原始短句保持不变，前缀只在 summary 拼接处补。"""
    raw = {"date": "2026-01-01", "observations": {"tongue": {}}}
    data = g.generate_weekly_report_data([raw])
    assert "舌质变化：本周无有效观测（舌质颜色未解析到）" in data["summary"]
    assert "。本周无有效观测（舌质颜色" not in data["summary"]
    assert data["trend_analysis"]["舌质变化"] == "本周无有效观测（舌质颜色未解析到）"


def test_summary_observed_tongue_color_no_prefix():
    """正常观测路径逐字不变：summary 中舌质趋势句原样保留，
    不得加"舌质变化："前缀。"""
    raw = {"date": "2026-01-01",
           "observations": {"tongue": {"body": {"color": "淡红"}}}}
    data = g.generate_weekly_report_data([raw])
    assert "舌质颜色偏离度整体稳定（0.0 → 0.0）" in data["summary"]
    assert "舌质变化：" not in data["summary"]


def test_radar_chart_skips_unobserved_day(monkeypatch, tmp_path, capsys):
    """全部轴无观测的日期不绘制多边形（全零多边形视觉上=一切正常），
    并有显式提示；不传 flags 时保持旧行为（向后兼容）。"""
    pytest.importorskip("matplotlib")
    monkeypatch.setattr(g, "CHARTS_DIR", str(tmp_path))
    dates = ["2026-01-01", "2026-01-02"]
    metrics = [{"舌质颜色": 7.0}, {}]
    flags = [
        {k: True for k in g.TONGUE_RADAR_METRIC_KEYS},
        {k: False for k in g.TONGUE_RADAR_METRIC_KEYS},
    ]
    path = g.generate_radar_chart(metrics, dates, obs_flags_list=flags)
    assert path is not None and os.path.exists(path)
    assert "2026-01-02 全部轴无有效观测" in capsys.readouterr().err
    # 不传 flags：全部绘制，不抛异常
    assert g.generate_radar_chart(metrics, dates) is not None
