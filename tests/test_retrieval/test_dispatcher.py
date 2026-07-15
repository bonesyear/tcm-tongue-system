"""dispatcher 单元测试：路由与合并逻辑。用临时 KB + 注入 fake RAG 精确测三条路由，
加一条真实 KB 集成测试。"""

import pytest

from src.retrieval.dispatcher import retrieve, retrieve_and, GREP_MIN_HITS


# ============================================================
# 临时 KB + fake RAG
# ============================================================
@pytest.fixture
def tmp_kb(tmp_path):
    """造一个可控命中数的临时 KB。
    "太阴" 出现在 3 行（>=GREP_MIN_HITS），"独有词" 只在 1 行（<阈值）。"""
    content = (
        "太阴病一\n"   # L1 太阴
        "太阴病二\n"   # L2 太阴
        "太阴病三\n"   # L3 太阴
        "独有词在此\n"  # L4 独有词
        "阳明病\n"     # L5
    )
    kb = tmp_path / "kb"
    kb.mkdir()
    (kb / "test.md").write_text(content, encoding="utf-8")
    return str(kb)


class FakeRag:
    """duck-typed RAG：可控 is_available 与返回结果。"""

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
# 路由：>= 阈值 → grep only
# ============================================================
class TestRouteGrepOnly:
    def test_greps_min_hits_uses_grep_only(self, tmp_kb):
        # 太阴命中 3 行 = GREP_MIN_HITS → 只用 grep，不调 RAG
        fake = FakeRag(available=True, results=[{"file": "test.md", "line": 99}])
        r = retrieve("太阴", kb_root=tmp_kb, rag=fake, syn_map={})
        assert r["method"] == "grep"
        assert r["grep_hits"] == GREP_MIN_HITS
        assert r["rag_hits"] == 0
        assert fake.calls == []  # 没调 RAG
        # results 全部 source=grep
        assert all(h["source"] == "grep" for h in r["results"])

    def test_invariant_results_equals_grep_plus_rag(self, tmp_kb):
        # 去重后恒有 len(results) == grep_hits + rag_hits
        rag_result = [{"file": "test.md", "line": 5, "content": "rag",
                       "context": [], "score": 0.9}]
        r = retrieve("独有词", kb_root=tmp_kb,
                     rag=FakeRag(available=True, results=rag_result), syn_map={})
        assert len(r["results"]) == r["grep_hits"] + r["rag_hits"]


# ============================================================
# 路由：< 阈值 + RAG 可用 → both / rag
# ============================================================
class TestRouteBoth:
    def test_below_threshold_rag_supplements(self, tmp_kb):
        # 独有词 1 命中 < 阈值；RAG 可用且返回结果 → both
        rag_result = [{"file": "test.md", "line": 5, "content": "rag补充",
                       "context": ["rag补充"], "score": 0.9, "source": "rag"}]
        fake = FakeRag(available=True, results=rag_result)
        r = retrieve("独有词", kb_root=tmp_kb, rag=fake, syn_map={})
        assert r["method"] == "both"
        assert r["grep_hits"] == 1
        assert r["rag_hits"] == 1
        assert len(r["results"]) == 2  # grep(1) + rag(1)

    def test_zero_grep_rag_has_results_method_rag(self, tmp_kb):
        # grep 0 命中、RAG 有结果 → method="rag"
        rag_result = [{"file": "test.md", "line": 5, "content": "rag",
                       "context": [], "score": 0.9}]
        fake = FakeRag(available=True, results=rag_result)
        r = retrieve("查不到的概念词XYZ", kb_root=tmp_kb, rag=fake, syn_map={})
        assert r["method"] == "rag"
        assert r["grep_hits"] == 0
        assert r["rag_hits"] == 1

    def test_merge_dedups_by_file_line(self, tmp_kb):
        # RAG 返回与 grep 同 (file,line) 的结果 → 去重，无新贡献 → method 退回 grep
        rag_dup = [{"file": "test.md", "line": 4, "content": "dup",
                    "context": [], "score": 0.9}]  # L4 是 grep 命中行
        fake = FakeRag(available=True, results=rag_dup)
        r = retrieve("独有词", kb_root=tmp_kb, rag=fake, syn_map={})
        assert len(r["results"]) == 1          # grep L4，rag 被去重
        assert r["rag_hits"] == 0              # 无新贡献
        assert r["method"] == "grep"           # rag 只返回重复 → 不计 both


