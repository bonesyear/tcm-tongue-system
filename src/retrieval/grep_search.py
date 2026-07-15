#!/usr/bin/env python3
"""
Grep 检索核心（Grep Search）
============================

对知识库全文做正则检索，返回带文件名+行号+上下文的命中。

接口（见 docs/architecture/retrieval-design.md 决策 2、3、6、9、10）：
    search(query, context_lines=3) -> list[dict]
        query 为 grep 正则模式（单术语如 "太阴水饮" 也是合法模式）。
        返回 [{"file","line","content","context"}]，按 (file,line) 去重——
        一行命中多术语仍算 1 条。context = 前 N + 匹配行 + 后 N，文件首尾截断。
    search_and(terms, context_lines=3) -> list[dict]
        AND：仅返回同时含全部 terms 的文件，附各 term 命中行（结果带 "term" 字段）。

设计要点：
  - 纯 Python re，不依赖 ripgrep（知识库约 1.1 万行，含《经方探源》全文；
    单查询全库逐行 re.search 实测约 1-2ms，文件行缓存生效后更快）。
  - 本模块是 leaf：不依赖 synonym_loader。临床口语词请先经
    synonym_loader.expand() 展开为模式再传入，或直接用 dispatcher.retrieve()。
  - KB 根目录由 __file__ 推导，可被 kb_root 参或 TCM_KB_ROOT 环境变量覆盖。
  - 递归 glob **/*.md，默认排除 README.md（元文档）。

安全提示：
  - search()/search_and() 的 query/terms 是**原始正则模式**，
    病态模式（如嵌套量词 "(a+)+$"）可造成灾难性回溯挂死进程（ReDoS）。
    不受信输入（用户/LLM 生成的字符串）请走 dispatcher.retrieve()——
    它对每个检索词 re.escape 后才拼接模式。
  - kb_root 参数与 TCM_KB_ROOT 环境变量是**部署配置**，不应来自用户输入：
    指向任意目录即可读出其中全部 .md 文件内容（受限任意文件读取面）。
"""

from __future__ import annotations

import os
import re
from glob import glob


# ============================================================
# 路径
# ============================================================
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(os.path.dirname(_THIS_DIR))
DEFAULT_KB_ROOT = os.path.join(_REPO_ROOT, "knowledge_base")
DEFAULT_EXCLUDE = {"README.md"}

# 环境变量覆盖（测试/部署时指向别处）
_ENV_KB = os.environ.get("TCM_KB_ROOT")
if _ENV_KB:
    DEFAULT_KB_ROOT = _ENV_KB


def _resolve_kb_root(kb_root: str | None) -> str:
    return os.path.abspath(kb_root or DEFAULT_KB_ROOT)


def list_kb_files(kb_root: str | None = None,
                  exclude: list[str] | None = None) -> list[str]:
    """递归列出 kb_root 下所有 .md 文件（绝对路径），排除 exclude 中的文件名。"""
    root = _resolve_kb_root(kb_root)
    excl = set(exclude) if exclude is not None else DEFAULT_EXCLUDE
    files = glob(os.path.join(root, "**", "*.md"), recursive=True)
    out = []
    for f in files:
        if os.path.basename(f) in excl:
            continue
        out.append(os.path.abspath(f))
    out.sort()
    return out


# ============================================================
# 文件读取缓存（按 path+mtime 失效）
# ============================================================
_FILE_CACHE: dict[str, tuple[float, list[str]]] = {}


def _read_lines(path: str) -> list[str]:
    """读文件为行列表（保留行内容、去末尾换行）。带 mtime 缓存。"""
    mtime = os.path.getmtime(path)
    cached = _FILE_CACHE.get(path)
    if cached and cached[0] == mtime:
        return cached[1]
    with open(path, encoding="utf-8") as f:
        lines = f.read().splitlines()
    _FILE_CACHE[path] = (mtime, lines)
    return lines


def _relpath(path: str, kb_root: str) -> str:
    """相对 kb_root 的路径，便于阅读（如 formulas/formula-system.md）。"""
    try:
        return os.path.relpath(path, kb_root)
    except ValueError:
        return path


