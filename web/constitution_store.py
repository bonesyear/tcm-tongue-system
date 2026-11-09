"""国标体质评估的版本化记录、草稿完成校验与过期判断。"""
from __future__ import annotations

import hashlib
import json

import time_utils
from src.constitution_assessment import (
    QUESTIONNAIRE_VERSION, RULE_BY_ID, RULE_ENTRIES, STANDARD_ID, evaluate_constitution,
)


def _json_safe(value):
    from fractions import Fraction
    if isinstance(value, Fraction):
        return str(value)
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def _input_hash(status, gender, answers, unanswered):
    payload = {"standard_id": STANDARD_ID, "questionnaire_version": QUESTIONNAIRE_VERSION,
               "status": status, "gender": gender, "answers": answers,
               "unanswered": sorted(unanswered)}
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _version_error(data):
    if data.get("schema_version") != 1:
        return f"schema_version 不支持: {data.get('schema_version')!r}"
    if data.get("standard_id") != STANDARD_ID:
        return f"standard_id 不支持: {data.get('standard_id')!r}"
    if data.get("questionnaire_version") != QUESTIONNAIRE_VERSION:
        return f"questionnaire_version 不支持: {data.get('questionnaire_version')!r}"
    return None


def _unanswered(values, answers):
    if not isinstance(values, (list, tuple)):
        raise TypeError("无法回答项必须是题号列表")
    if len(set(values)) != len(values):
        raise ValueError("无法回答项不能重复")
    for entry_id in values:
        if not isinstance(entry_id, str) or entry_id not in {entry.entry_id for entry in RULE_ENTRIES}:
            raise ValueError(f"未知无法回答题号: {entry_id!r}")
        if entry_id in answers:
            raise ValueError(f"无法回答与作答不能并存: {entry_id}")
    return sorted(values)


def build_assessment(answers, gender, unanswered=(), skipped=False, final=False,
                     timezone_name=None):
    if skipped:
        answers = {}
        unanswered = []
        evaluation = evaluate_constitution({}, None, skipped=True)
        status = "skipped"
        gender = None
    else:
        evaluation = evaluate_constitution(answers, gender)
        answers = evaluation["answers"]
        unanswered = _unanswered(unanswered, answers)
        status = "completed" if final else "draft"
    if final and not skipped:
        applicable = {entry.entry_id for entry in RULE_ENTRIES
                      if not (entry.gender_condition == "female_only" and gender != "female"
                              or entry.gender_condition == "male_only" and gender != "male")}
        missing = sorted(entry_id for entry_id in applicable
                         if entry_id not in answers and entry_id not in unanswered)
        if missing:
            raise ValueError(f"未完成体质评估：{', '.join(missing)}")
    return {
        "schema_version": 1,
        "standard_id": STANDARD_ID,
        "questionnaire_version": QUESTIONNAIRE_VERSION,
        "status": status,
        "gender": gender,
        "answers": answers,
        "unanswered": unanswered,
        "evaluation": _json_safe(evaluation),
        "input_hash": _input_hash(status, gender, answers, unanswered),
        "updated_at": time_utils.iso_now(timezone_name),
    }


def finalize_assessment(draft, timezone_name=None):
    data = draft.get("constitution_assessment")
    if data is None:
        return None
    if not isinstance(data, dict):
        raise ValueError("体质评估草稿不是对象")
    if data.get("status") == "skipped":
        return build_assessment({}, None, skipped=True, final=True)
    if data.get("status") not in {"draft", "completed"}:
        raise ValueError("体质评估草稿状态无效")
    return build_assessment(data.get("answers", {}), data.get("gender"),
                            data.get("unanswered", []), final=True,
                            timezone_name=timezone_name)


def assessment_view(raw):
    data = raw.get("constitution_assessment")
    if data is None:
        return {"status": "unassessed", "stale": False, "reasons": []}
    if not isinstance(data, dict):
        return {"status": "error", "stale": True, "reasons": ["体质评估结构不是对象"]}
    version_error = _version_error(data)
    if version_error:
        return {"status": "error", "stale": True, "reasons": [version_error]}
    status = data.get("status")
    if status not in {"completed", "skipped"}:
        return {"status": "error", "stale": True,
                "reasons": ["体质评估不是正式完成状态"]}
    try:
        expected = build_assessment(data.get("answers", {}), data.get("gender"),
                                    data.get("unanswered", []), skipped=status == "skipped",
                                    final=True)
    except (TypeError, ValueError) as error:
        return {"status": "error", "stale": True, "reasons": [str(error)]}
    reasons = []
    if data.get("input_hash") != expected["input_hash"]:
        reasons.append("体质评估输入已变化")
    if data.get("evaluation") != expected["evaluation"]:
        reasons.append("体质评估结果或版本已变化")
    if reasons:
        return {"status": "error", "stale": True, "reasons": reasons}
    return {"status": status, "stale": False, "reasons": [], "assessment": data}


def validate_assessment(raw):
    view = assessment_view(raw)
    return view["reasons"] if view["status"] == "error" else []


def validate_draft_assessment(data):
    if not isinstance(data, dict):
        raise ValueError("体质评估草稿不是对象")
    version_error = _version_error(data)
    if version_error:
        raise ValueError(version_error)
    status = data.get("status")
    if status not in {"draft", "completed", "skipped"}:
        raise ValueError("体质评估草稿状态无效")
    if not isinstance(data.get("answers"), dict):
        raise ValueError("体质评估答案不是对象")
    if not isinstance(data.get("unanswered"), list):
        raise ValueError("体质评估无法回答项不是列表")
    expected = build_assessment(data["answers"], data.get("gender"),
                                data["unanswered"], skipped=status == "skipped",
                                final=status == "completed")
    if data.get("input_hash") != expected["input_hash"]:
        raise ValueError("体质评估草稿输入指纹不一致")
    if data.get("evaluation") != expected["evaluation"]:
        raise ValueError("体质评估草稿结果不一致")
