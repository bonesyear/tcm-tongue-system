#!/usr/bin/env python3
"""
别名词典加载与查询展开（Synonym Loader）
================================================

把"临床口语描述"展开为知识库里实际出现的标准术语，供 grep_search 做 OR 检索。

例：expand("便软") → pattern="便软|下利|便溏|大便溏|溏泄|大便微溏"
                   synonyms_used=["下利","便溏","大便溏","溏泄","大便微溏"]

设计要点（见 docs/architecture/retrieval-design.md 决策 1、4）：
  - YAML 解析优先用 PyYAML（环境已装）；未装则回退手写解析器，只认一种受限格式
    （顶层 `key:` + 缩进 `- 项` 的 block 序列）。从而不硬依赖 PyYAML，也不把它
    加进 requirements.txt。
  - expand() 对每个术语 re.escape 后再 `|` 连接——防止术语中的正则元字符破坏匹配。
  - 原查询词始终并入模式（与别名词典给出的标准术语一起 OR）。
  - query 不是别名词典的键时，pattern = re.escape(query)，synonyms_used = []。

本模块是 leaf：不依赖 retrieval 内其它模块，可独立测试。
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field


# ============================================================
# 路径
# ============================================================
# src/retrieval/synonym_loader.py → 上溯两级到 repo_root → knowledge_base/
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(os.path.dirname(_THIS_DIR))
DEFAULT_MAP_PATH = os.path.join(_REPO_ROOT, "knowledge_base", "synonym_map.yaml")


# ============================================================
# YAML 解析（PyYAML 优先，回退手写）
# ============================================================
def _parse_simple_yaml(text: str) -> dict[str, list[str]]:
    """手写回退解析器：只认 block 风格 `key:` + 缩进 `- 项`。

    约束（在 synonym_map.yaml 顶部注释里写明）：
      - `#` 开头为注释；空行跳过。
      - `key:` 行（行尾一个 ASCII 冒号，冒号后无内容）→ 新建键。
      - `  - 项` 行（缩进后以 `- ` 开头）→ 当前键的列表项。
      - 不支持 flow 风格、引号、锚点、行内 `key: value`。

    与 PyYAML 一致的两点容忍（避免在装了 PyYAML 与未装时行为分叉）：
      - 键行尾随空白：`便软: ` 视作 `便软:`。
      - 键/项行尾随注释：`便软: # 说明`、`- 下利 # 说明` 视作去掉注释。
    """
    result: dict[str, list[str]] = {}
    current_key: str | None = None
    for raw in text.splitlines():
        if not raw.strip():
            continue
        stripped = raw.strip()
        if stripped.startswith("#"):
            continue
        # 行内注释：仅 " #"（空格+井号，YAML 注释规则）才剥离，避免误伤含 # 的术语
        if " #" in stripped:
            stripped = stripped.split(" #", 1)[0].rstrip()
        if stripped.startswith("- "):
            if current_key is None:
                raise ValueError(f"别名词典列表项缺少所属键: {raw!r}")
            item = stripped[2:].strip()
            if item:
                result[current_key].append(item)
            continue
        if stripped.endswith(":"):
            key = stripped[:-1].strip()
            if not key:
                raise ValueError(f"别名词典空键: {raw!r}")
            result[key] = []
            current_key = key
            continue
        raise ValueError(
            f"别名词典行无法解析（手写解析器仅支持 'key:' 与 '- 项'）: {raw!r}"
        )
    return result


def load_map(path: str | None = None) -> dict[str, list[str]]:
    """加载别名词典为 {临床词: [标准术语,...]}。

    优先 PyYAML；未安装则用手写解析器。path 默认 knowledge_base/synonym_map.yaml。
    """
    p = os.path.abspath(path or DEFAULT_MAP_PATH)
    with open(p, encoding="utf-8") as f:
        text = f.read()
    try:
        import yaml  # type: ignore
        data = yaml.safe_load(text)
    except ImportError:
        return _parse_simple_yaml(text)
    if not isinstance(data, dict):
        raise ValueError(f"别名词典顶层必须是 dict，实际: {type(data).__name__}")
    # 规范化：值统一为 list[str]
    normalized: dict[str, list[str]] = {}
    for key, val in data.items():
        if val is None:
            normalized[str(key)] = []
        elif isinstance(val, list):
            normalized[str(key)] = [str(v) for v in val]
        else:
            # 单值容忍为单项列表
            normalized[str(key)] = [str(val)]
    return normalized


# ============================================================
# 缓存（按路径+mtime 失效，避免每次 expand 都读盘）
# ============================================================
_CACHE: dict[str, tuple[float, dict[str, list[str]]]] = {}


def _load_map_cached(path: str | None = None) -> dict[str, list[str]]:
    p = os.path.abspath(path or DEFAULT_MAP_PATH)
    mtime = os.path.getmtime(p)
    cached = _CACHE.get(p)
    if cached and cached[0] == mtime:
        return cached[1]
    m = load_map(p)
    _CACHE[p] = (mtime, m)
    return m


# ============================================================
# 查询展开
# ============================================================
@dataclass
class ExpandResult:
    """expand() 的返回。"""
    query: str                       # 原查询
    pattern: str                     # re.escape 后 OR 连接的正则；空查询为 ""
    terms: list[str] = field(default_factory=list)          # 全部检索词 = [原词] + 同义词
    synonyms_used: list[str] = field(default_factory=list)  # 实际生效同义词（不含原词）


def expand(query: str, syn_map: dict[str, list[str]] | None = None) -> ExpandResult:
    """把临床查询展开为 OR 正则模式。

    - query 命中别名词典：terms = [query] + 其标准术语（去重、保序）。
    - query 未命中：terms = [query]，synonyms_used = []。
    - 空 query：返回空 pattern（grep_search 据此返回 []）。
    """
    q = query or ""
    if not q.strip():
        return ExpandResult(query=q, pattern="", terms=[], synonyms_used=[])

    sm = syn_map if syn_map is not None else _load_map_cached()
    raw_syns = sm.get(q, [])

    # 去重保序，剔除与原词重复者
    seen: set[str] = set()
    terms = [q]
    seen.add(q)
    synonyms_used: list[str] = []
    for s in raw_syns:
        if s and s not in seen:
            seen.add(s)
            terms.append(s)
            synonyms_used.append(s)

    pattern = "|".join(re.escape(t) for t in terms)
    return ExpandResult(query=q, pattern=pattern, terms=terms, synonyms_used=synonyms_used)


def expand_many(queries: list[str], syn_map: dict[str, list[str]] | None = None) -> ExpandResult:
    """把多个查询合并为一个 OR 模式（用于 AND 查询里逐项展开后合并）。

    返回的 terms/synonyms_used 为所有查询展开后的并集（去重保序）。
    """
    sm = syn_map if syn_map is not None else _load_map_cached()
    seen: set[str] = set()
    all_terms: list[str] = []
    all_syns: list[str] = []
    for q in queries:
        r = expand(q, sm)
        for t in r.terms:
            if t and t not in seen:
                seen.add(t)
                all_terms.append(t)
        for s in r.synonyms_used:
            if s not in seen:
                seen.add(s)
                all_syns.append(s)
    pattern = "|".join(re.escape(t) for t in all_terms) if all_terms else ""
    return ExpandResult(
        query="|".join(queries),
        pattern=pattern,
        terms=all_terms,
        synonyms_used=all_syns,
    )
