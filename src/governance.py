"""医学治理清单与标定证据校验；不自动修改医学规则。"""
from __future__ import annotations

from .alerts import DANGER_PROVENANCE
from .dimensions import VisionDimension
from .indicators import INDICATOR_REGISTRY
from .scoring import DIMENSION_RULES


def _spec_refs(dim, key):
    spec = INDICATOR_REGISTRY.for_field(dim, key)
    return [{"source_id": ref.source_id, "source_sha256": ref.sha256,
             "keyword": ref.keyword, "locator": ref.locator}
            for ref in spec.source_refs]


def _danger_refs(key):
    return [dict(ref) for ref in DANGER_PROVENANCE[key]]


def _experience_ref(keyword, locator):
    return [{"source_id": "experience", "source_sha256": "",
             "keyword": keyword, "locator": locator}]


def _topic(indicator_id, current_value, reason, refs):
    return {
        "id": indicator_id,
        "dimension": indicator_id.split(".", 1)[0],
        "indicator": indicator_id.split(".", 1)[1],
        "current_value": current_value,
        "proposed_value": None,
        "reason": reason,
        "evidence_refs": refs,
        "approved_by": None,
        "migration": "keep_current",
        "status": "pending",
        "calibration": None,
    }


def build_decision_inventory() -> list[dict]:
    entries = []
    for dim, indicators in DIMENSION_RULES.items():
        for indicator, rules in indicators.items():
            for keyword, value in rules.items():
                entries.append(_topic(
                    f"{dim.english_name}.{indicator}.{keyword}", value,
                    "待主人/医学人员裁决：原著不能单独证明固定分值",
                    _spec_refs(dim, indicator),
                ))
    entries.extend([
        _topic("tongue.sublingual_color.baseline", "淡紫/<2mm",
               "教材暗红/2.7mm 与现有淡紫/<2mm 口径须分别裁决，不伪称同一基线",
               _spec_refs(VisionDimension.TONGUE, "sublingual_color")),
        _topic("tongue.body.color.five_levels", "五档",
               "五档的信息损失与可接受替代待裁决；不恢复未经签认的九档",
               _spec_refs(VisionDimension.TONGUE, "body_color")),
        _topic("collapse_yang.yin_yang_classification", "脱阳前兆（未重分类）",
               "绝汗亡阴/亡阳分类待医学签认，本清单不先行改类",
               _danger_refs("collapse_yang")),
        _topic("acute_jaundice.intercept_level", "screening/critical_rule",
               "急性黄疸拦截级别须结合语境和真实证据，不能仅由颜色决定",
               _danger_refs("acute_jaundice")),
        _topic("tongue_critical.retention", "苔焦黑干燥＋舌质干裂起刺",
               "该组合的存废与拦截边界待签认，不继续沿用紫暗必需条件",
               _danger_refs("tongue_critical")),
        _topic("clinical_total.retention", "六维启发式汇总",
               "总分缺少原著量化依据；去留及历史重算策略待裁决，不当作疾病严重度",
               _experience_ref("临床总分", "docs/AUDIT_2026-10-26_bottom-up-model.md §M9")),
        _topic("confidence.dose_gate", "covered >= 4 → allows_dosage",
               "覆盖维度不能单独授权具体剂量；须独立安全策略和医学签认",
               _experience_ref("覆盖四维给剂量", "docs/AUDIT_2026-10-26_bottom-up-model.md §M2")),
    ])
    return entries


def _human_signoff(value) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    lowered = value.strip().lower()
    return lowered not in {
        "kimi", "codex", "gpt", "claude", "qwen", "assistant", "openai",
        "ai", "chatgpt", "gemini", "deepseek",
    }


