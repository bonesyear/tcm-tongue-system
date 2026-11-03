"""红线证据快照、确认令牌与裁决审计；不依赖 Web 框架。"""
from __future__ import annotations

import datetime
import hashlib
import hmac
import json

from .alerts import ALERT_RULESET_VERSION, evaluate_alerts
from .record import DailyRecord


DECISIONS = frozenset({"keep", "dismiss", "clear"})


class DangerReviewConflict(ValueError):
    pass


def _digest(value) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _evidence(evaluation: dict) -> list[dict]:
    return [{"path": item.get("source", ""), "value": item.get("text", "")}
            for item in evaluation.get("evidence", [])
            if isinstance(item, dict) and item.get("state") == "matched"]


def _history(raw: dict) -> list[dict]:
    history = raw.get("danger_review", [])
    return [dict(item) for item in history if isinstance(item, dict)] \
        if isinstance(history, list) else []


def _latest(raw: dict) -> dict:
    return {item.get("key"): item for item in _history(raw)
            if isinstance(item.get("key"), str)}


def _stored_auto(raw: dict) -> dict:
    flags = raw.get("danger_flags", {})
    evaluations = flags.get("evaluations", []) if isinstance(flags, dict) else []
    result = {}
    if isinstance(evaluations, list):
        for evaluation in evaluations:
            if not isinstance(evaluation, dict):
                continue
            key = evaluation.get("rule_id")
            evidence = _evidence(evaluation)
            if isinstance(key, str) and evaluation.get("state") == "triggered" and evidence:
                result[key] = evidence
    for key, review in _latest(raw).items():
        evidence = review.get("evidence")
        if review.get("decision") in DECISIONS and isinstance(evidence, list) and evidence:
            result[key] = evidence
    return result


def _audit(decision: str, key: str, original: list[str], evidence: list[dict],
           source: str, client: str) -> dict:
    return {
        "decision": decision, "key": key,
        "original_triggered": sorted(original), "evidence": evidence,
        "evidence_hash": _digest(evidence), "source": source, "client": client,
        "at": datetime.datetime.now().isoformat(timespec="seconds"),
    }


def refresh_danger(raw: dict, previous_raw: dict | None = None,
                   source="correction", client="") -> dict:
    """重算自动项、保留外部项，并恢复证据匹配的既有裁决。"""
    before = previous_raw if previous_raw is not None else raw
    previous_flags = before.get("danger_flags", {})
    if isinstance(previous_flags, dict) and any(
            key in previous_flags for key in ("triggered", "not_triggered", "unknown", "dismissed", "evaluations")
    ) and any(isinstance(value, dict) for key, value in previous_flags.items()
              if key not in ("triggered", "not_triggered", "unknown", "dismissed", "evaluations")):
        raise ValueError("danger_flags 混合了 B 式状态列表与 A 式旗对象，结构不可信")
    previous_record = DailyRecord(before)
    original = set(previous_record.get_triggered_danger_flags())
    previous_evidence = _stored_auto(before)
    external = original - set(previous_evidence)
    evaluations = evaluate_alerts(raw)
    automatic = {key for key, result in evaluations.items() if result.state == "triggered"}
    evidence = {key: _evidence(result.to_dict()) for key, result in evaluations.items()}
    latest = _latest(raw)
    dismissed = {key for key in automatic
                 if latest.get(key, {}).get("decision") == "dismiss"
                 and latest[key].get("evidence_hash") == _digest(evidence[key])}
    previous_dismissed = previous_flags.get("dismissed", []) \
        if isinstance(previous_flags, dict) else []
    previous_dismissed = set(previous_dismissed) \
        if isinstance(previous_dismissed, list) else set()
    cleared = sorted(key for key in previous_evidence
                     if (key in original or key in previous_dismissed)
                     and key not in automatic
                     and _digest(previous_evidence[key]) != _digest(evidence.get(key, [])))
    triggered = sorted(external | (automatic - dismissed))
    history = _history(raw)
    for key in cleared:
        history.append(_audit("clear", key, sorted(original),
                              previous_evidence[key], source, client))
    raw["danger_review"] = history
    raw["danger_flags"] = {
        "triggered": triggered,
        "not_triggered": [key for key, result in evaluations.items()
                          if result.state == "not_triggered"
                          and key not in triggered and key not in dismissed],
        "unknown": [key for key, result in evaluations.items()
                    if result.state == "unknown"
                    and key not in triggered and key not in dismissed],
        "dismissed": sorted(dismissed),
        "evaluations": [result.to_dict() for result in evaluations.values()],
        "ruleset_version": ALERT_RULESET_VERSION,
    }
    revived = sorted(key for key in automatic if key in latest
                     and latest[key].get("evidence_hash") != _digest(evidence[key]))
    return {"cleared": cleared, "revived": revived}


