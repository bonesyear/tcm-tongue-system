"""危险信号兼容接口；规则与三态求值由 src.alerts 提供。"""
from .alerts import (
    ALERT_RULESET_VERSION,
    DANGER_FLAGS,
    DANGER_PATTERNS,
    DANGER_PROVENANCE,
    alert_evaluation_map,
    danger_flags_for,
    evaluate_alert,
    evaluate_alerts,
    _leaf_texts,
)


def detect_danger(observations) -> list:
    """返回有阳性证据的规则键；筛查与组合规则都需人工复核。"""
    return [rule_id for rule_id, result in evaluate_alerts(observations).items()
            if result.state == "triggered"]
