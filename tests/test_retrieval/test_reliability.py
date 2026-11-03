"""批次 03 可靠性：retrieval 统一入口回归。

覆盖：
  - retrieve() 输入 trim（前后空白）与非字符串输入 fail-loud
  - 悬空/连续 AND fail-loud（ValueError），不再静默走 OR 落空
  - chunk.file 路径分隔符统一为正斜杠（Windows 与 grep 结果一致）
  - retrieve 层 grep/RAG 大小写策略统一（ASCII 词大小写不敏感）
  - RAG chunk 按首行去重导致补充证据丢失：改为按 chunk 行范围判定
"""
import pytest

from src.retrieval import retrieve, retrieve_and
from src.retrieval.rag_search import RagSearch, build_chunks
from src.retrieval.dispatcher import GREP_MIN_HITS
from src.retrieval.grep_search import search


@pytest.fixture
def tmp_kb(tmp_path):
    """两行一段的临时 KB：独有词在段首，段内第二行是"补充证据"。"""
    content = "独有词在段首\n这段补充证据只有 RAG chunk 能带到\n"
    kb = tmp_path / "kb"
    kb.mkdir()
    (kb / "test.md").write_text(content, encoding="utf-8")
    return str(kb)


class FakeRag:
    def __init__(self, available=True, results=None):
        self._available = available
        self._results = results or []
        self.calls = []

    def is_available(self):
        return self._available

    def search(self, query, k=5):
        self.calls.append(query)
        return list(self._results)


# ============================================================
# 输入 trim 与类型
# ============================================================
class TestInputTrim:
    def test_whitespace_query_trimmed(self, tmp_kb):
        r = retrieve("  独有词  ", kb_root=tmp_kb, rag=FakeRag(available=False))
        assert r["grep_hits"] == 1
        assert r["pattern"] == "独有词"

    def test_blank_query_returns_empty(self, tmp_kb):
        r = retrieve("   ", kb_root=tmp_kb, rag=FakeRag(available=False))
        assert r["results"] == []
        assert r["grep_hits"] == 0

    def test_non_string_query_raises(self, tmp_kb):
        with pytest.raises(TypeError):
            retrieve(123, kb_root=tmp_kb, rag=FakeRag(available=False))


# ============================================================
# 悬空 AND fail-loud
# ============================================================
class TestDanglingAnd:
    @pytest.mark.parametrize("query", [
        "太阴 AND", "AND 太阴", "AND", "太阴 AND  AND 五苓", "a AND b AND",
    ])
    def test_dangling_and_raises(self, tmp_kb, query):
        with pytest.raises(ValueError):
            retrieve(query, kb_root=tmp_kb, rag=FakeRag(available=False))

    def test_valid_and_still_works(self, tmp_kb):
        # 回归：合法 AND 不受影响（两行同文件，两词各命中一行）
        r = retrieve("独有词 AND 补充", kb_root=tmp_kb,
                     rag=FakeRag(available=False))
        assert r["grep_hits"] == 2


# ============================================================
# Windows 路径分隔符一致
# ============================================================
class TestPathSeparator:
    def _kb_with_subdir(self, tmp_path):
        kb = tmp_path / "kb"
        sub = kb / "sub"
        sub.mkdir(parents=True)
        (sub / "a.md").write_text("独有词在段首\n这段补充证据只有 RAG chunk 能带到\n",
                                  encoding="utf-8")
        return str(kb)

    def test_chunk_file_uses_forward_slash(self, tmp_path):
        kb = self._kb_with_subdir(tmp_path)
        chunks = build_chunks(kb)
        assert chunks, "应有 chunk"
        # 子目录文件在 Windows 下 relpath 含反斜杠——必须统一为正斜杠
        assert any("/" in c.file for c in chunks)
        assert all("\\" not in c.file for c in chunks)

    def test_rag_result_file_matches_grep_style(self, tmp_path):
        # 真实 RAG 结果（grep 0 命中触发）file 字段与 grep 同风格（正斜杠）
        kb = self._kb_with_subdir(tmp_path)
        r = retrieve("chunk 证据", kb_root=kb, syn_map={})
        assert r["grep_hits"] == 0
        assert r["rag_hits"] >= 1
        assert all("\\" not in h["file"] for h in r["results"])
        assert all(h["file"].startswith("sub/") for h in r["results"])