def review_snapshot(raw: dict) -> dict:
    """读取已刷新的记录，返回当前证据、待确认键和绑定令牌。"""
    evaluations = evaluate_alerts(raw)
    evidence = {key: _evidence(result.to_dict()) for key, result in evaluations.items()}
    triggered = DailyRecord(raw).get_triggered_danger_flags()
    latest = _latest(raw)
    kept = [key for key in triggered
            if latest.get(key, {}).get("decision") == "keep"
            and latest[key].get("evidence_hash") == _digest(evidence.get(key, []))]
    pending = [key for key in triggered if key not in kept]
    flags = raw.get("danger_flags", {})
    dismissed = flags.get("dismissed", []) if isinstance(flags, dict) else []
    token = _digest({"triggered": sorted(triggered),
                     "evidence": {key: evidence.get(key, []) for key in triggered}})
    return {
        "triggered": triggered, "pending": pending, "kept": kept,
        "dismissed": dismissed if isinstance(dismissed, list) else [],
        "evidence": evidence, "token": token,
        "evaluations": {key: result.to_dict() for key, result in evaluations.items()},
    }


def merge_scope(snapshot: dict, dimensions: set[str], questions: dict) -> set[str]:
    """merge 中只允许处理本轮触及维度/问诊证据的误报裁决。"""
    allowed = set()
    for key in snapshot["pending"]:
        for item in snapshot["evidence"].get(key, []):
            path = item["path"]
            if path.split(".", 1)[0] in dimensions \
                    or any(path.startswith(f"text:{dim}") for dim in dimensions):
                allowed.add(key)
            if path.startswith("inquiry.") and any(
                    path == f"inquiry.{question}" or path.rstrip("？") == f"inquiry.{question}".rstrip("？")
                    for question in questions):
                allowed.add(key)
    return allowed


def apply_decision(raw: dict, token: str, decisions: dict,
                   scope: set[str] | None = None, source="wizard", client="") -> dict:
    snapshot = review_snapshot(raw)
    if not snapshot["pending"] or not isinstance(token, str) \
            or not hmac.compare_digest(token, snapshot["token"]):
        raise DangerReviewConflict("红线证据已变化，请重新确认")
    if not isinstance(decisions, dict) or set(decisions) != set(snapshot["pending"]):
        raise ValueError("必须逐项裁决本次展示的全部红线")
    if any(value not in ("keep", "dismiss") for value in decisions.values()):
        raise ValueError("红线裁决只能是 keep 或 dismiss")
    if scope is not None and any(value == "dismiss" and key not in scope
                                 for key, value in decisions.items()):
        raise ValueError("merge 不能判未触及的旧红线为误报")
    history = _history(raw)
    for key in snapshot["pending"]:
        history.append(_audit(decisions[key], key, snapshot["triggered"],
                              snapshot["evidence"].get(key, []), source, client))
    flags = raw["danger_flags"]
    dismissed = set(flags.get("dismissed", []))
    for key, decision in decisions.items():
        if decision == "dismiss":
            dismissed.add(key)
            flags["triggered"] = [item for item in flags["triggered"] if item != key]
        else:
            dismissed.discard(key)
            if key not in flags["triggered"]:
                flags["triggered"].append(key)
    flags["dismissed"] = sorted(dismissed)
    raw["danger_review"] = history
    return snapshot


def validate_history(history) -> list[str]:
    if not isinstance(history, list):
        return ["danger_review 应为列表"]
    errors = []
    for index, item in enumerate(history):
        if not isinstance(item, dict):
            errors.append(f"danger_review[{index}] 应为对象")
            continue
        if not isinstance(item.get("key"), str) or not item["key"].strip():
            errors.append(f"danger_review[{index}].key 应为非空字符串")
        if item.get("decision") not in DECISIONS:
            errors.append(f"danger_review[{index}].decision 非法")
        original = item.get("original_triggered")
        if not isinstance(original, list) or any(
                not isinstance(key, str) or not key.strip() for key in original):
            errors.append(f"danger_review[{index}].original_triggered 应为非空字符串列表")
        evidence = item.get("evidence")
        if not isinstance(evidence, list) or any(
                not isinstance(entry, dict)
                or not isinstance(entry.get("path"), str)
                or not isinstance(entry.get("value"), str) for entry in evidence):
            errors.append(f"danger_review[{index}].evidence 应为路径/文本对象列表")
        if not isinstance(item.get("evidence_hash"), str) or len(item["evidence_hash"]) != 64:
            errors.append(f"danger_review[{index}].evidence_hash 无效")
        if not isinstance(item.get("source"), str) or not item["source"].strip():
            errors.append(f"danger_review[{index}].source 应为非空字符串")
        if not isinstance(item.get("at"), str) or not item["at"].strip():
            errors.append(f"danger_review[{index}].at 应为非空字符串")
        if "client" in item and not isinstance(item["client"], str):
            errors.append(f"danger_review[{index}].client 应为字符串")
    return errors
