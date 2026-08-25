#!/usr/bin/env python3
"""
RAG 语义检索层（Retrieval-Augmented Generation）
================================================

Grep 主路径的语义补充路径：用于跨条文鉴别、概念性查询（如"太阴水饮"这类
知识库里未必逐字出现、但需要语义关联的检索）。

双后端（见 docs/architecture/retrieval-design.md 决策 8 及 2026-07-12 更新）：
  - EmbeddingBackend：sentence-transformers 本地嵌入 + 余弦相似。真正语义。
    惰性 import；未装时不可用。
  - TfidfBackend：**纯 Python 倒排索引** TF-IDF 余弦检索。非真正语义嵌入，
    零外部依赖（连 numpy 都不需要），作为 sentence-transformers 未装时的
    轻量兜底。装上 sentence-transformers 后自动升级。
    （v1.3.3 前曾用 numpy 稠密矩阵实现：4498 chunk × 33613 词表占约 605 MB
    内存；倒排索引把同等索引压到约几十 MB，构建也更快。）

chunk 策略（任务要求"按段落切，保留章节标题作为元数据"）：
  按 markdown 空行分段，过长者按行边界再切（≤500 字符）；每段附带最近的
  `#` 标题行作为元数据。每 chunk 记录 file / start_line / end_line / title / text。

本模块是 leaf：惰性导入外部依赖，顶层零外部 import，故 `import rag_search`
永远不会因缺依赖而崩。dispatcher 靠 is_available() 决定是否调用。
"""

from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass


_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(os.path.dirname(_THIS_DIR))
DEFAULT_KB_ROOT = os.path.join(_REPO_ROOT, "knowledge_base")
DEFAULT_EXCLUDE = {"README.md"}

# 环境变量覆盖——与 grep_search 同一约定：TCM_KB_ROOT 必须对 grep 与 RAG
# 同时生效，否则设置该变量后 retrieve() 会把两个不同知识库的结果混在一起返回
_ENV_KB = os.environ.get("TCM_KB_ROOT")
if _ENV_KB:
    DEFAULT_KB_ROOT = _ENV_KB

_CHUNK_MAX_CHARS = 500
# 中日韩统一表意文字范围（简判，够用）
_CJK = r"一-鿿"


# ============================================================
# Chunk
# ============================================================
@dataclass
class Chunk:
    file: str           # 相对 kb_root 的路径
    start_line: int     # 1-based
    end_line: int       # 1-based
    title: str          # 最近的前置 # 标题（无则空）
    text: str


def _doc_text(c: Chunk) -> str:
    """用于检索匹配的文本 = 章节标题 + 正文。

    标题作为元数据保留在 Chunk.title，但若不并入匹配文本，仅出现在标题里的术语
    （如章节名"五苓散"）就无法被 TF-IDF/embedding 召回——标题上下文形同虚设。
    故匹配时把标题前置进文本；返回结果的 content/context 仍取正文（title 字段单独给）。
    """
    return (c.title + "\n" + c.text) if c.title else c.text


def _chunk_file(lines: list[str], rel: str) -> list[Chunk]:
    """按空行分段，附最近 # 标题，超长按行再切。"""
    chunks: list[Chunk] = []
    title = ""
    buf: list[str] = []
    buf_start = 0

    def flush(end_idx: int) -> None:
        nonlocal buf, buf_start
        if not buf:
            return
        text = "\n".join(buf).strip()
        if text:
            # 超长则按行切分
            if len(text) <= _CHUNK_MAX_CHARS:
                chunks.append(Chunk(rel, buf_start + 1, end_idx + 1, title, text))
            else:
                acc, acc_start = "", buf_start
                for i, ln in enumerate(buf):
                    if len(acc) + len(ln) + 1 > _CHUNK_MAX_CHARS and acc:
                        chunks.append(Chunk(rel, acc_start + 1, buf_start + i, title, acc.strip()))
                        acc, acc_start = ln, buf_start + i
                    else:
                        acc = acc + "\n" + ln if acc else ln
                if acc.strip():
                    chunks.append(Chunk(rel, acc_start + 1, end_idx + 1, title, acc.strip()))
        buf, buf_start = [], end_idx + 1

    for idx, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("#"):
            # 标题行：结束当前段、更新标题、标题本身不入段
            flush(idx - 1)
            title = stripped.lstrip("#").strip()
            continue
        if not stripped:
            flush(idx - 1)
            continue
        if not buf:
            buf_start = idx
        buf.append(line)
    flush(len(lines) - 1)
    return chunks


