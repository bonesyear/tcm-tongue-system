"""rag_search 单元测试：chunk 切分、标题上下文、TF-IDF 兜底召回。

TF-IDF 后端自 v1.3.3 起为纯 Python 倒排索引实现，零外部依赖，
全部测试无需 numpy。补齐标题上下文保留与 heading-only 召回。"""

import pytest

from src.retrieval.rag_search import (
    build_chunks,
    RagSearch,
    Chunk,
    _chunk_file,
    _doc_text,
    tokenize,
)


# ============================================================
# chunk 切分（纯函数，不依赖 numpy）
# ============================================================
class TestChunkFile:
    def test_title_attached_to_following_paragraph(self):
        lines = ["# 标题A", "内容一", "", "内容二"]
        chunks = _chunk_file(lines, "f.md")
        # 两个段落 chunk，都应带标题A
        assert len(chunks) == 2
        assert all(c.title == "标题A" for c in chunks)
        assert chunks[0].text == "内容一"
        assert chunks[1].text == "内容二"

    def test_title_propagates_across_blank_lines(self):
        # 标题之后的多个段落（空行分隔）都继承同一标题
        lines = ["## 章二", "段一", "", "段二", "", "段三"]
        chunks = _chunk_file(lines, "f.md")
        assert len(chunks) == 3
        assert {c.title for c in chunks} == {"章二"}

    def test_new_heading_updates_title(self):
        lines = ["# A", "a内容", "# B", "b内容"]
        chunks = _chunk_file(lines, "f.md")
        assert len(chunks) == 2
        assert chunks[0].title == "A" and chunks[0].text == "a内容"
        assert chunks[1].title == "B" and chunks[1].text == "b内容"

    def test_content_before_any_heading_has_empty_title(self):
        lines = ["无标题内容", "# 标题", "有标题内容"]
        chunks = _chunk_file(lines, "f.md")
        assert len(chunks) == 2
        assert chunks[0].title == ""           # 标题前的段落无标题
        assert chunks[1].title == "标题"

    def test_line_numbers_are_1_based_and_correct(self):
        lines = ["# H", "line2", "", "line4"]
        chunks = _chunk_file(lines, "f.md")
        # chunk1: line2 (1-based L2)；chunk2: line4 (L4)
        assert chunks[0].start_line == 2 and chunks[0].end_line == 2
        assert chunks[1].start_line == 4 and chunks[1].end_line == 4

    def test_long_paragraph_split_by_line(self):
        # 单段超 _CHUNK_MAX_CHARS(500) → 按行切分，行号连续
        long_line = "字" * 300
        lines = ["# H", long_line, long_line, long_line]  # 3×300 = 900 > 500
        chunks = _chunk_file(lines, "f.md")
        assert len(chunks) >= 2
        # 切分后行号连续覆盖 L2-L4
        all_lines = [c.start_line for c in chunks]
        assert min(all_lines) == 2
        # 每个 sub-chunk 不超阈值（单行 300 ≤ 500）
        assert all(len(c.text) <= 500 for c in chunks)

    def test_heading_line_not_in_chunk_text(self):
        # 标题行本身不入正文 text（作为 title 元数据单独存）
        lines = ["# 五苓散", "正文"]
        chunks = _chunk_file(lines, "f.md")
        assert len(chunks) == 1
        assert "五苓散" not in chunks[0].text
        assert chunks[0].title == "五苓散"


class TestDocText:
    def test_prepends_title(self):
        c = Chunk("f.md", 1, 1, "标题", "正文")
        assert _doc_text(c) == "标题\n正文"

    def test_no_title_returns_text(self):
        c = Chunk("f.md", 1, 1, "", "正文")
        assert _doc_text(c) == "正文"


class TestTokenize:
    def test_cjk_bigram_and_unigram(self):
        toks = tokenize("太阴水饮")
        # unigram: 太,阴,水,饮；bigram: 太阴,阴水,水饮
        assert "太" in toks and "太阴" in toks
        assert "水饮" in toks and "饮" in toks

    def test_ascii_lowercased(self):
        toks = tokenize("Hello World")
        assert "hello" in toks and "world" in toks

    def test_empty(self):
        assert tokenize("") == []


# ============================================================
# build_chunks 集成
# ============================================================
class TestBuildChunks:
    def test_excludes_readme(self, tmp_path):
        kb = tmp_path / "kb"
        kb.mkdir()
        (kb / "a.md").write_text("# T\n正文\n", encoding="utf-8")
        (kb / "README.md").write_text("# R\n正文\n", encoding="utf-8")
        chunks = build_chunks(str(kb))
        assert all(c.file != "README.md" for c in chunks)

    def test_nonexistent_kb_returns_empty(self):
        assert build_chunks("/no/such/kb") == []


# ============================================================
# TF-IDF 兜底召回（纯 Python 倒排索引，零依赖）
# ============================================================
@pytest.fixture
def rag_on_tmp_kb(tmp_path):
    kb = tmp_path / "kb"
    kb.mkdir()
    (kb / "a.md").write_text(
        "# 六要素\n"            # 标题：含"六要素"
        "这是正文，讨论太阴病。\n"  # 正文：含"太阴"
        "\n"
        "# 其他章节\n"
        "无关内容。\n",
        encoding="utf-8",
    )
    return RagSearch(kb_root=str(kb))


class TestTfidfBackend:
    def test_is_available_and_backend_name(self, rag_on_tmp_kb):
        # 纯 Python TF-IDF 兜底恒可用（不再依赖 numpy）
        assert rag_on_tmp_kb.is_available()
        assert rag_on_tmp_kb.backend_name() == "TfidfBackend"

    def test_body_term_retrievable(self, rag_on_tmp_kb):
        res = rag_on_tmp_kb.search("太阴", k=5)
        assert len(res) >= 1
        assert all(r["source"] == "rag" for r in res)

    def test_heading_only_term_retrievable(self, rag_on_tmp_kb):
        # "六要素" 仅出现在标题，不在正文 → 经 _doc_text 并入匹配文本才可召回
        res = rag_on_tmp_kb.search("六要素", k=5)
        assert len(res) >= 1
        # 命中的 chunk 标题应含"六要素"
        assert any("六要素" in r["title"] for r in res)

    def test_search_empty_query(self, rag_on_tmp_kb):
        assert rag_on_tmp_kb.search("", k=5) == []
        assert rag_on_tmp_kb.search("   ", k=5) == []

    def test_search_no_match_returns_empty(self, rag_on_tmp_kb):
        assert rag_on_tmp_kb.search("完全不存在的词XYZ", k=5) == []

    def test_result_shape(self, rag_on_tmp_kb):
        res = rag_on_tmp_kb.search("太阴", k=5)
        if res:
            r = res[0]
            assert {"file", "line", "content", "context", "score",
                    "title", "source"} <= set(r.keys())
