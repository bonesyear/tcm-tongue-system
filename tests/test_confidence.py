"""Confidence module 测试：覆盖度→等级、安全边界、一致性。"""
import pytest

from src import confidence as C
from src.confidence import ConfidenceLevel, from_coverage, allows_formula, allows_dosage


def test_from_coverage_mapping():
    assert from_coverage(0) is ConfidenceLevel.LOW
    assert from_coverage(1) is ConfidenceLevel.LOW
    assert from_coverage(2) is ConfidenceLevel.MEDIUM
    assert from_coverage(3) is ConfidenceLevel.MEDIUM
    assert from_coverage(4) is ConfidenceLevel.HIGH
    assert from_coverage(5) is ConfidenceLevel.HIGH
    assert from_coverage(6) is ConfidenceLevel.HIGH
    # 超范围封顶
    assert from_coverage(7) is ConfidenceLevel.HIGH


def test_allows_formula_low_false():
    """安全铁律：LOW 置信度不允许给方剂。"""
    assert allows_formula(ConfidenceLevel.LOW) is False
    assert allows_formula("LOW") is False


def test_allows_formula_medium_high_true():
    assert allows_formula(ConfidenceLevel.MEDIUM) is True
    assert allows_formula(ConfidenceLevel.HIGH) is True
    assert allows_formula("HIGH") is True


def test_allows_dosage_only_high():
    assert allows_dosage(ConfidenceLevel.LOW) is False
    assert allows_dosage(ConfidenceLevel.MEDIUM) is False
    assert allows_dosage(ConfidenceLevel.HIGH) is True


def test_is_consistent():
    assert C.is_consistent("HIGH", 6) is True
    assert C.is_consistent("HIGH", 4) is True
    assert C.is_consistent("MEDIUM", 2) is True
    assert C.is_consistent("LOW", 1) is True
    # 不一致
    assert C.is_consistent("HIGH", 1) is False
    assert C.is_consistent("LOW", 6) is False
    # 无法识别
    assert C.is_consistent("UNKNOWN", 6) is False
    assert C.is_consistent(None, 6) is False


def test_parse_level_lenient():
    assert C.parse_level("HIGH") is ConfidenceLevel.HIGH
    assert C.parse_level("high") is ConfidenceLevel.HIGH
    assert C.parse_level("HIGH CONFIDENCE") is ConfidenceLevel.HIGH
    assert C.parse_level(None) is None
    assert C.parse_level("garbage") is None


def test_parse_level_chinese():
    """中文置信度解析（历史 Bug 8：注释声称兼容"高度确信"，实现却解析不了）。"""
    assert C.parse_level("高度确信") is ConfidenceLevel.HIGH
    assert C.parse_level("高度") is ConfidenceLevel.HIGH
    assert C.parse_level("高") is ConfidenceLevel.HIGH
    assert C.parse_level("中度确信") is ConfidenceLevel.MEDIUM
    assert C.parse_level("低度确信") is ConfidenceLevel.LOW
    # 非置信度中文词不应误判
    assert C.parse_level("中医") is None
    assert C.parse_level("高血压") is None


def test_parse_level_word_boundary():
    """英文前缀须有词边界："HIGHEST" 不是 HIGH。"""
    assert C.parse_level("LOWEST") is None
    assert C.parse_level("HIGHEST") is None
    assert C.parse_level("HIGH-CONF") is ConfidenceLevel.HIGH


def test_is_consistent_accepts_chinese():
    assert C.is_consistent("高度确信", 6) is True
    assert C.is_consistent("低度确信", 6) is False


def test_parse_level_chinese_colloquial():
    """对抗验证发现："低置信度" 是 LLM 高频写法，解析不了会绕过安全铁律。"""
    assert C.parse_level("低置信度") is ConfidenceLevel.LOW
    assert C.parse_level("高置信度") is ConfidenceLevel.HIGH
    assert C.parse_level("中置信度") is ConfidenceLevel.MEDIUM
    assert C.parse_level("中等") is ConfidenceLevel.MEDIUM


def test_parse_level_mixed_cjk_boundary():
    """CJK 字符是合法词边界（isalpha() 对 CJK 为 True，不能用它判断）。"""
    assert C.parse_level("HIGH置信度") is ConfidenceLevel.HIGH
    assert C.parse_level("LOW置信度") is ConfidenceLevel.LOW


def test_parse_level_whitespace_returns_none():
    """纯空白必须返回 None，不得抛 IndexError（对抗验证发现）。"""
    assert C.parse_level("   ") is None
    assert C.parse_level("") is None


def test_coerce_whitespace_raises_valueerror_not_indexerror():
    """allows_formula 对无法识别输入抛文档声明的 ValueError，而非 IndexError。"""
    with pytest.raises(ValueError):
        C.allows_formula("   ")


def test_prompt_paragraph_mentions_rule():
    text = C.prompt_paragraph()
    assert "LOW" in text and "MEDIUM" in text and "HIGH" in text
    assert "不给方剂" in text  # 安全铁律
