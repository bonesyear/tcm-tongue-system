"""短文本的证据状态：匹配、否定、排除语境与未出现。"""
from __future__ import annotations

from dataclasses import dataclass
import re

from .textnorm import mask_non_negations


@dataclass(frozen=True)
class TermMatch:
    text: str
    term: str
    start: int
    end: int
    state: str
    reason: str = ""


_BOUNDARY_RE = re.compile(r"[，。；,;]|但是|但|然而|却|而")
_NEGATION_RE = re.compile(r"并非|绝非|排除|无|未|没|不")
_POST_NEGATION_RE = re.compile(
    r"不明显|不显著|不突出|不著|未见|阴性|已排除|排除|不存在|已除外|除外"
)
_COMPARISON_RE = re.compile(r"(?:需|须|应|宜|要)与[^，。；]{0,8}$")
_COMPARISON_END_RE = re.compile(r"(?:等.{0,4})?(?:相)?(?:鉴别|区分|辨别|甄别)")


def _clause_start(text: str, end: int) -> int:
    start = 0
    for boundary in _BOUNDARY_RE.finditer(text, 0, end):
        start = boundary.end()
    return start


def _negation_reason(text: str, start: int, end: int) -> str:
    before = mask_non_negations(text[_clause_start(text, start):start][-12:])
    match = _NEGATION_RE.search(before)
    if match:
        return f"前置否定：{match.group()}"
    after = text[end:end + 8]
    match = _POST_NEGATION_RE.match(after)
    if match:
        return f"后置否定：{match.group()}"
    return ""


def _exclusion_reason(text: str, term: str, start: int, end: int) -> str:
    if term == "镜面" and text[end:end + 2] in ("反光", "反射"):
        return "光学反光/反射，不是舌象描述"
    before = text[_clause_start(text, start):start]
    after = text[end:end + 12]
    if _COMPARISON_RE.search(before) and _COMPARISON_END_RE.match(after):
        return "鉴别比较语境，不是患者阳性证据"
    return ""


def find_term(text: str, term: str) -> TermMatch:
    """返回首个肯定匹配；无肯定匹配时保留首个否定/排除语境。"""
    if not isinstance(text, str) or not isinstance(term, str) or not term:
        return TermMatch(str(text), str(term), -1, -1, "missing")
    from .textnorm import normalize_text
    text, term = normalize_text(text), normalize_text(term)
    fallback = None
    start = text.find(term)
    while start >= 0:
        end = start + len(term)
        reason = _exclusion_reason(text, term, start, end)
        state = "excluded" if reason else ""
        if not reason:
            reason = _negation_reason(text, start, end)
            state = "negated" if reason else "matched"
        match = TermMatch(text, term, start, end, state, reason)
        if state == "matched":
            return match
        if fallback is None:
            fallback = match
        start = text.find(term, start + 1)
    return fallback or TermMatch(text, term, -1, -1, "missing")
