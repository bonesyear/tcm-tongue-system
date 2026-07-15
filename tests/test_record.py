"""Record module 测试。

用脱敏样例记录 tests/fixtures/2026-06-25_analysis.json（形状 B，字段结构
与真实 LLM 产出一致）作为 fixture，断言新架构能正确解析、按维度取观测、
取方剂/辨证/红线，且不丢失信息。

fixture 入库原因：原先依赖 records/daily/ 下的真实记录，而该目录被
.gitignore 排除且含个人健康数据 → 新环境克隆后测试必挂（历史 Bug 1）。
"""
import json
import os

import pytest

from src.record import DailyRecord
from src.dimensions import VisionDimension, DIMENSIONS

RECORD_PATH = os.path.join(
    os.path.dirname(__file__), "fixtures", "2026-06-25_analysis.json"
)


@pytest.fixture
def real_record():
    with open(RECORD_PATH, encoding="utf-8") as f:
        return DailyRecord(json.load(f))


def test_parses_real_record_as_shape_b(real_record):
    assert real_record.shape == "B"
    assert real_record.date == "2026-06-25"


def test_get_observation_tongue_has_content(real_record):
    obs = real_record.get_observation(VisionDimension.TONGUE)
    # 返回规范化指标字典，舌诊应有多项非空观测
    assert isinstance(obs, dict)
    non_empty = {k: v for k, v in obs.items() if v}
    assert len(non_empty) > 0, "舌诊观测不应全空"
    # 真实记录舌质颜色为「淡红为底，花剥区偏红」
    assert "淡红" in obs["body_color"]


def test_get_observation_text_non_empty(real_record):
    text = real_record.get_observation_text(VisionDimension.HEAD_FACE)
    assert "萎黄" in text  # 真实记录面色萎黄


def test_get_formula_non_empty(real_record):
    formula = real_record.get_formula()
    assert formula, "方剂不应为空"
    assert formula.get("name") == "健脾清胃凉血养阴汤（自拟）"
    assert formula.get("total_herbs") == 12
    assert len(formula.get("ingredients", [])) == 12


def test_get_pattern_differentiation(real_record):
    pd = real_record.get_pattern_differentiation()
    assert pd, "辨证结果不应为空"
    # 真实记录含核心病机
    assert "core_pathomechanism" in pd or "核心病机" in pd


def test_get_danger_flags(real_record):
    df = real_record.get_danger_flags()
    assert isinstance(df, dict)
    # 真实记录无触发红线
    assert real_record.get_triggered_danger_flags() == []


def test_dimension_coverage_six(real_record):
    coverage = real_record.get_dimension_coverage()
    assert all(coverage.values()), "真实记录应六维全覆盖"
    assert real_record.get_covered_dimension_count() == 6


def test_inquiry_coverage(real_record):
    asked, total = real_record.get_inquiry_coverage()
    assert asked == 15 and total == 15


def test_confidence_claimed(real_record):
    assert real_record.get_confidence() == "HIGH"


def test_all_dimensions_return_stable_structure(real_record):
    """六个维度都应返回指标字典（即使某指标为空也以 '' 占位）。"""
    for dim in DIMENSIONS:
        obs = real_record.get_observation(dim)
        assert isinstance(obs, dict)
        assert len(obs) > 0


def test_shape_a_template_compatibility():
    """形状 A（模板格式，doubao_vision_analysis 中文键）也能被解析。"""
    shape_a = {
        "date": "2026-01-01",
        "doubao_vision_analysis": {
            "舌诊": {"舌质颜色": "淡红", "舌苔厚薄": "薄白", "齿痕": "无",
                     "舌体动态": "伸舌自如"},
            "头面诊": {"面域": {"面色": "萎黄"}, "鼻域": {"鼻衄": "无"}},
        },
    }
    rec = DailyRecord(shape_a)
    assert rec.shape == "A"
    tongue = rec.get_observation(VisionDimension.TONGUE)
    assert tongue["body_color"] == "淡红"
    assert tongue["coating_thickness"] == "薄白"
    # 模板字段"舌体动态"不再被静默丢弃（历史 Bug 11）
    assert tongue["body_dynamics"] == "伸舌自如"
    head = rec.get_observation(VisionDimension.HEAD_FACE)
    assert head["face_color"] == "萎黄"
    assert head["nose_bleeding"] == "无"


def test_unknown_dimension_raises():
    """未知维度名必须报错，不得静默回落到舌诊（历史 Bug 9）。"""
    rec = DailyRecord({"date": "2026-01-01", "observations": {}})
    with pytest.raises(ValueError):
        rec.get_observation("不存在的维度")


def test_inquiry_coverage_tolerates_dirty_values():
    """inquiry_coverage 的 covered/total 为脏数据时按 0 处理，不抛异常。"""
    rec = DailyRecord({
        "date": "2026-01-01",
        "observations": {},
        "inquiry_coverage": {"covered": "N/A", "total": None},
    })
    assert rec.get_inquiry_coverage() == (0, 0)


def test_malformed_containers_do_not_crash():
    """容器字段类型错误（字符串等）时各访问器按空返回，不抛 AttributeError
    （对抗验证发现：原 'str' object has no attribute 'get' 裸崩溃）。"""
    rec = DailyRecord({
        "date": "2026-01-01",
        "observations": "坏数据",
        "inquiry_coverage": "15/15",
        "deepseek_diagnosis": "整段文本",
    })
    assert rec.get_covered_dimension_count() == 0
    assert rec.get_inquiry_coverage() == (0, 0)
    assert rec.get_formula() == {}
    assert rec.get_pattern_differentiation() == {}


def test_has_formula_content():
    """安全边界的方剂判定：无方名但携带药材+剂量同样算方剂（对抗验证发现）。"""
    from src.record import has_formula_content
    assert has_formula_content(None) is False
    assert has_formula_content({}) is False
    assert has_formula_content({"name": "苓桂术甘汤"}) is True
    assert has_formula_content({"主方": "苓桂术甘汤"}) is True
    assert has_formula_content(
        {"ingredients": [{"herb": "党参", "dosage": "15g"}]}) is True
    # 结构异常（整段文本）不放行
    assert has_formula_content("苓桂术甘汤：茯苓15g 桂枝10g") is True
    assert has_formula_content("   ") is False


def test_no_information_loss_against_raw(real_record):
    """新架构取出的观测文本应是原始记录的子集，不丢失关键信息。"""
    raw = real_record.raw
    # 舌下络脉颜色（真实记录判读为正常）
    tongue = real_record.get_observation(VisionDimension.TONGUE)
    assert "隐约浅淡蓝紫色" in tongue["sublingual_color"]
    # 耳色红赤
    ear = real_record.get_observation(VisionDimension.EAR)
    assert ear["color"] == raw["observations"]["ear"]["color"]
