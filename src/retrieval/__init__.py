#!/usr/bin/env python3
"""
知识检索包（Knowledge Retrieval）
=================================

Grep 主路径 + 别名词典静态映射 + 可选 RAG 语义补充。

公共 API：
    retrieve(query)               统一检索入口（推荐）
                                  query 可为字符串、含 "AND" 的字符串、或字符串列表
    retrieve_and(terms)           AND 检索入口（跨条文鉴别，如 ["苓桂","五苓"]）
    search(query, context_lines)  纯 grep 检索（正则模式）
    search_and(terms)             AND 检索原语（正则模式，不经别名词典/RAG）
    expand(query)                 别名词典展开
    load_map()                    加载别名词典
    is_rag_available()            RAG 是否可用

用法：
    from src.retrieval import retrieve
    r = retrieve("便软")
    print(r["method"], r["synonyms_used"], len(r["results"]))

    # AND 检索（两种等价写法）
    r = retrieve("苓桂 AND 五苓")
    r = retrieve(["苓桂", "五苓"])

    from src.retrieval import search
    for hit in search("苓桂术甘汤"):
        print(hit["file"], hit["line"], hit["content"])

安全提示：
  - search()/search_and() 接受**原始正则**，不受信输入
    （用户/LLM 生成的字符串）请一律走 retrieve()（内部 re.escape）。
  - kb_root 参数与 TCM_KB_ROOT 环境变量是**部署配置**，不应来自用户
    输入——指向任意目录即可读出其中全部 .md 文件内容。

模块依赖（无环）：synonym_loader / grep_search / rag_search 为 leaf，
dispatcher 编排三者。详见 docs/architecture/retrieval-design.md。
"""

from .synonym_loader import (
    expand,
    expand_many,
    load_map,
    ExpandResult,
)
from .grep_search import (
    search,
    search_and,
    count_hits,
    list_kb_files,
)
from .rag_search import (
    RagSearch,
    is_available as is_rag_available,
    search as rag_search,
)
from .dispatcher import (
    retrieve,
    retrieve_and,
    GREP_MIN_HITS,
)

__all__ = [
    "retrieve",
    "retrieve_and",
    "search",
    "search_and",
    "count_hits",
    "list_kb_files",
    "expand",
    "expand_many",
    "load_map",
    "ExpandResult",
    "RagSearch",
    "is_rag_available",
    "rag_search",
    "GREP_MIN_HITS",
]
