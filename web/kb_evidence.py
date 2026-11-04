"""报告用知识库候选条文检索；不装配周报或写健康记录。"""
from __future__ import annotations

from src.dimensions import DIMENSIONS
import records_store

MAX_KB_EXCERPT_CHARS = 1200
MAX_KB_TOTAL_CHARS = 12000


def _kb_references(rec, kb_root=None, max_hits: int = 10,
                   anchor_terms=None, category=None) -> list:
    """按当日证候和类别锚词检索候选条文。"""
    from src.scoring import score_indicators
    from src.textnorm import display_text
    if anchor_terms is None:
        anchor_terms = ["忌口", "适宜", "食疗", "煎服", "温覆"]
    evidence_terms = []
    for dim in DIMENSIONS:
        obs = rec.get_observation(dim)
        if not dim.is_covered(obs) or records_store._is_declared_normal(obs):
            continue
        for ind, v in score_indicators(dim, obs).items():
            if v >= 4 and obs.get(ind):
                evidence_terms.append(obs[ind])
    for k in rec.get_triggered_danger_flags():
        evidence_terms.append(records_store.DANGER_FLAGS.get(k, {}).get("name", k))

    from src.retrieval import retrieve
    hits = {}
    total_chars = 0

    def collect(terms, limit):
        nonlocal total_chars
        for term in terms:
            if len(hits) >= limit or total_chars >= MAX_KB_TOTAL_CHARS:
                return
            r = retrieve(term, context_lines=1, kb_root=kb_root)
            added = 0
            for h in r.get("results", []):
                if len(hits) >= limit or added >= 2 \
                        or total_chars >= MAX_KB_TOTAL_CHARS:
                    break
                fkey = (h["file"].replace("\\", "/"), h["line"])
                if fkey in hits:
                    continue
                excerpt = display_text(h["content"], MAX_KB_EXCERPT_CHARS)
                if not excerpt:
                    continue
                excerpt = excerpt[:MAX_KB_TOTAL_CHARS - total_chars]
                hits[fkey] = {"file": display_text(fkey[0], 240), "line": h["line"],
                              "excerpt": excerpt, "term": display_text(term, 128)}
                if category:
                    hits[fkey]["category"] = category
                total_chars += len(excerpt)
                added += 1

    collect(evidence_terms, max_hits // 2)
    collect(anchor_terms, max_hits)
    return list(hits.values())[:max_hits]


def _category_for_file(filename):
    first = filename.replace("\\", "/").split("/", 1)[0]
    for category, directory in (("constitution", "diagnostics"),
                                ("diet", "diet-lifestyle"), ("formula", "formulas")):
        if first == directory:
            return category
    return None


def _kb_references_unified(rec, kb_roots: dict, anchor_terms=None) -> list:
    """按当前可用类别形成统一检索视图，保留全局候选预算与类别溯源。"""
    from pathlib import Path
    import shutil
    import tempfile
    from src.retrieval import KB_CATEGORY_DEFS
    from src.retrieval.synonym_loader import (
        MAX_SYNONYM_KEYS, MAX_SYNONYMS_PER_KEY, load_map,
    )

    active = {category: kb_roots.get(category) for category in KB_CATEGORY_DEFS
              if kb_roots.get(category)}
    if not active:
        return []
    distinct_roots = list(dict.fromkeys(active.values()))
    shared = {root for root in distinct_roots
              if list(active.values()).count(root) > 1}

    def shared_category(relative):
        category = _category_for_file(relative)
        if category is None:
            if len(active) < len(KB_CATEGORY_DEFS):
                raise ValueError(f"共享综合知识库文件无法确定类别: {relative}；"
                                 "缺类时请按 diagnostics/、diet-lifestyle/、formulas/ 分类"
                                 "或改用分类专用根")
            return "composite"
        return category

    if len(active) == len(KB_CATEGORY_DEFS) and len(distinct_roots) == 1:
        root = distinct_roots[0]
        refs = _kb_references(rec, kb_root=root, anchor_terms=anchor_terms)
        for ref in refs:
            ref["category"] = shared_category(ref["file"])
        return refs

    with tempfile.TemporaryDirectory(prefix="kb-unified-") as view:
        view = Path(view)
        owners = {}
        merged_map = {}
        ordered_roots = sorted(distinct_roots,
                               key=lambda root: (root not in shared,
                                                 distinct_roots.index(root)))
        for root in ordered_roots:
            root_path = Path(root)
            for source in root_path.rglob("*"):
                if not source.is_file() or source.suffix.lower() != ".md" \
                        or source.name.lower() == "readme.md":
                    continue
                relative = source.relative_to(root_path).as_posix()
                if root in shared:
                    owner = shared_category(relative)
                    if owner != "composite" and active.get(owner) != root:
                        continue
                else:
                    owner = next(category for category, value in active.items()
                                 if value == root)
                target = view / relative
                if target.exists() and target.read_bytes() != source.read_bytes():
                    raise ValueError(f"重复且内容冲突的知识库文件: {relative}")
                if not target.exists():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, target)
                owners[relative] = owner
            map_path = root_path / "synonym_map.yaml"
            if map_path.is_file():
                for key, values in load_map(str(map_path)).items():
                    aliases = merged_map.setdefault(key, [])
                    for value in values:
                        if value not in aliases:
                            aliases.append(value)
        if len(merged_map) > MAX_SYNONYM_KEYS or any(
                len(values) > MAX_SYNONYMS_PER_KEY for values in merged_map.values()):
            raise ValueError("统一别名词典超过现有键或别名数量上限")
        if merged_map:
            with (view / "synonym_map.yaml").open("w", encoding="utf-8") as handle:
                for key, values in merged_map.items():
                    handle.write(f"{key}:\n")
                    for value in values:
                        handle.write(f"  - {value}\n")
        refs = _kb_references(rec, kb_root=str(view), anchor_terms=anchor_terms)
        for ref in refs:
            category = owners.get(ref["file"])
            if category is None:
                raise ValueError(f"统一知识库候选缺少类别溯源: {ref['file']}")
            ref["category"] = category
        return refs
