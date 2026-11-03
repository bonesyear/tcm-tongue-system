"""医学治理清单与真实标定报告的结构约束。"""
import copy
import json
import os
import subprocess
import sys
import tempfile

from src.governance import (
    build_decision_inventory, validate_calibration_report, validate_decision_table,
)
from src.scoring import DIMENSION_RULES


def _report():
    return {
        "authorization": "explicit_user",
        "dataset_kind": "deidentified",
        "dataset_version": "schema-only-v1",
        "model": "example-vision-v1",
        "model_config": {
            "base_url": "https://example.invalid", "temperature": 0.6,
            "max_tokens": 600, "timeout": 60,
        },
        "reference_conclusion": "医学人员人工复核（仅结构示例）",
        "coverage": ["normal", "abnormal", "borderline", "lighting", "pose", "staining"],
        "total_cases": 6,
        "runs_per_image": 2,
        "metrics": {"true_positive": 4, "false_positive": 1, "false_negative": 1, "unknown": 0},
        "rates": {"false_positive_rate": 1 / 6, "false_negative_rate": 1 / 6, "unknown_rate": 0},
        "vocabulary": {"total": 12, "in_domain": 12},
        "field_metrics": {
            key: {"total": 2, "consistent": 2, "in_domain": 2,
                  "false_positive": 0, "false_negative": 0, "unknown": 0}
            for key in ("daiyang", "jaundice", "tooth_marks", "coating_greasy",
                        "sublingual", "critical_signs")
        },
    }


def _entry():
    entry = copy.deepcopy(build_decision_inventory()[0])
    entry.update(status="approved", approved_by="医学人员（结构示例）",
                 calibration=_report())
    return entry


def test_inventory_covers_all_scoring_rules_and_governance_topics_without_changing_rules():
    before = copy.deepcopy(DIMENSION_RULES)
    entries = build_decision_inventory()
    assert len(entries) == len({entry["id"] for entry in entries})
    expected = {
        f"{dim.english_name}.{indicator}.{keyword}": value
        for dim, indicators in DIMENSION_RULES.items()
        for indicator, rules in indicators.items()
        for keyword, value in rules.items()
    }
    for entry in entries:
        assert entry["status"] == "pending"
        assert entry["migration"] == "keep_current"
        assert entry["proposed_value"] is None
        assert entry["approved_by"] is None
        assert entry["calibration"] is None
        assert entry["reason"] and entry["evidence_refs"]
        if entry["id"] in expected:
            assert entry["current_value"] == expected[entry["id"]]
    assert {entry["id"] for entry in entries} >= {
        "tongue.sublingual_color.baseline", "tongue.body.color.five_levels",
        "collapse_yang.yin_yang_classification", "acute_jaundice.intercept_level",
        "tongue_critical.retention", "clinical_total.retention", "confidence.dose_gate",
    }
    assert validate_decision_table(entries) == []
    assert DIMENSION_RULES == before


def test_approval_requires_human_signoff_and_calibration():
    entry = _entry()
    entry["approved_by"] = "Kimi"
    assert validate_decision_table([entry], require_complete=False)
    entry["approved_by"] = "医学人员（结构示例）"
    entry["calibration"] = None
    assert validate_decision_table([entry], require_complete=False)
    entry["calibration"] = _report()
    assert validate_decision_table([entry], require_complete=False) == []


def test_changed_weight_requires_explicit_migration():
    entry = _entry()
    entry["proposed_value"] = 0 if entry["current_value"] else 1
    entry["migration"] = "keep_current"
    assert validate_decision_table([entry], require_complete=False)
    entry["migration"] = "migrate"
    assert validate_decision_table([entry], require_complete=False) == []


def test_categorical_topics_accept_structural_values_without_medical_decision():
    entry = next(entry for entry in build_decision_inventory()
                 if entry["id"] == "collapse_yang.yin_yang_classification")
    entry.update(status="approved", approved_by="医学人员（结构示例）",
                 calibration=_report(), migration="migrate",
                 proposed_value="仅校验类别结构（未作医学裁决）")
    assert validate_decision_table([entry], require_complete=False) == []
    entry["proposed_value"] = 3
    assert validate_decision_table([entry], require_complete=False)
    entry["proposed_value"] = ""
    assert validate_decision_table([entry], require_complete=False)


def test_calibration_cannot_be_mocked_or_omit_failure_metrics():
    report = _report()
    report["dataset_kind"] = "synthetic"
    assert validate_calibration_report(report)
    report = _report()
    report["model"] = "mock-vision"
    assert validate_calibration_report(report)
    report = _report()
    report["authorization"] = ""
    assert validate_calibration_report(report)
    report = _report()
    report["api_key"] = "not-a-real-key"
    assert validate_calibration_report(report)
    report = _report()
    del report["metrics"]["false_negative"]
    assert validate_calibration_report(report)
    report = _report()
    del report["rates"]
    assert validate_calibration_report(report)
    report = _report()
    report["coverage"].remove("borderline")
    assert validate_calibration_report(report)
    report = _report()
    del report["field_metrics"]["sublingual"]
    assert validate_calibration_report(report)
    report = _report()
    report["total_cases"] = 5
    assert validate_calibration_report(report)


def test_validation_handles_human_names_and_bad_containers():
    entry = _entry()
    entry["approved_by"] = "Aiden"
    assert validate_decision_table([entry], require_complete=False) == []
    report = _report()
    report["coverage"] = [{"not": "a string"}]
    assert validate_calibration_report(report)
    report = _report()
    report["model_config"] = None
    assert validate_calibration_report(report)
    bad_id = _entry()
    bad_id["id"] = ["not-a-string"]
    assert validate_decision_table([bad_id], require_complete=False)


def test_governance_inventory_cli_writes_pending_table_and_checks_it():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with tempfile.TemporaryDirectory(dir=root) as tmp:
        target = os.path.join(tmp, "decisions.json")
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        command = [sys.executable, os.path.join(root, "scripts", "governance_inventory.py"),
                   "--output", target]
        result = subprocess.run(command, cwd=root, env=env, capture_output=True, timeout=60)
        assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
        with open(target, encoding="utf-8") as f:
            payload = json.load(f)
        assert payload["schema_version"] == 1
        assert len(payload["entries"]) == len(build_decision_inventory())
        assert all(entry["status"] == "pending" for entry in payload["entries"])
        check = subprocess.run(command + ["--check"], cwd=root, env=env,
                               capture_output=True, timeout=60)
        assert check.returncode == 0, check.stderr.decode("utf-8", "replace")
