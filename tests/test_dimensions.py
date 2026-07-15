"""Dimension module 测试：六维规范 + 中英双向映射。"""
from src.dimensions import (
    VisionDimension,
    DIMENSIONS,
    chinese_to_english,
    english_to_chinese,
    from_chinese,
    from_english,
    all_chinese_names,
    all_english_names,
)


def test_six_dimensions():
    assert len(DIMENSIONS) == 6
    names = [d.english_name for d in DIMENSIONS]
    assert names == ["tongue", "head_face", "eye", "ear", "hand", "skin"]


def test_each_dimension_has_metadata():
    for d in DIMENSIONS:
        assert d.chinese_name, f"{d} 缺中文名"
        assert d.english_name, f"{d} 缺英文名"
        assert isinstance(d.subdomains, list) and len(d.subdomains) > 0, f"{d} 缺子域"


def test_tongue_subdomains():
    tongue = VisionDimension.TONGUE
    assert tongue.chinese_name == "舌诊"
    assert "舌质" in tongue.subdomains
    assert "舌苔" in tongue.subdomains
    assert "舌下络脉" in tongue.subdomains


def test_bidirectional_mapping():
    pairs = [
        ("舌诊", "tongue"),
        ("头面诊", "head_face"),
        ("目诊", "eye"),
        ("耳诊", "ear"),
        ("手诊", "hand"),
        ("皮肤诊", "skin"),
    ]
    for ch, en in pairs:
        assert chinese_to_english(ch) == en
        assert english_to_chinese(en) == ch
        assert from_chinese(ch) is from_english(en)


def test_unknown_name_returns_none():
    assert from_chinese("不存在") is None
    assert from_english("xxx") is None
    assert chinese_to_english("xxx") is None
    assert english_to_chinese("xxx") is None


def test_is_covered_count_rule():
    assert VisionDimension.TONGUE.is_covered({"body_color": "淡红"}) is True
    assert VisionDimension.TONGUE.is_covered({"body_color": ""}) is False
    assert VisionDimension.TONGUE.is_covered(None) is False
    assert VisionDimension.TONGUE.is_covered("有内容") is True
    assert VisionDimension.TONGUE.is_covered("   ") is False


def test_name_lists():
    assert all_chinese_names() == ["舌诊", "头面诊", "目诊", "耳诊", "手诊", "皮肤诊"]
    assert all_english_names() == ["tongue", "head_face", "eye", "ear", "hand", "skin"]
