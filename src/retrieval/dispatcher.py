#!/usr/bin/env python3
"""
检索调度器（Retrieval Dispatcher）
==================================

统一入口，按查询类型自动路由：先经别名词典展开，再优先 Grep；Grep 命中不足时
补充 RAG 语义检索。

路由规则（见 docs/architecture/retrieval-design.md 决策 7）：
  1. expand(query) → 得到 OR 模式 + synonyms_used
  2. grep_search.search(pattern) → grep_hits
  3. grep_hits >= GREP_MIN_HITS        → method="grep"，不调 RAG
     grep_hits <  GREP_MIN_HITS 且 RAG 可用 → 合并 grep+rag，method="both"
                                                  （grep_hits==0 且 rag 有结果 → "rag"）
     grep_hits <  GREP_MIN_HITS 且 RAG 不可用 → method="grep"，诚实返回少量命中

AND 查询（决策 10 的补全）：
  retrieve("苓桂 AND 五苓") 或 retrieve_and(["苓桂", "五苓"])。
  每个 term 先经 expand() 展开为 OR 模式（含同义词），再交 grep_search.search_and()
  做 AND——只返回同时命中全部 term（任一同义词即可）的文件。grep 不足阈值时同样补 RAG。

依赖（无环）：synonym_loader、grep_search、rag_search。
"""

from __future__ import annotations

import re
import threading

from .kb_paths import kb_map_path, resolve_kb_root
from .synonym_loader import expand, ExpandResult, _load_map_cached
from .grep_search import search as grep_search, search_and as grep_search_and
from .rag_search import MIN_RAG_SCORE, RagSearch


GREP_MIN_HITS = 3  # Grep 命中数阈值，低于此值才考虑补充 RAG


def _expand(query, kb_root, syn_map):
    if syn_map is None:
        syn_map = _load_map_cached(kb_map_path(kb_root))
    return expand(query, syn_map=syn_map)

# RagSearch 进程内缓存（按 kb_root 归一化路径为键）。
# 索引构建成本高（全库切 chunk + 建倒排），每次 retrieve 新建实例会把
# 该成本乘到每个低命中查询上（历史 Bug 6）。缓存后仅首查付一次构建成本。
# 注意：进程存活期间 KB 内容变更不会触发重建；需要刷新可清空本字典。
_RAG_CACHE: dict[str, RagSearch] = {}
_RAG_CACHE_LOCK = threading.RLock()


def _default_rag(kb_root: str | None) -> RagSearch:
    """按 kb_root 取（或新建）进程内共享的 RagSearch 实例。"""
    key = resolve_kb_root(kb_root)
    engine = _RAG_CACHE.get(key)
    if engine is None:
        with _RAG_CACHE_LOCK:
            engine = _RAG_CACHE.get(key)
            if engine is None:
                engine = RagSearch(kb_root=key)
                _RAG_CACHE[key] = engine
    return engine

# AND 语法分隔符："a AND b AND c"（大小写不敏感，前后须有空格，避免误伤术语）
_AND_SPLIT = re.compile(r"\s+AND\s+", re.IGNORECASE)

# 悬空 AND 判定：AND 作为独立词出现（前后空白/串首/串尾），用于 fail-loud
_AND_TOKEN = re.compile(r"(?i)(?:^|\s)AND(?:\s|$)")


