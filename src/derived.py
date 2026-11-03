"""派生数据的输入指纹、评分规则与生成器版本。"""
from __future__ import annotations

import datetime
import hashlib
import json

from .dimensions import DIMENSIONS
from .scoring import SCORING_RULESET_VERSION


DERIVED_GENERATOR_VERSION = "2026-10-27.b07.1"


def observation_input_hash(rec) -> str:
    """对观察、采集元数据、声明、上下文与红线审计生成稳定 SHA256。"""
    payload = {
        "observations": {
            dim.english_name: rec.get_observation(dim) for dim in DIMENSIONS
        },
        "observation_meta": rec.raw.get("observation_meta", {}),
        "declarations": rec.raw.get("declarations", []),
        "schema_version": rec.raw.get("schema_version"),
        "inquiry": rec.raw.get("inquiry", {}),
        "context": rec.raw.get("context", {}),
    }
    if "danger_review" in rec.raw:
        payload["danger_review"] = rec.raw["danger_review"]
    if "photos" in rec.raw:
        payload["photos"] = rec.raw["photos"]
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def current_derived_meta(rec) -> dict:
    """新写入或重新生成时使用的派生元数据；读取旧记录不调用此函数。"""
    return {
        "input_hash": observation_input_hash(rec),
        "scoring_ruleset_version": SCORING_RULESET_VERSION,
        "generator_version": DERIVED_GENERATOR_VERSION,
        "updated_at": datetime.datetime.now().isoformat(timespec="seconds"),
    }
