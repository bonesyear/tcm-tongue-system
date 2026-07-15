"""grep_search 单元测试：纯 grep 引擎。用 tmp_path 造临时 KB 做精确断言，
加一条真实 KB 冒烟测试验证集成。"""

import os
import re

import pytest

from src.retrieval.grep_search import (
    search,
    search_and,
    count_hits,
    list_kb_files,
)


# ============================================================
# 临时 KB fixture
# ============================================================
@pytest.fixture
def tmp_kb(tmp_path):
    """造一个已知内容与行号的临时 KB。"""
    content = (
        "# 测试知识库\n"            # L1 标题
        "\n"                         # L2
        "太阴病属寒属虚。\n"          # L3 ← 含"太阴"
        "下利便溏者属太阴。\n"        # L4 ← 含"下利""便溏""太阴"
        "腹满心下痞为常见症。\n"      # L5 ← 含"腹满""心下痞"
        "\n"                         # L6
        "阳明病属里热。\n"            # L7 ← 含"阳明"
        "便硬便燥者属阳明。\n"        # L8 ← 含"便硬""便燥""阳明"
    )
    kb = tmp_path / "kb"
    kb.mkdir()
    (kb / "test.md").write_text(content, encoding="utf-8")
    return str(kb)


# ============================================================
# search
# ============================================================
class TestSearch:
    def test_basic_match(self, tmp_kb):
        r = search("太阴", kb_root=tmp_kb)
        assert len(r) == 2  # L3, L4
        assert {h["line"] for h in r} == {3, 4}

    def test_result_shape(self, tmp_kb):
        r = search("太阴", kb_root=tmp_kb)
        h = r[0]
        assert set(h.keys()) == {"file", "line", "content", "context"}
        assert h["file"] == "test.md"
        assert h["content"] == "太阴病属寒属虚。"
        assert h["line"] == 3

    def test_context_window(self, tmp_kb):
        r = search("腹满", kb_root=tmp_kb, context_lines=3)
        assert len(r) == 1
        h = r[0]
        assert h["line"] == 5
        # 前 3 + 匹配行 + 后 3 = 7（L2..L8）
        assert len(h["context"]) == 7
        assert h["context"][3] == h["content"]  # 中间元素是匹配行

    def test_context_at_file_start(self, tmp_kb):
        """首行命中：context 前面不足 3 行，自然截断。"""
        r = search("测试知识库", kb_root=tmp_kb, context_lines=3)
        assert len(r) == 1
        h = r[0]
        assert h["line"] == 1
        # L1 在最前，context 只能从 L1 起：最多 4 行（L1-L4）
        assert len(h["context"]) <= 4
        assert h["context"][0] == h["content"]

    def test_context_at_file_end(self, tmp_kb):
        r = search("便燥", kb_root=tmp_kb, context_lines=3)
        assert len(r) == 1
        h = r[0]
        assert h["line"] == 8  # 最后一行
        # 后面不足 3 行：context = L5..L8（4 行）
        assert len(h["context"]) <= 4

    def test_or_pattern(self, tmp_kb):
        r = search("下利|便硬", kb_root=tmp_kb)
        assert len(r) == 2  # L4 下利, L8 便硬
        assert {h["line"] for h in r} == {4, 8}

    def test_dedup_one_line_multiple_terms(self, tmp_kb):
        """一行同时命中多个 OR 术语 → 仍算 1 条。"""
        r = search("下利|便溏", kb_root=tmp_kb)
        # L4 同时含"下利"和"便溏"，应只返回 1 条
        assert len(r) == 1
        assert r[0]["line"] == 4

    def test_no_match_returns_empty(self, tmp_kb):
        r = search("不存在的术语XYZ", kb_root=tmp_kb)
        assert r == []

    def test_empty_query_returns_empty(self, tmp_kb):
        assert search("", kb_root=tmp_kb) == []
        assert search("   ", kb_root=tmp_kb) == []

    def test_results_sorted_by_file_then_line(self, tmp_kb):
        r = search("阳明", kb_root=tmp_kb)
        assert [h["line"] for h in r] == sorted(h["line"] for h in r)

    def test_invalid_regex_raises(self, tmp_kb):
        with pytest.raises(ValueError):
            search("[未闭合", kb_root=tmp_kb)

    def test_case_insensitive(self, tmp_path):
        kb = tmp_path / "kb"
        kb.mkdir()
        (kb / "a.md").write_text("Hello World\nhello\n", encoding="utf-8")
        r = search("hello", kb_root=str(kb), case_sensitive=True)
        assert len(r) == 1  # 只匹配小写
        r2 = search("hello", kb_root=str(kb), case_sensitive=False)
        assert len(r2) == 2  # 大小写都匹配


