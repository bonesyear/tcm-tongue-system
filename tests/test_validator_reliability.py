"""批次 03 可靠性：input_validator 诊断性回归。

覆盖：
  - 形状 B danger_flags 携带附加元数据（字符串/数值键）不误报 error
  - confidence 不一致告警文案同时说清「声称值（解析等级）」与「覆盖推断等级」
  - Windows GBK 控制台打印 emoji 不崩（UnicodeEncodeError），stdout 与退出码语义不变
"""
import json
import os
import subprocess
import sys
import tempfile

import pytest

import input_validator as v

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RECORD_PATH = os.path.join(ROOT, "tests", "fixtures", "2026-06-25_analysis.json")


def _validate_raw(raw):
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                     encoding="utf-8") as f:
        json.dump(raw, f, ensure_ascii=False)
        path = f.name
    try:
        return v.validate_record(path)
    finally:
        os.remove(path)


def _shape_b_record():
    return {
        "date": "2026-01-01",
        "confidence": "MEDIUM",
        "observations": {"tongue": {"body": {"color": "淡红"}}},
        "danger_flags": {"triggered": [], "not_triggered": []},
    }


# ============================================================
# 形状 B danger_flags 附加元数据不误报
# ============================================================
class TestShapeBDangerMetadata:
    def test_extra_string_metadata_not_error(self):
        raw = _shape_b_record()
        df = raw["danger_flags"]
        df["source"] = "拍照向导"
        df["note"] = "用户确认无危重体征"
        _, errors, _ = _validate_raw(raw)
        assert errors == [], f"附加字符串元数据不应产生 error: {errors}"

    def test_extra_numeric_metadata_not_error(self):
        raw = _shape_b_record()
        raw["danger_flags"]["schema_version"] = 2
        _, errors, _ = _validate_raw(raw)
        assert errors == [], f"附加数值元数据不应产生 error: {errors}"

    def test_triggered_still_type_checked_with_metadata(self):
        # 元数据容忍不等于放松结构校验：triggered 类型错误仍必须报错
        raw = _shape_b_record()
        raw["danger_flags"]["triggered"] = "none"
        raw["danger_flags"]["source"] = "wizard"
        _, errors, _ = _validate_raw(raw)
        assert any("triggered" in e for e in errors)

    def test_b06_three_state_metadata_accepted(self):
        from src.alerts import danger_flags_for
        raw = _shape_b_record()
        raw["danger_flags"] = danger_flags_for(raw)
        _, errors, _ = _validate_raw(raw)
        assert errors == []

    def test_b06_unknown_and_evaluation_types_checked(self):
        raw = _shape_b_record()
        raw["danger_flags"]["unknown"] = "not-a-list"
        raw["danger_flags"]["evaluations"] = [
            {"rule_id": "daiyang", "state": "not_triggered", "kind": "screening"},
            {"rule_id": "acute_jaundice", "state": "sometimes", "kind": "critical_rule"},
        ]
        _, errors, _ = _validate_raw(raw)
        assert any("unknown" in e for e in errors)
        assert any("state" in e for e in errors)

    def test_shape_a_optional_unknown_state_and_invalid_state(self):
        raw = _shape_b_record()
        raw["danger_flags"] = {
            "daiyang": {"triggered": False, "finding": "", "state": "unknown"},
        }
        _, errors, _ = _validate_raw(raw)
        assert errors == []
        raw["danger_flags"]["daiyang"]["state"] = "not-sure"
        _, errors, _ = _validate_raw(raw)
        assert any("state" in e for e in errors)

    def test_b07_metadata_and_declaration_validation(self):
        raw = _shape_b_record()
        raw["schema_version"] = 2
        raw["observation_meta"] = {"tongue.body.color": {
            "source": "manual", "method": "photo", "raw": "淡红",
            "certainty": "user_confirmed", "evidence": {}, "value": "淡红",
        }}
        raw["declarations"] = [{"kind": "declared_normal", "dimension": "skin",
                                "part": "皮肤", "reason": "用户确认"}]
        _, errors, _ = _validate_raw(raw)
        assert errors == []

        bad_method = json.loads(json.dumps(raw))
        bad_method["observation_meta"] = {"tongue.body.dynamics": {
            "source": "vision", "method": "photo", "raw": "强硬",
            "certainty": "unverified", "evidence": {}, "value": "强硬",
        }}
        _, errors, _ = _validate_raw(bad_method)
        assert any("动态" in e or "视频" in e for e in errors)

        bad_declaration = json.loads(json.dumps(raw))
        bad_declaration["declarations"] = [{"kind": "skip-all", "dimension": "skin"}]
        _, errors, _ = _validate_raw(bad_declaration)
        assert any("声明" in e or "skip-all" in e for e in errors)

        bad_schema = json.loads(json.dumps(raw))
        bad_schema["schema_version"] = "2"
        _, errors, _ = _validate_raw(bad_schema)
        assert any("schema_version" in e for e in errors)

        bad_unknown = json.loads(json.dumps(raw))
        bad_unknown["observation_meta"] = {"eye.lower_lid_color": {
            "source": "vision", "method": "photo", "raw": "淡白",
            "certainty": "unknown", "evidence": {"exposed": False}, "value": "淡白",
        }}
        _, errors, _ = _validate_raw(bad_unknown)
        assert any("unknown" in e for e in errors)

    def test_shape_a_non_dict_flag_still_error(self):
        # 形状 A（无 triggered/not_triggered 键）的 flag 值非对象仍是 error
        raw = _shape_b_record()
        raw["danger_flags"] = {"高热神昏": "yes"}
        _, errors, _ = _validate_raw(raw)
        assert any("高热神昏" in e for e in errors)