# ============================================================
# grep/RAG 大小写策略统一
# ============================================================
class TestCasePolicy:
    def test_ascii_case_insensitive_at_retrieve_level(self, tmp_path):
        kb = tmp_path / "kb"
        kb.mkdir()
        (kb / "a.md").write_text("TaiYin 术语行\n", encoding="utf-8")
        r = retrieve("taiyin", kb_root=str(kb), rag=FakeRag(available=False))
        assert r["grep_hits"] == 1  # 大小写不敏感才能命中
        r2 = retrieve("TAIYIN", kb_root=str(kb), rag=FakeRag(available=False))
        assert r2["grep_hits"] == 1

    def test_raw_search_stays_case_sensitive(self, tmp_path):
        # search() 是原始正则接口，保持默认大小写敏感（精确语义）
        kb = tmp_path / "kb"
        kb.mkdir()
        (kb / "a.md").write_text("TaiYin 术语行\n", encoding="utf-8")
        assert search("taiyin", kb_root=str(kb)) == []
        assert len(search("taiyin", kb_root=str(kb),
                          case_sensitive=False)) == 1

    def test_real_kb_ascii_query_consistent(self):
        # 真实 KB：retrieve 层两种写法命中一致
        r1 = retrieve("shaoyang", syn_map={})
        r2 = retrieve("SHAOYANG", syn_map={})
        assert r1["grep_hits"] == r2["grep_hits"]


# ============================================================
# RAG chunk 补充证据丢失（按首行去重的缺陷）
# ============================================================
class TestRagChunkDedup:
    def test_chunk_with_uncovered_lines_kept(self, tmp_kb):
        # grep 命中 L1（独有词）；RAG chunk [1..2] 首行=L1——
        # 旧按 (file,line) 首行去重会丢弃整段补充证据（L2），现按行范围判定
        rag_result = [{"file": "test.md", "line": 1, "end_line": 2,
                       "content": "独有词在段首", "context": ["独有词在段首",
                       "这段补充证据只有 RAG chunk 能带到"],
                       "score": 0.9, "source": "rag"}]
        r = retrieve("独有词", kb_root=tmp_kb,
                     rag=FakeRag(available=True, results=rag_result))
        assert r["grep_hits"] == 1
        assert r["rag_hits"] == 1           # 补充证据保留
        assert r["method"] == "both"
        assert len(r["results"]) == r["grep_hits"] + r["rag_hits"]

    def test_exact_line_chunk_still_deduped(self, tmp_kb):
        # RAG 单行 chunk 与 grep 完全同位 → 仍是重复，应去重
        rag_result = [{"file": "test.md", "line": 1, "end_line": 1,
                       "content": "dup", "context": [], "score": 0.9}]
        r = retrieve("独有词", kb_root=tmp_kb,
                     rag=FakeRag(available=True, results=rag_result))
        assert r["rag_hits"] == 0
        assert r["method"] == "grep"
        assert len(r["results"]) == 1

    def test_chunk_fully_covered_by_grep_deduped(self, tmp_path):
        # chunk [1..2] 两行都被 grep 命中 → 整段已覆盖，去重
        kb = tmp_path / "kb"
        kb.mkdir()
        (kb / "a.md").write_text("独有词一行\n独有词二行\n", encoding="utf-8")
        rag_result = [{"file": "a.md", "line": 1, "end_line": 2,
                       "content": "dup", "context": [], "score": 0.9}]
        r = retrieve("独有词", kb_root=str(kb), syn_map={},
                     rag=FakeRag(available=True, results=rag_result))
        assert r["grep_hits"] == 2
        assert r["rag_hits"] == 0
        assert len(r["results"]) == 2

    def test_and_route_chunk_dedup(self, tmp_kb):
        # AND 路径同样按行范围判定
        rag_result = [{"file": "test.md", "line": 1, "end_line": 2,
                       "content": "x", "context": [], "score": 0.9}]
        r = retrieve_and(["独有词", "补充"], kb_root=tmp_kb,
                         rag=FakeRag(available=True, results=rag_result),
                         syn_map={})
        assert r["grep_hits"] == 2
        assert r["rag_hits"] == 0  # [1..2] 已被 grep 两行覆盖