# ============================================================
# search_and
# ============================================================
class TestSearchAnd:
    def test_returns_only_files_with_all_terms(self, tmp_kb):
        # "太阴" 和 "下利" 同时出现在 test.md（L3 有太阴，L4 有下利+太阴）
        r = search_and(["太阴", "下利"], kb_root=tmp_kb)
        assert len(r) > 0
        files = {h["file"] for h in r}
        assert files == {"test.md"}
        # 每条带 term 字段
        terms_in_results = {h["term"] for h in r}
        assert terms_in_results == {"太阴", "下利"}

    def test_excludes_file_missing_any_term(self, tmp_kb):
        # "太阴" 在 test.md，"不存在XYZ" 不在 → 整文件不返回
        r = search_and(["太阴", "不存在XYZ"], kb_root=tmp_kb)
        assert r == []

    def test_empty_terms_returns_empty(self, tmp_kb):
        assert search_and([], kb_root=tmp_kb) == []
        assert search_and(["", "  "], kb_root=tmp_kb) == []


# ============================================================
# count_hits
# ============================================================
class TestCountHits:
    def test_count_matches_search_length(self, tmp_kb):
        assert count_hits("太阴", kb_root=tmp_kb) == len(search("太阴", kb_root=tmp_kb))
        assert count_hits("太阴", kb_root=tmp_kb) == 2

    def test_count_empty(self, tmp_kb):
        assert count_hits("", kb_root=tmp_kb) == 0


# ============================================================
# list_kb_files
# ============================================================
class TestListKbFiles:
    def test_excludes_readme(self, tmp_path):
        kb = tmp_path / "kb"
        kb.mkdir()
        (kb / "a.md").write_text("x", encoding="utf-8")
        (kb / "README.md").write_text("x", encoding="utf-8")
        files = list_kb_files(str(kb))
        names = [os.path.basename(f) for f in files]
        assert "a.md" in names
        assert "README.md" not in names

    def test_recursive(self, tmp_path):
        kb = tmp_path / "kb"
        sub = kb / "sub"
        sub.mkdir(parents=True)
        (kb / "a.md").write_text("x", encoding="utf-8")
        (sub / "b.md").write_text("x", encoding="utf-8")
        assert len(list_kb_files(str(kb))) == 2

    def test_nonexistent_dir_returns_empty(self):
        """KB 目录不存在 → glob 返回空，不抛异常。"""
        assert list_kb_files("/no/such/kb/dir") == []

    def test_empty_dir_returns_empty(self, tmp_path):
        kb = tmp_path / "kb"
        kb.mkdir()
        assert list_kb_files(str(kb)) == []


# ============================================================
# 边界情况
# ============================================================
class TestEdgeCases:
    def test_single_char_query(self, tmp_kb):
        # 单字符也是合法正则模式，正常子串匹配（L3、L4 含"太"）
        r = search("太", kb_root=tmp_kb)
        assert len(r) == 2
        assert {h["line"] for h in r} == {3, 4}

    def test_search_nonexistent_kb_returns_empty(self):
        assert search("anything", kb_root="/no/such/kb") == []

    def test_search_empty_kb_dir(self, tmp_path):
        kb = tmp_path / "kb"
        kb.mkdir()
        assert search("anything", kb_root=str(kb)) == []


# ============================================================
# 真实 KB 冒烟测试
# ============================================================
class TestRealKbSmoke:
    """对真实 knowledge_base/ 的集成冒烟测试（不耦合精确行号）。"""

    def test_linggui_formula_hits_real_kb(self):
        # 苓桂术甘汤 实测出现在 constitution-types / diet-therapy / diagnostic-framework
        r = search("苓桂术甘汤")
        assert len(r) >= 3
        files = {h["file"] for h in r}
        assert "diagnostics/constitution-types.md" in files
        assert len(files) >= 2  # 跨多个文件

    def test_xiali_hits_multiple_files(self):
        r = search("下利")
        assert len(r) >= 5  # 实测 10
        # 跨多个文件
        assert len({h["file"] for h in r}) >= 2

    def test_real_kb_files_listed(self):
        files = list_kb_files()
        names = [os.path.basename(f) for f in files]
        assert "diagnostic-framework.md" in names
        assert "formula-system.md" in names
        assert "README.md" not in names  # 默认排除