def validate_decision_table(entries, require_complete=True) -> list[str]:
    errors = []
    expected = {entry["id"]: entry["current_value"]
                for entry in build_decision_inventory()}
    seen = set()
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("id"), str) \
                or not entry["id"].strip():
            errors.append("裁决项缺少有效字符串 id")
            continue
        indicator_id = entry["id"]
        if indicator_id in seen:
            errors.append(f"{indicator_id}: 裁决项 id 重复")
        seen.add(indicator_id)
        if indicator_id not in expected:
            errors.append(f"{indicator_id}: 不在当前医学规则清单中")
            continue
        if entry.get("current_value") != expected[indicator_id]:
            errors.append(f"{indicator_id}: current_value 与当前实现不一致")
        if not entry.get("reason"):
            errors.append(f"{indicator_id}: 缺少裁决理由")
        refs = entry.get("evidence_refs")
        if not isinstance(refs, list) or not refs:
            errors.append(f"{indicator_id}: 缺少出处")
        else:
            for ref in refs:
                if not isinstance(ref, dict) or not ref.get("source_id") \
                        or not ref.get("keyword") or not ref.get("locator"):
                    errors.append(f"{indicator_id}: 出处字段不完整")
                elif ref["source_id"] != "experience" and not ref.get("source_sha256"):
                    errors.append(f"{indicator_id}: 书籍出处缺文件哈希")
        status = entry.get("status", "pending")
        if status not in ("pending", "approved"):
            errors.append(f"{indicator_id}: 未知裁决状态 {status}")
            continue
        migration = entry.get("migration")
        if migration not in ("keep_current", "migrate", "retire"):
            errors.append(f"{indicator_id}: 未知迁移方式 {migration}")
        if status == "pending":
            continue
        if not _human_signoff(entry.get("approved_by")):
            errors.append(f"{indicator_id}: 需要主人或医学人员签认，不能由 AI 签认")
        proposed = entry.get("proposed_value")
        if migration == "keep_current" and proposed is not None \
                and proposed != expected[indicator_id]:
            errors.append(f"{indicator_id}: keep_current 与 proposed_value 矛盾")
        if migration == "migrate":
            current = expected[indicator_id]
            if isinstance(current, (int, float)) and not isinstance(current, bool):
                if isinstance(proposed, bool) \
                        or not isinstance(proposed, (int, float)) \
                        or not 0 <= proposed <= 10:
                    errors.append(f"{indicator_id}: 评分变更值必须是 0–10 数值")
            elif not isinstance(proposed, str) or not proposed.strip():
                errors.append(f"{indicator_id}: 类别变更值必须是非空字符串")
        if migration == "retire" and proposed is not None:
            errors.append(f"{indicator_id}: retire 不应同时指定新值")
        calibration = entry.get("calibration")
        if not isinstance(calibration, dict):
            errors.append(f"{indicator_id}: 批准前缺真实标定报告")
        else:
            errors.extend(f"{indicator_id}: {error}"
                          for error in validate_calibration_report(calibration))
    if require_complete:
        missing = sorted(set(expected) - seen)
        if missing:
            errors.append("裁决清单缺当前规则: " + "、".join(missing))
    return errors