# ============================================================
# confidence 不一致文案
# ============================================================
class TestConfidenceWording:
    def test_inconsistent_message_shows_both_levels(self):
        # 声称 HIGH 但只覆盖 1 维 → 推断 LOW；告警必须同时说清两端等级
        raw = {
            "date": "2026-01-01",
            "confidence": "HIGH",
            "observations": {"tongue": {"body": {"color": "淡红"}}},
            "danger_flags": {"triggered": [], "not_triggered": []},
        }
        _, _, warnings = _validate_raw(raw)
        conf_warn = [w for w in warnings if "置信度不一致" in w]
        assert conf_warn, f"应有置信度不一致告警: {warnings}"
        msg = conf_warn[0]
        assert "HIGH" in msg           # 声称值
        assert "LOW" in msg            # 覆盖推断等级
        assert "推断" in msg           # 等级来源说清

    def test_unparseable_message_mentions_inferred_level(self):
        raw = _shape_b_record()
        raw["confidence"] = "极高"
        _, _, warnings = _validate_raw(raw)
        msg = [w for w in warnings if "无法识别" in w]
        assert msg and "MEDIUM" in msg[0]  # 1 维覆盖 → MEDIUM 推断


# ============================================================
# Windows GBK 控制台：emoji 打印不崩
# ============================================================
def _run_validator_cli(io_encoding):
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = io_encoding
    env.pop("PYTHONUTF8", None)
    return subprocess.run(
        [sys.executable, os.path.join(ROOT, "scripts", "input_validator.py"),
         RECORD_PATH],
        capture_output=True, env=env, cwd=ROOT, timeout=120,
    )


class TestGbkConsole:
    def test_gbk_stdout_no_crash_exit_zero(self):
        # 默认 Windows 中文控制台 = GBK：emoji 打印曾抛 UnicodeEncodeError
        # （traceback + 非预期退出）。修复后：stdout 完整、退出码 0（无 error）
        proc = _run_validator_cli("gbk")
        assert proc.returncode == 0, (
            f"GBK 下退出码应为 0，实际 {proc.returncode}；"
            f"stderr: {proc.stderr.decode('gbk', errors='replace')[:500]}"
        )
        out = proc.stdout.decode("gbk", errors="replace")
        assert "验证结果" in out
        assert "Traceback" not in out

    def test_utf8_stdout_keeps_emoji(self):
        proc = _run_validator_cli("utf-8")
        assert proc.returncode == 0
        out = proc.stdout.decode("utf-8")
        assert "验证结果" in out
        assert "✅" in out  # emoji 原样保留

    def test_error_exit_code_preserved_gbk(self):
        # 退出码语义不变：有 error 的记录仍退出 1（GBK 下也不崩）
        bad = {"date": "2026-01-01", "confidence": "LOW",
               "formula": {"name": "违规方"},
               "danger_flags": {"triggered": [], "not_triggered": []}}
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                         encoding="utf-8") as f:
            json.dump(bad, f, ensure_ascii=False)
            path = f.name
        try:
            env = dict(os.environ)
            env["PYTHONIOENCODING"] = "gbk"
            proc = subprocess.run(
                [sys.executable, os.path.join(ROOT, "scripts",
                                              "input_validator.py"), path],
                capture_output=True, env=env, cwd=ROOT, timeout=120)
            assert proc.returncode == 1
            assert b"Traceback" not in proc.stderr
        finally:
            os.remove(path)
