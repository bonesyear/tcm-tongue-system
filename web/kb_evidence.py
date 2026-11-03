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
