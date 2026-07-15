"""synonym_loader 单元测试：别名词典加载与查询展开。"""

import re

import pytest

from src.retrieval.synonym_loader import (
    expand,
    expand_many,
    load_map,
    _parse_simple_yaml,
    DEFAULT_MAP_PATH,
)


# ============================================================
# load_map
# ============================================================
class TestLoadMap:
    def test_loads_real_map(self):
        m = load_map()
        assert isinstance(m, dict)
        assert len(m) > 10  # 实际 72 个键

    def test_known_key_has_verified_targets(self):
        m = load_map()
        # 便软 → 必含经 grep 验证出现在 KB 的"下利"
        assert "下利" in m["便软"]
        # 怕冷 → 含"恶寒"
        assert "恶寒" in m["怕冷"]

    def test_hand_rolled_parser_parity_with_pyyaml(self):
        """手写回退解析器与 PyYAML 结果一致（保证未装 PyYAML 时行为相同）。"""
        try:
            import yaml  # noqa: F401
        except ImportError:
            # 没装 PyYAML 时，load_map 本就走手写路径，无需对比
            return
        with open(DEFAULT_MAP_PATH, encoding="utf-8") as f:
            text = f.read()
        assert load_map() == _parse_simple_yaml(text)

    def test_hand_rolled_parser_skips_comments_and_blanks(self):
        text = (
            "# 注释\n"
            "\n"
            "便软:\n"
            "  - 下利\n"
            "  # 这条不算\n"
            "  - 便溏\n"
            "怕冷:\n"
            "  - 恶寒\n"
        )
        m = _parse_simple_yaml(text)
        assert m == {"便软": ["下利", "便溏"], "怕冷": ["恶寒"]}

    def test_hand_rolled_parser_rejects_flow_style(self):
        """手写解析器不认 flow 风格——保证格式约束被遵守。"""
        text = "便软: [下利, 便溏]\n"
        try:
            _parse_simple_yaml(text)
            assert False, "应抛 ValueError"
        except ValueError:
            pass

    def test_parser_handles_key_trailing_comment(self):
        """键行尾随注释：与 PyYAML 一致（此前手写解析器会抛错）。"""
        m = _parse_simple_yaml("便软: # note\n  - 下利\n")
        assert m == {"便软": ["下利"]}

    def test_parser_handles_key_trailing_whitespace(self):
        """键行尾随空白：与 PyYAML 一致（此前手写解析器会抛错）。"""
        m = _parse_simple_yaml("便软:   \n  - 下利\n")
        assert m == {"便软": ["下利"]}

    def test_parser_handles_item_inline_comment(self):
        m = _parse_simple_yaml("便软:\n  - 下利 # 说明\n  - 便溏\n")
        assert m == {"便软": ["下利", "便溏"]}

    def test_parser_handles_pipe_and_colon_in_items(self):
        """术语含竖线/冒号（无空格）应原样保留。"""
        m = _parse_simple_yaml("方剂:\n  - 苓桂|五苓\n  - 苓桂:甘\n")
        assert m == {"方剂": ["苓桂|五苓", "苓桂:甘"]}

    def test_parser_parity_with_pyyaml_edge_cases(self):
        """手写解析器在多种边界格式下与 PyYAML（经 load_map 规范化）结果一致。"""
        try:
            import yaml  # noqa: F401
        except ImportError:
            return
        import tempfile, os
        cases = [
            "便软: # note\n  - 下利\n",
            "便软: \n  - 下利\n",
            "便软:\n  - 下利 # c\n  - 便溏\n",
            "方剂:\n  - 苓桂|五苓\n",
            "空键:\n下个:\n  - x\n",
            "# 头注释\n\n便软: # c\n  - 下利\n怕冷:\n  - 恶寒\n",
        ]
        for text in cases:
            with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False,
                                             encoding="utf-8") as f:
                f.write(text)
                path = f.name
            try:
                assert load_map(path) == _parse_simple_yaml(text), text
            finally:
                os.unlink(path)

    def test_load_map_missing_file_raises(self):
        """别名词典文件缺失 → fail-fast（FileNotFoundError），不静默返回空。"""
        with pytest.raises(FileNotFoundError):
            load_map("/no/such/synonym_map.yaml")


# ============================================================
# expand
# ============================================================
class TestExpand:
    def test_expand_known_key(self):
        r = expand("便软")
        assert r.query == "便软"
        # 原词 + 同义词都在 terms
        assert "便软" in r.terms
        assert "下利" in r.terms
        # synonyms_used 不含原词
        assert "便软" not in r.synonyms_used
        assert "下利" in r.synonyms_used

    def test_expand_pattern_is_escaped_or(self):
        r = expand("便软")
        # pattern 是合法正则
        assert re.compile(r.pattern)
        # 每个术语都被 re.escape（此处术语无元字符，但应能逐字命中）
        for t in r.terms:
            assert re.escape(t) in r.pattern

    def test_expand_non_key(self):
        r = expand("太阴水饮")  # 不是别名词典的键
        assert r.synonyms_used == []
        assert r.terms == ["太阴水饮"]
        assert r.pattern == re.escape("太阴水饮")

    def test_expand_empty_query(self):
        r = expand("")
        assert r.pattern == ""
        assert r.terms == []
        assert r.synonyms_used == []

    def test_expand_dedups_query_in_synonyms(self):
        """若别名词典把原词也列为同义词，不应重复。"""
        syn_map = {"怕冷": ["恶寒", "怕冷", "恶寒"]}
        r = expand("怕冷", syn_map=syn_map)
        assert r.terms.count("怕冷") == 1
        assert r.terms.count("恶寒") == 1
        assert "怕冷" not in r.synonyms_used  # 原词不计入 synonyms_used

    def test_expand_uses_injected_map(self):
        syn_map = {"甲": ["乙", "丙"]}
        r = expand("甲", syn_map=syn_map)
        assert r.terms == ["甲", "乙", "丙"]
        assert r.synonyms_used == ["乙", "丙"]


# ============================================================
# expand_many
# ============================================================
class TestExpandMany:
    def test_merges_multiple_queries(self):
        syn_map = {"便软": ["下利"], "怕冷": ["恶寒"]}
        r = expand_many(["便软", "怕冷"], syn_map=syn_map)
        assert "便软" in r.terms and "下利" in r.terms
        assert "怕冷" in r.terms and "恶寒" in r.terms
        # 去重
        assert len(r.terms) == len(set(r.terms))

    def test_empty_list(self):
        r = expand_many([], syn_map={})
        assert r.pattern == ""
        assert r.terms == []