# ============================================================
# 路由：< 阈值 + RAG 不可用 → grep only（诚实）
# ============================================================
class TestRouteRagUnavailable:
    def test_below_threshold_rag_unavailable(self, tmp_kb):
        fake = FakeRag(available=False)
        r = retrieve("独有词", kb_root=tmp_kb, rag=fake, syn_map={})
        assert r["method"] == "grep"
        assert r["grep_hits"] == 1
        assert r["rag_hits"] == 0
        assert len(r["results"]) == 1

    def test_zero_grep_rag_unavailable_empty(self, tmp_kb):
        fake = FakeRag(available=False)
        r = retrieve("查不到XYZ", kb_root=tmp_kb, rag=fake, syn_map={})
        assert r["method"] == "grep"
        assert r["results"] == []


# ============================================================
# synonyms_used 透传
# ============================================================
class TestSynonymPropagation:
    def test_synonyms_used_passed_through(self, tmp_kb):
        syn_map = {"独有词": ["太阴", "阳明"]}
        # 太阴(3)+阳明(1)+独有词(1) 命中 → >= 阈值 → grep
        r = retrieve("独有词", kb_root=tmp_kb, syn_map=syn_map,
                     rag=FakeRag())
        assert r["method"] == "grep"
        assert "太阴" in r["synonyms_used"]
        assert "阳明" in r["synonyms_used"]
        assert r["pattern"]  # 非空

    def test_non_key_no_synonyms(self, tmp_kb):
        r = retrieve("太阴", kb_root=tmp_kb, syn_map={}, rag=FakeRag())
        assert r["synonyms_used"] == []


# ============================================================
# 默认 RagSearch 的进程内缓存（历史 Bug 6：曾每次低命中查询重建索引）
# ============================================================
class TestRagCache:
    def test_default_rag_instance_reused(self, tmp_kb):
        from src.retrieval import dispatcher
        dispatcher._RAG_CACHE.clear()
        try:
            # 第一次低命中查询：rag=None → 新建并缓存 RagSearch
            retrieve("查不到的概念词XYZ", kb_root=tmp_kb, syn_map={})
            assert len(dispatcher._RAG_CACHE) == 1
            engine = next(iter(dispatcher._RAG_CACHE.values()))
            # 第二次查询必须复用同一实例（索引不重建）
            retrieve("另一个查不到的词ABC", kb_root=tmp_kb, syn_map={})
            assert len(dispatcher._RAG_CACHE) == 1
            assert next(iter(dispatcher._RAG_CACHE.values())) is engine
        finally:
            dispatcher._RAG_CACHE.clear()

    def test_injected_rag_bypasses_cache(self, tmp_kb):
        from src.retrieval import dispatcher
        dispatcher._RAG_CACHE.clear()
        retrieve("查不到的概念词XYZ", kb_root=tmp_kb, rag=FakeRag(), syn_map={})
        assert dispatcher._RAG_CACHE == {}