def build_chunks(kb_root: str | None = None, exclude: set[str] | None = None) -> list[Chunk]:
    """扫描 kb_root 下所有 .md，切成 Chunk 列表。"""
    from glob import glob
    root = os.path.abspath(kb_root or DEFAULT_KB_ROOT)
    excl = exclude if exclude is not None else DEFAULT_EXCLUDE
    files = sorted(glob(os.path.join(root, "**", "*.md"), recursive=True))
    chunks: list[Chunk] = []
    for f in files:
        if os.path.basename(f) in excl:
            continue
        try:
            with open(f, encoding="utf-8") as fh:
                lines = fh.read().splitlines()
        except OSError:
            continue
        rel = os.path.relpath(f, root)
        chunks.extend(_chunk_file(lines, rel))
    return chunks


# ============================================================
# 分词（CJK 字符 bigram + unigram + ASCII 词）
# ============================================================
_TOKEN_RE = re.compile(rf"[{_CJK}]+|[A-Za-z0-9]+")


def tokenize(text: str) -> list[str]:
    """中文按字符 bigram+unigram，ASCII 按词。捕获"太阴""水饮"等 2 字术语。"""
    tokens: list[str] = []
    for m in _TOKEN_RE.findall(text):
        if m[0] >= "一":  # CJK 段
            chars = list(m)
            for c in chars:
                tokens.append(c)              # unigram
            for a, b in zip(chars, chars[1:]):
                tokens.append(a + b)          # bigram
        else:
            tokens.append(m.lower())          # ascii 词
    return tokens


# ============================================================
# TF-IDF 后端（纯 Python 倒排索引，零依赖兜底）
# ============================================================
class TfidfBackend:
    """纯 Python 倒排索引 TF-IDF 余弦检索。非真正语义嵌入，轻量兜底。

    实现：每个 token 存 (chunk_idx, 归一化权重) 的 postings 列表；
    查询时只遍历查询 token 的 postings 累加点积——既省内存（只存非零项），
    查询也只触碰含查询词的 chunk。
    """

    def __init__(self, chunks: list[Chunk]):
        self.chunks = chunks
        self._idf: dict[str, float] = {}
        # token → [(chunk_idx, 该 chunk 内 L2 归一化后的 tf-idf 权重), ...]
        self._postings: dict[str, list[tuple[int, float]]] = {}
        self._built = False

    def build(self) -> None:
        # 词表 + TF（标题+正文，让标题术语也可召回）
        doc_tokens = [tokenize(_doc_text(c)) for c in self.chunks]
        n = len(self.chunks)
        df: dict[str, int] = {}
        for toks in doc_tokens:
            for t in set(toks):
                df[t] = df.get(t, 0) + 1
        # IDF（平滑）
        self._idf = {t: math.log((1 + n) / (1 + d)) + 1.0 for t, d in df.items()}
        postings: dict[str, list[tuple[int, float]]] = {}
        for i, toks in enumerate(doc_tokens):
            tf: dict[str, int] = {}
            for t in toks:
                tf[t] = tf.get(t, 0) + 1
            weights = {t: c * self._idf[t] for t, c in tf.items()}
            norm = math.sqrt(sum(w * w for w in weights.values())) or 1.0
            for t, w in weights.items():
                postings.setdefault(t, []).append((i, w / norm))
        self._postings = postings
        self._built = True

    def search(self, query: str, k: int = 5) -> list[dict]:
        if not self._built:
            self.build()
        q_toks = tokenize(query)
        if not q_toks:
            return []
        tf: dict[str, int] = {}
        for t in q_toks:
            tf[t] = tf.get(t, 0) + 1
        q_weights = {t: c * self._idf[t] for t, c in tf.items() if t in self._idf}
        q_norm = math.sqrt(sum(w * w for w in q_weights.values()))
        if q_norm == 0:
            return []
        # 稀疏点积：只遍历查询 token 的 postings
        scores: dict[int, float] = {}
        for t, qw in q_weights.items():
            qn = qw / q_norm
            for i, dw in self._postings.get(t, ()):
                scores[i] = scores.get(i, 0.0) + qn * dw
        top = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
        out: list[dict] = []
        for i, sim in top[:min(k, len(self.chunks))]:
            if sim <= 0:
                continue
            c = self.chunks[i]
            out.append({
                "file": c.file,
                "line": c.start_line,
                "content": c.text.splitlines()[0] if c.text else "",
                "context": c.text.splitlines(),
                "score": round(sim, 4),
                "title": c.title,
                "source": "rag",
            })
        return out


