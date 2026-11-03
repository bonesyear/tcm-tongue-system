"""批次 03 可靠性：embedding 后端加载失败路径回归。

mock 复现（不下载模型）：sentence-transformers 声称可用但模型加载/编码
抛异常时，retrieve() 曾直接崩溃——修复后须 stderr 可诊断并自动回退
TF-IDF 后端，检索结果照常返回。
"""
import importlib

import pytest

# 注意：src/retrieval/__init__.py 有 `from .rag_search import search as
# rag_search`，包属性 rag_search 被函数遮蔽——"import src.retrieval.rag_search
# as rag_mod" 会拿到那个函数。必须经 importlib 取真模块。
rag_mod = importlib.import_module("src.retrieval.rag_search")
from src.retrieval import retrieve
from src.retrieval.rag_search import EmbeddingBackend, RagSearch


@pytest.fixture
def tmp_kb(tmp_path):
    kb = tmp_path / "kb"
    kb.mkdir()
    (kb / "a.md").write_text("太阴病段落一\n\n无关段落\n", encoding="utf-8")
    return str(kb)


class _BoomModel:
    """模拟 SentenceTransformer：构造即抛（如模型下载失败/无网络）。"""

    def __init__(self, *a, **k):
        raise RuntimeError("模型加载失败（模拟：无网络/缓存缺失）")


def _make_broken_backend(chunks):
    emb = EmbeddingBackend(chunks, model_name="mock-broken")
    emb._available = True            # 模拟 sentence-transformers 已安装
    emb._SentenceTransformer = _BoomModel
    return emb


# ============================================================
# mock 复现 + 回退行为
# ============================================================
class TestEmbeddingFailure:
    def test_build_failure_marks_unavailable_with_warning(self, tmp_kb, capsys):
        chunks = rag_mod.build_chunks(tmp_kb)
        emb = _make_broken_backend(chunks)
        emb.build()  # 修复前：RuntimeError 穿透
        assert emb.is_available() is False
        assert "embedding" in capsys.readouterr().err

    def test_rag_search_falls_back_to_tfidf(self, tmp_kb, capsys):
        rag = RagSearch(kb_root=tmp_kb)
        rag_mod_embedding = rag_mod.EmbeddingBackend

        class _FakeEmb:
            def __init__(self, chunks, model_name=None):
                pass

            def is_available(self):
                return True

            def build(self):
                raise RuntimeError("模拟模型加载失败")

        rag_mod.EmbeddingBackend = _FakeEmb
        try:
            res = rag.search("太阴", k=5)
        finally:
            rag_mod.EmbeddingBackend = rag_mod_embedding
        # 修复前：RuntimeError 穿透，search 崩溃；修复后：TF-IDF 兜底有结果
        assert res, "回退 TF-IDF 后应有结果"
        assert rag.backend_name() == "TfidfBackend"
        assert "embedding" in capsys.readouterr().err

    def test_retrieve_survives_embedding_failure(self, tmp_kb, monkeypatch, capsys):
        # 端到端：retrieve 默认 rag 路径（grep 0 命中 → RAG）在后端损坏时
        # 不崩、返回 TF-IDF 结果
        class _FakeEmb:
            def __init__(self, chunks, model_name=None):
                pass

            def is_available(self):
                return True

            def build(self):
                raise RuntimeError("模拟模型加载失败")

        monkeypatch.setattr(rag_mod, "EmbeddingBackend", _FakeEmb)
        # 查询含"太阴"token（TF-IDF 可召回）但 grep 逐字无命中 → 强制走 RAG
        r = retrieve("太阴概念XYZ", kb_root=tmp_kb, syn_map={})
        assert r["grep_hits"] == 0
        assert r["rag_hits"] >= 1
        assert "embedding" in capsys.readouterr().err

    def test_healthy_embedding_backend_untouched(self, tmp_kb, monkeypatch):
        # 健康后端（不可用即未装 sentence-transformers）仍走 TF-IDF，无告警
        rag = RagSearch(kb_root=tmp_kb)
        assert rag.backend_name() == "TfidfBackend"
        res = rag.search("太阴", k=5)
        assert res
