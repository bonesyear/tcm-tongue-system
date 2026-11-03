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
  - retrieve() 层统一**大小写不敏感**（ASCII 词）；search()/search_and()
    作为原始正则接口保持默认大小写敏感。
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
from .kb_status import (
    KB_CATEGORY_DEFS,
    inspect_kb,
    inspect_kb_categories,
    kb_category_root,
    kb_env_key,
    kb_disabled_key,
    kb_legacy_root,
)


def invalidate_kb_caches(kb_root=None):
    """知识库被外部替换后，清除该根的词典、文件和 RAG 缓存。"""
    import os
    from . import dispatcher, grep_search, synonym_loader
    from .kb_paths import kb_map_path, resolve_kb_root

    root = resolve_kb_root(kb_root)
    with synonym_loader._CACHE_LOCK:
        synonym_loader._CACHE.pop(kb_map_path(root), None)
    with dispatcher._RAG_CACHE_LOCK:
        dispatcher._RAG_CACHE.pop(root, None)
    with grep_search._FILE_CACHE_LOCK:
        for path in list(grep_search._FILE_CACHE):
            try:
                inside = os.path.commonpath((root, path)) == root
            except ValueError:
                inside = False
            if inside:
                grep_search._FILE_CACHE.pop(path, None)


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
    "invalidate_kb_caches",
    "inspect_kb",
    "inspect_kb_categories",
    "kb_category_root",
    "kb_env_key",
    "kb_disabled_key",
    "kb_legacy_root",
    "KB_CATEGORY_DEFS",
    "GREP_MIN_HITS",
]