# ============================================================
# AND 查询路由（retrieve_and / " AND " 字符串 / 列表）
# ============================================================
class TestRetrieveAnd:
    def test_and_string_routes_to_grep_not_rag(self, tmp_kb):
        # "太阴 AND 阳明"：test.md 同时含两者 → grep 命中充足，不调 RAG
        # （回归：以前 " AND " 整串被 escape 成字面量 → grep 0 → 误走 RAG）
        fake = FakeRag(available=True, results=[{"file": "test.md", "line": 99}])
        r = retrieve("太阴 AND 阳明", kb_root=tmp_kb, rag=fake, syn_map={})
        assert r["method"] == "grep"
        assert r["grep_hits"] >= GREP_MIN_HITS   # 太阴(L1-3)+阳明(L5)=4
        assert r["rag_hits"] == 0
        assert fake.calls == []                   # 没调 RAG
        assert r["terms"] == ["太阴", "阳明"]

    def test_and_list_form_equivalent(self, tmp_kb):
        r_str = retrieve("太阴 AND 阳明", kb_root=tmp_kb, syn_map={}, rag=FakeRag())
        r_lst = retrieve(["太阴", "阳明"], kb_root=tmp_kb, syn_map={}, rag=FakeRag())
        assert r_str["method"] == r_lst["method"]
        assert r_str["grep_hits"] == r_lst["grep_hits"]
        assert r_str["terms"] == r_lst["terms"]

    def test_retrieve_and_expands_synonyms(self, tmp_kb):
        # 独有词 经别名词典展开为 "独有词|太阴"；与 阳明 做 AND 仍命中 test.md
        syn_map = {"独有词": ["太阴"]}
        r = retrieve_and(["独有词", "阳明"], kb_root=tmp_kb,
                         syn_map=syn_map, rag=FakeRag())
        assert r["method"] == "grep"
        assert "太阴" in r["synonyms_used"]
        # term 字段回标为原 term（独有词/阳明），不是 OR 模式串
        assert {h["term"] for h in r["results"]} <= {"独有词", "阳明"}

    def test_and_missing_term_falls_back_to_rag(self, tmp_kb):
        # test.md 无 "不存在XYZ" → AND 整文件不返回 → grep 0 → RAG 兜底
        rag_result = [{"file": "other.md", "line": 1, "content": "rag",
                       "context": [], "score": 0.9}]
        r = retrieve(["太阴", "不存在XYZ"], kb_root=tmp_kb,
                     rag=FakeRag(available=True, results=rag_result), syn_map={})
        assert r["method"] == "rag"
        assert r["grep_hits"] == 0
        assert r["rag_hits"] == 1

    def test_and_invariant_results_equals_grep_plus_rag(self, tmp_kb):
        rag_result = [{"file": "other.md", "line": 1, "content": "rag",
                       "context": [], "score": 0.9}]
        r = retrieve(["独有词", "阳明"], kb_root=tmp_kb,
                     rag=FakeRag(available=True, results=rag_result), syn_map={})
        assert len(r["results"]) == r["grep_hits"] + r["rag_hits"]

    def test_and_empty_terms_returns_empty(self, tmp_kb):
        r = retrieve_and([], kb_root=tmp_kb, syn_map={}, rag=FakeRag())
        assert r["method"] == "grep"
        assert r["results"] == []
        assert r["grep_hits"] == 0
        assert r["pattern"] == ""

    def test_and_whitespace_terms_filtered(self, tmp_kb):
        # 全是空白/空串的 term → 等价空 AND
        r = retrieve_and(["", "  "], kb_root=tmp_kb, syn_map={}, rag=FakeRag())
        assert r["results"] == []


# ============================================================
# 真实 KB 集成（依赖 numpy 兜底 RAG）
# ============================================================
class TestRealKbIntegration:
    def test_clinical_term_uses_grep(self):
        # 便软 经别名词典展开后 grep 命中充足 → method=grep
        r = retrieve("便软")
        assert r["method"] == "grep"
        assert r["grep_hits"] >= GREP_MIN_HITS
        assert "下利" in r["synonyms_used"]

    def test_conceptual_query_falls_back_to_rag(self):
        # 地图舌：现代临床术语，经方原文中无逐字出现 → grep=0 → RAG 兜底
        r = retrieve("地图舌 治疗")
        assert r["grep_hits"] == 0
        # RAG 可用（numpy 兜底）→ 有结果
        assert r["rag_hits"] > 0
        assert r["method"] in ("rag", "both")
        assert r["synonyms_used"] == []  # 非别名词典键

    def test_and_query_uses_grep_on_real_kb(self):
        # 苓桂 AND 五苓：跨条文鉴别，两词在多个文件共现 → grep 充足
        # （回归：以前 retrieve("苓桂 AND 五苓") 误走 RAG）
        r = retrieve("苓桂 AND 五苓")
        assert r["method"] == "grep"
        assert r["grep_hits"] >= GREP_MIN_HITS
        assert r["rag_hits"] == 0
        # 跨多文件
        assert len({h["file"] for h in r["results"]}) >= 2
        # term 字段是原词
        assert {h["term"] for h in r["results"]} <= {"苓桂", "五苓"}