def _context(lines: list[str], idx: int, n: int) -> list[str]:
    """返回 lines[idx] 前后各 n 行（含匹配行），首尾截断。"""
    start = max(0, idx - n)
    end = min(len(lines), idx + n + 1)
    return lines[start:end]


# ============================================================
# 检索
# ============================================================
def search(query: str,
           context_lines: int = 3,
           kb_root: str | None = None,
           case_sensitive: bool = True) -> list[dict]:
    """正则检索知识库全文。

    参数：
        query: grep 正则模式。空串 → 返回 []。
        context_lines: 匹配行前后各取多少行上下文。
        kb_root: 知识库根目录，默认 knowledge_base/。
        case_sensitive: 大小写敏感（中文无影响；ASCII 词默认敏感）。

    返回：[{"file": 相对路径, "line": 1-based 行号, "content": 匹配行文本,
            "context": [前后行...]}]，按 file→line 升序。
    """
    if not query or not query.strip():
        return []
    root = _resolve_kb_root(kb_root)
    flags = 0 if case_sensitive else re.IGNORECASE
    try:
        regex = re.compile(query, flags)
    except re.error as e:
        raise ValueError(f"无效的正则模式 {query!r}: {e}") from e

    results: list[dict] = []
    for path in list_kb_files(root):
        lines = _read_lines(path)
        rel = _relpath(path, root)
        for idx, line in enumerate(lines):
            if regex.search(line):
                results.append({
                    "file": rel,
                    "line": idx + 1,
                    "content": line,
                    "context": _context(lines, idx, context_lines),
                })
    # 已天然按 file→line 升序（glob 排序 + 行号递增），无需再排
    return results


def search_and(terms: list[str],
               context_lines: int = 3,
               kb_root: str | None = None,
               case_sensitive: bool = True) -> list[dict]:
    """AND 检索：仅返回同时包含全部 terms 的文件中，各 term 的命中行。

    每个 term 自身是一个 grep 正则模式。某文件缺少任一 term 则整文件不返回。
    适用于跨条文鉴别，如 search_and(["苓桂", "五苓"]) 找同时讨论两者的文件。

    返回：[{"file","line","content","context","term"}]，按 file→term→line 排序。
    """
    terms = [t for t in terms if t and t.strip()]
    if not terms:
        return []
    root = _resolve_kb_root(kb_root)
    flags = 0 if case_sensitive else re.IGNORECASE
    regexes: list[tuple[str, re.Pattern]] = []
    for t in terms:
        try:
            regexes.append((t, re.compile(t, flags)))
        except re.error as e:
            raise ValueError(f"无效的正则模式 {t!r}: {e}") from e

    results: list[dict] = []
    for path in list_kb_files(root):
        lines = _read_lines(path)
        rel = _relpath(path, root)
        # 每个术语在该文件的命中行索引
        per_term_hits: list[list[int]] = []
        for _term, regex in regexes:
            hits = [i for i, line in enumerate(lines) if regex.search(line)]
            if not hits:
                per_term_hits = []  # 任一缺失 → 整文件跳过
                break
            per_term_hits.append(hits)
        if not per_term_hits:
            continue
        # 收集每个 term 的命中行（去重，保持 file→term→line 序）
        seen_lines: set[tuple[str, int, str]] = set()
        for (term, _r), hits in zip(regexes, per_term_hits):
            for idx in hits:
                key = (rel, idx + 1, term)
                if key in seen_lines:
                    continue
                seen_lines.add(key)
                results.append({
                    "file": rel,
                    "line": idx + 1,
                    "content": lines[idx],
                    "context": _context(lines, idx, context_lines),
                    "term": term,
                })
    return results


# ============================================================
# 命中数（公共 API；dispatcher 目前直接用 len(search(...))）
# ============================================================
def count_hits(query: str, kb_root: str | None = None,
               case_sensitive: bool = True) -> int:
    """返回 search(query) 的命中行数（不构造 context，略快）。"""
    return len(search(query, context_lines=0, kb_root=kb_root,
                      case_sensitive=case_sensitive))
