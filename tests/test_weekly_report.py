"""集成测试：周报生成器在样例记录（形状 B）上产出非全零输出（核心 bug 修复回归）。

fixture 说明见 test_record.py 模块 docstring。
"""
import json
import os
import re

import pytest

import generate_weekly_report as g
from src.record import DailyRecord
from src.dimensions import VisionDimension

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
    # 八项指标齐全
    assert set(metrics.keys()) == {
        "舌质颜色", "舌苔厚度", "舌苔润燥", "齿痕",
        "瘀斑", "舌下络脉", "裂纹", "舌体胖瘦",
    }


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


def test_empty_records_report_structure():
    """空记录列表返回完整结构（含 confidence_checks 空列表）。"""
    data = g.generate_weekly_report_data([])
    assert data["daily_records_count"] == 0
    assert data["confidence_checks"] == []
