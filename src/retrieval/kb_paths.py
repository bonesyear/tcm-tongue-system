"""知识库路径的唯一归一化入口；仅使用标准库。"""
from __future__ import annotations

import os


_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def resolve_kb_root(kb_root: str | None = None) -> str:
    raw = kb_root or os.environ.get("TCM_KB_ROOT") or "knowledge_base"
    if not os.path.isabs(raw):
        raw = os.path.join(_REPO_ROOT, raw)
    return os.path.abspath(raw)


def kb_map_path(kb_root: str | None = None) -> str:
    return os.path.join(resolve_kb_root(kb_root), "synonym_map.yaml")