# ============================================================
# Embedding 后端（sentence-transformers，惰性，未装时不可用）
# ============================================================
class EmbeddingBackend:
    """sentence-transformers 嵌入 + 余弦。真正语义。需安装 sentence-transformers。"""

    def __init__(self, chunks: list[Chunk], model_name: str = "paraphrase-multilingual-MiniLM-L12-v2"):
        self.chunks = chunks
        self.model_name = model_name
        self._model = None
        self._vectors = None
        self._available = False
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore
            self._SentenceTransformer = SentenceTransformer
            self._available = True
        except ImportError:
            self._available = False

    def is_available(self) -> bool:
        return self._available

    def build(self) -> None:
        if not self._available:
            return
        self._model = self._SentenceTransformer(self.model_name)
        self._vectors = self._model.encode([_doc_text(c) for c in self.chunks],
                                           normalize_embeddings=True)

    def search(self, query: str, k: int = 5) -> list[dict]:
        import numpy as np  # 惰性
        if not self._available or self._model is None:
            return []
        qv = self._model.encode([query], normalize_embeddings=True)[0]
        sims = self._vectors @ qv
        order = np.argsort(-sims)[:min(k, len(self.chunks))]
        out = []
        for i in order:
            score = float(sims[i])
            if score <= 0:
                continue
            c = self.chunks[i]
            out.append({
                "file": c.file, "line": c.start_line,
                "content": c.text.splitlines()[0] if c.text else "",
                "context": c.text.splitlines(),
                "score": round(score, 4), "title": c.title, "source": "rag",
            })
        return out


# ============================================================
# RagSearch：统一入口，自动选后端
# ============================================================
class RagSearch:
    """RAG 检索统一入口。优先 embedding 后端，回退 TF-IDF。"""

    def __init__(self, kb_root: str | None = None, model_name: str | None = None):
        self.kb_root = os.path.abspath(kb_root or DEFAULT_KB_ROOT)
        self.model_name = model_name
        self._chunks: list[Chunk] | None = None
        self._backend: TfidfBackend | EmbeddingBackend | None = None

    def _ensure_index(self) -> None:
        if self._backend is not None:
            return
        if self._chunks is None:
            self._chunks = build_chunks(self.kb_root)
        # 优先 embedding
        emb = EmbeddingBackend(self._chunks, self.model_name or "paraphrase-multilingual-MiniLM-L12-v2")
        if emb.is_available():
            emb.build()
            self._backend = emb
        else:
            # 回退 TF-IDF（numpy）
            tfidf = TfidfBackend(self._chunks)
            tfidf.build()
            self._backend = tfidf

    def is_available(self) -> bool:
        """是否可用于检索。

        TF-IDF 兜底为纯 Python 实现（零依赖），故恒为 True；
        装有 sentence-transformers 时 _ensure_index 会自动升级为语义嵌入。
        保留本方法：dispatcher 与注入的 mock（duck-typing）都依赖此接口。
        """
        return True

    def backend_name(self) -> str:
        """当前实际使用的后端名（诊断用）。"""
        self._ensure_index()
        return type(self._backend).__name__

    def search(self, query: str, k: int = 5) -> list[dict]:
        if not query or not query.strip():
            return []
        if not self.is_available():
            return []
        self._ensure_index()
        return self._backend.search(query, k=k)


# ============================================================
# 模块级便捷函数
# ============================================================
_default: RagSearch | None = None


def _get_default() -> RagSearch:
    global _default
    if _default is None:
        _default = RagSearch()
    return _default


def is_available() -> bool:
    """模块级：RAG 是否可用。"""
    return _get_default().is_available()


def search(query: str, k: int = 5) -> list[dict]:
    """模块级便捷检索。返回 [{file,line,content,context,score,title,source}]。"""
    return _get_default().search(query, k=k)