def retrieve(query: "str | list[str] | tuple[str, ...]",
             context_lines: int = 3,
             kb_root: str | None = None,
             syn_map: dict | None = None,
             rag: RagSearch | None = None) -> dict:
    """统一检索入口。

    参数：
        query: 临床查询。可为——
            - 单个口语词/标准术语字符串（OR 检索，经别名词典展开）；
            - 含 ``AND`` 的字符串，如 ``"苓桂 AND 五苓"``（AND 检索）；
            - 字符串列表/元组，如 ``["苓桂", "五苓"]``（AND 检索）。
            字符串查询会先 strip 首尾空白；非字符串输入抛 TypeError；
            悬空 AND（``"太阴 AND"`` / ``"AND 太阴"`` / 连续 AND）抛
            ValueError——fail-loud，不再静默当普通词检索落空。
        context_lines: grep 结果上下文行数。
        kb_root: 知识库根目录（测试可注入临时目录）。
        syn_map: 别名词典（测试可注入；默认加载 synonym_map.yaml）。
        rag: RAG 实例（测试可注入 mock；默认按 kb_root 新建）。

    大小写策略：retrieve 层统一大小写不敏感（ASCII 词；RAG 分词本就
    小写化，grep 在此以 IGNORECASE 对齐）。search()/search_and() 是原始
    正则接口，保持默认大小写敏感，精确语义不变。

    返回：
        {
          "results":         [{"file","line","content","context","source",...}],
          "method":          "grep" | "rag" | "both",
          "synonyms_used":   [str, ...],     # 实际展开用到的同义词
          "grep_hits":       int,
          "rag_hits":        int,
          "pattern":         str,            # 展开后的 grep 正则（诊断用）
          "terms":           [str, ...],     # 全部检索词
        }
    """
    # AND 路由：列表/元组，或含 " AND " 的字符串
    if isinstance(query, (list, tuple)):
        return retrieve_and(list(query), context_lines=context_lines,
                            kb_root=kb_root, syn_map=syn_map, rag=rag)
    if not isinstance(query, str):
        raise TypeError(
            f"retrieve() 的 query 应为字符串或字符串列表，实际为 "
            f"{type(query).__name__}"
        )
    query = query.strip()
    if not query:
        # 空查询：与 expand() 空 pattern 契约一致，返回空结果
        return {
            "results": [], "method": "grep", "synonyms_used": [],
            "grep_hits": 0, "rag_hits": 0, "pattern": "", "terms": [],
        }
    # 悬空 AND fail-loud：AND 在串首/串尾或连续出现，说明调用方拼接查询
    # 有 bug——静默当普通词检索只会落空，必须显式报错
    if _AND_TOKEN.search(query):
        tokens = query.split()
        and_idx = [i for i, t in enumerate(tokens) if t.upper() == "AND"]
        if (tokens[0].upper() == "AND" or tokens[-1].upper() == "AND"
                or any(b - a == 1 for a, b in zip(and_idx, and_idx[1:]))):
            raise ValueError(
                f"悬空/连续 AND: {query!r}——AND 检索须为 "
                f"'词A AND 词B' 形式（两端各有一个非空检索词）"
            )
    if _AND_SPLIT.search(query):
        parts = [p.strip() for p in _AND_SPLIT.split(query)]
        parts = [p for p in parts if p]
        if len(parts) > 1:
            return retrieve_and(parts, context_lines=context_lines,
                                kb_root=kb_root, syn_map=syn_map, rag=rag)

    # 1. 别名词典展开
    exp: ExpandResult = _expand(query, kb_root, syn_map)

    # 2. Grep 主路径（retrieve 层统一大小写不敏感，与 RAG 分词对齐）
    grep_results = grep_search(exp.pattern, context_lines=context_lines,
                               kb_root=kb_root, case_sensitive=False) \
        if exp.pattern else []
    for r in grep_results:
        r.setdefault("source", "grep")
    grep_hits = len(grep_results)

    # 3. 路由：是否补充 RAG
    rag_raw: list[dict] = []

    if grep_hits < GREP_MIN_HITS:
        rag_engine = rag if rag is not None else _default_rag(kb_root)
        if rag_engine.is_available():
            # RAG 用全部检索词（原词+同义词）做语义查询，覆盖更广
            rag_query = " ".join(exp.terms) if exp.terms else query
            rag_raw = rag_engine.search(rag_query, k=5)

    return _merge(grep_results, grep_hits, rag_raw, exp.synonyms_used,
                  exp.pattern, exp.terms)