def _nonnegative_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _ratio(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= value <= 1


def validate_calibration_report(report) -> list[str]:
    if not isinstance(report, dict):
        return ["标定报告必须为对象"]
    errors = []
    for key in ("authorization", "dataset_kind", "dataset_version", "model", "reference_conclusion"):
        if not isinstance(report.get(key), str) or not report[key].strip():
            errors.append(f"标定报告缺少 {key}")
    if report.get("authorization") != "explicit_user":
        errors.append("真实标定需要主人明确授权")
    if report.get("dataset_kind") != "deidentified":
        errors.append("标定集必须使用经授权的脱敏照片，不能用模拟数据代替")
    if "mock" in str(report.get("model", "")).lower() \
            or "fake" in str(report.get("model", "")).lower() \
            or "dummy" in str(report.get("model", "")).lower():
        errors.append("mock/fake 模型不能作为真实标定证据")
    config = report.get("model_config")
    if "api_key" in report or (isinstance(config, dict) and "api_key" in config):
        errors.append("标定报告不得包含 API Key")

    if not isinstance(config, dict) or not config.get("base_url"):
        errors.append("缺模型端点配置")
    elif not isinstance(config["base_url"], str):
        errors.append("模型端点必须为字符串")
    if not isinstance(config, dict) or not _ratio(config.get("temperature")):
        errors.append("temperature 必须为 0–1 数值")
    if not isinstance(config, dict) or not _nonnegative_int(config.get("max_tokens")) \
            or config["max_tokens"] <= 0:
        errors.append("max_tokens 必须为正整数")
    if not isinstance(config, dict) or not _nonnegative_int(config.get("timeout")) \
            or config["timeout"] <= 0:
        errors.append("timeout 必须为正整数")

    required_coverage = {"normal", "abnormal", "borderline", "lighting", "pose", "staining"}
    coverage = report.get("coverage")
    if not isinstance(coverage, list) \
            or not all(isinstance(item, str) for item in coverage) \
            or not required_coverage.issubset(coverage):
        errors.append("标定集须覆盖正常、异常、边界、光线、拍姿与染色差异")
    total = report.get("total_cases")
    if not _nonnegative_int(total) or total <= 0:
        errors.append("total_cases 必须为正整数")
        total = 0
    if not _nonnegative_int(report.get("runs_per_image")) or report["runs_per_image"] < 2:
        errors.append("同一图片至少需要重复识图两次")

    metrics = report.get("metrics")
    if not isinstance(metrics, dict):
        errors.append("缺整体混淆矩阵")
        metrics = {}
    counts = {}
    for key in ("true_positive", "false_positive", "false_negative", "unknown"):
        value = metrics.get(key)
        if not _nonnegative_int(value):
            errors.append(f"metrics.{key} 必须为非负整数（可为 0）")
            value = 0
        counts[key] = value
    if total and sum(counts.values()) != total:
        errors.append("total_cases 与混淆矩阵总数不一致")

    rates = report.get("rates")
    if not isinstance(rates, dict):
        errors.append("缺误报率、漏报率和未知率")
        rates = {}
    if total:
        expected_rates = {
            "false_positive_rate": counts["false_positive"] / total,
            "false_negative_rate": counts["false_negative"] / total,
            "unknown_rate": counts["unknown"] / total,
        }
        for key, expected in expected_rates.items():
            value = rates.get(key)
            if not _ratio(value):
                errors.append(f"rates.{key} 必须为 0–1 数值（可为 0）")
            elif abs(value - expected) > 1e-9:
                errors.append(f"rates.{key} 与混淆矩阵不一致")

    required_fields = {"daiyang", "jaundice", "tooth_marks", "coating_greasy",
                       "sublingual", "critical_signs"}
    field_metrics = report.get("field_metrics")
    if not isinstance(field_metrics, dict):
        errors.append("缺字段级标定指标")
        field_metrics = {}
    for field in sorted(required_fields):
        metrics = field_metrics.get(field)
        if not isinstance(metrics, dict):
            errors.append(f"缺字段 {field} 的标定指标")
            continue
        total_field = metrics.get("total")
        if not _nonnegative_int(total_field) or total_field <= 0:
            errors.append(f"字段 {field}.total 必须为正整数")
            continue
        for key in ("consistent", "in_domain", "false_positive", "false_negative", "unknown"):
            value = metrics.get(key)
            if not _nonnegative_int(value) or value > total_field:
                errors.append(f"字段 {field}.{key} 超出有效范围")
        if (metrics.get("consistent", 0) + metrics.get("false_positive", 0)
                + metrics.get("false_negative", 0) + metrics.get("unknown", 0) != total_field):
            errors.append(f"字段 {field} 的评价总数不一致")

    vocabulary = report.get("vocabulary")
    if not isinstance(vocabulary, dict) or not _nonnegative_int(vocabulary.get("total")) \
            or vocabulary["total"] <= 0:
        errors.append("缺规范词落域总数")
    elif not _nonnegative_int(vocabulary.get("in_domain")) \
            or vocabulary["in_domain"] > vocabulary["total"]:
        errors.append("规范词落域数不能超过评价总数")
    return errors