def retrieve_and(terms: "list[str] | tuple[str, ...]",
                 context_lines: int = 3,
                 kb_root: str | None = None,
                 syn_map: dict | None = None,
                 rag: RagSearch | None = None) -> dict:
    """AND 检索入口：返回同时包含全部 terms（任一同义词即可）的文件中各 term 命中行。

    每个 term 先经 expand() 展开为 OR 模式（原词 + 同义词），再交
    grep_search.search_and() 做 AND——某文件缺少任一 term 的整组模式即整文件不返回。
    适用于跨条文鉴别，如 retrieve_and(["苓桂", "五苓"])。

    返回结构与 retrieve() 一致；results 各条带 "term" 字段（标注命中的原 term）。
    pattern 为各 term 展开模式的 " AND " 连接（诊断用，非单一可检索正则）。
    """
    clean = [t.strip() for t in terms if isinstance(t, str) and t.strip()]
    if not clean:
        return {
            "results": [], "method": "grep", "synonyms_used": [],
            "grep_hits": 0, "rag_hits": 0, "pattern": "", "terms": [],
        }

    # 1. 每个 term 展开为 OR 模式
    expanded = [_expand(t, kb_root, syn_map) for t in clean]
    patterns = [e.pattern for e in expanded]
    # 模式 → 原 term 的回标（search_and 的 term 字段存的是模式串，对外应回标原词）
    pat_to_term = dict(zip(patterns, clean))

    # 2. Grep AND 主路径（retrieve 层统一大小写不敏感，与 RAG 分词对齐）
    grep_results = grep_search_and(patterns, context_lines=context_lines,
                                   kb_root=kb_root,
                                   case_sensitive=False) if all(patterns) else []
    for r in grep_results:
        r.setdefault("source", "grep")
        if r.get("term") in pat_to_term:
            r["term"] = pat_to_term[r["term"]]
    grep_hits = len(grep_results)

    # 3. 路由：是否补充 RAG（用全部 term + 同义词的并集做语义查询）
    rag_raw: list[dict] = []
    if grep_hits < GREP_MIN_HITS:
        rag_engine = rag if rag is not None else _default_rag(kb_root)
        if rag_engine.is_available():
            all_terms: list[str] = []
            for e in expanded:
                all_terms.extend(e.terms)
            rag_raw = rag_engine.search(" ".join(all_terms) if all_terms
                                        else " ".join(clean), k=5)
            rag_raw = [r for r in rag_raw if r.get("score", 0) >= MIN_RAG_SCORE]
            if rag_raw:
                and_hits = grep_search_and(patterns, context_lines=0,
                                          kb_root=kb_root, case_sensitive=False)
                allowed_files = {r["file"] for r in and_hits}
                rag_raw = [dict(r, term=" AND ".join(clean)) for r in rag_raw
                           if r.get("file") in allowed_files]

    # 4. 同义词并集（去重保序）
    syns_used: list[str] = []
    seen_syn: set[str] = set()
    for e in expanded:
        for s in e.synonyms_used:
            if s not in seen_syn:
                seen_syn.add(s)
                syns_used.append(s)

    return _merge(grep_results, grep_hits, rag_raw, syns_used,
                  " AND ".join(patterns), clean)


def _merge(grep_results: list[dict], grep_hits: int, rag_raw: list[dict],
           synonyms_used: list[str], pattern: str, terms: list[str]) -> dict:
    """合并 grep + rag，计算 method 与 invariant。

    invariant：len(results) == grep_hits + rag_hits（rag_hits 只计去重后的新贡献）。

    去重语义：RAG 结果是一条 chunk 证据（带 end_line 行范围），与 grep 的
    单行命中按"行范围是否已被 grep 完全覆盖"判定——chunk 范围内存在任一
    grep 未覆盖的行即保留（首行相同不代表整段证据重复；旧实现按首行去重，
    会丢掉 chunk 内 grep 未命中行的补充证据）。RAG 结果缺 end_line 时退化为
    单行精确判定。
    """
    # grep 命中行按文件分组（results 天然按 file→line 升序）
    grep_lines: dict[str, set[int]] = {}
    for r in grep_results:
        grep_lines.setdefault(r["file"], set()).add(r["line"])

    # grep 在前，rag 去重后追加。注意不能用 grep 的 (file,line) 集合对 rag
    # 做首行短路：chunk 首行命中只说明证据有交集，不代表整段重复
    merged = list(grep_results)
    seen_rag: set[tuple[str, int]] = set()
    new_rag = 0
    for r in rag_raw:
        key = (r["file"], r["line"])
        if key in seen_rag:
            continue  # 完全同位的 rag 重复项
        start, end = r["line"], r.get("end_line", r["line"])
        covered = grep_lines.get(r["file"], set())
        if covered and all((start + i) in covered
                           for i in range(end - start + 1)):
            continue  # 整段行范围已被 grep 命中覆盖，确属重复
        seen_rag.add(key)
        r.setdefault("source", "rag")
        merged.append(r)
        new_rag += 1

    # method：以"新贡献"为准——rag 只返回重复时不计 both
    method = "grep"
    if grep_hits < GREP_MIN_HITS and new_rag > 0:
        method = "rag" if grep_hits == 0 else "both"

    return {
        "results": merged,
        "method": method,
        "synonyms_used": synonyms_used,
        "grep_hits": grep_hits,
        "rag_hits": new_rag,
        "pattern": pattern,
        "terms": terms,
    }
