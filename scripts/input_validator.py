#!/usr/bin/env python3
"""
输入验证器 —— 多维度中医望诊 Daily Analysis JSON 验证
============================================================

本验证器是 Record / Dimension / Confidence module 的 adapter：
不再手抄字段路径，而是通过 Record interface 取数据，从 Dimension module
取规范六维，从 Confidence module 复核安全边界。校验逻辑数据驱动。

功能：
  1. 必填顶层字段（date 等）
  2. 六维观测覆盖（数据驱动，从 Dimension 枚举取规范）
  3. 问诊覆盖统计
  4. 安全红线（danger_flags）完整性
  5. 置信度一致性：记录声称的 confidence 与实际覆盖维度数是否一致
     （LOW 不允许给方剂 —— 安全边界强制，违反计为**严重错误**，退出码 1）

严重度约定：
  - error：结构缺失/安全边界违反 → 退出码 1，记录不予通过
  - warning：取值可疑/覆盖不全 → 提示但通过

用法：
  python3 scripts/input_validator.py <daily_analysis_json_path>

示例：
  python3 scripts/input_validator.py records/daily/2026-06-25_analysis.json
"""

import json
import os
import sys
from typing import Any, Dict, List, Tuple

# 让仓库根可被导入（src 为包）
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from src.record import DailyRecord, SCHEMA, has_formula_content  # noqa: E402
from src.dimensions import DIMENSIONS, VisionDimension  # noqa: E402
from src import confidence as confidence_mod  # noqa: E402

# 顶层容器字段:键存在但类型不是 dict → 严重错误(不能静默按空处理,
# 否则红线/方剂等安全数据会被类型错误"清零"后放行)
_DICT_FIELDS = ("observations", "doubao_vision_analysis", "inquiry",
                "inquiry_coverage", "deepseek_diagnosis",
                "pattern_differentiation", "danger_flags", "formula")


def validate_record(filepath: str) -> Tuple[DailyRecord, List[str], List[str]]:
    """验证单个 daily analysis JSON 文件。

    返回:
        tuple: (record, errors, warnings)
        record 为 DailyRecord（即使有错误也返回，便于报告取 date 等）。
    """
    errors: List[str] = []
    warnings: List[str] = []

    if not os.path.isfile(filepath):
        return None, [f"❌ 文件不存在: {filepath}"], []

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except json.JSONDecodeError as e:
        return None, [f"❌ JSON 解析失败: {e}"], []
    except Exception as e:
        return None, [f"❌ 读取文件出错: {e}"], []

    try:
        record = DailyRecord(raw)
    except (TypeError, ValueError) as e:
        # 顶层不是对象（如 JSON 数组）等无法解析的输入 → error 报告，不落 traceback
        return None, [f"❌ 记录结构异常，无法解析: {e}"], []

    try:
        # ---- 0. 顶层容器类型 ----
        errors.extend(_validate_structure(record.raw))

        # ---- 1. 顶层必填字段（数据驱动，来自 SCHEMA） ----
        for field in SCHEMA["top_required_any"]:
            if not record.raw.get(field):
                errors.append(f"❌ 缺失必填字段: {field}")

        # ---- 2. 六维观测覆盖（从 Dimension 枚举取规范，不再手抄中文名） ----
        coverage = record.get_dimension_coverage()
        covered_count = record.get_covered_dimension_count()
        for dim in DIMENSIONS:
            if not coverage[dim]:
                warnings.append(f"⚠️ 维度未覆盖: {dim.chinese_name}（{dim.english_name}）")

        # ---- 3. 问诊覆盖 ----
        asked, total = record.get_inquiry_coverage()
        # total==0 视为问诊结构缺失（形状 A 的 inquiry 会被解析为 asked 计数）
        if total == 0 and "inquiry" not in record.raw and "inquiry_coverage" not in record.raw:
            warnings.append("⚠️ 缺少问诊数据（inquiry / inquiry_coverage）")

        # ---- 4. 安全红线（danger_flags）完整性 ----
        df_errors, df_warnings = _validate_danger_flags(record)
        errors.extend(df_errors)
        warnings.extend(df_warnings)

        # ---- 5. 置信度一致性（调 Confidence module） ----
        conf_errors, conf_warnings = _validate_confidence(record, covered_count)
        errors.extend(conf_errors)
        warnings.extend(conf_warnings)
    except Exception as e:  # 防御兜底：任何未预期异常都转为 error，不落 traceback
        errors.append(f"❌ 校验过程异常（记录结构可能损坏）: {e!r}")

    return record, errors, warnings


def _validate_structure(raw: Dict[str, Any]) -> List[str]:
    """顶层容器字段的类型校验：键存在但不是对象 → error。"""
    return [
        f"❌ 字段 {field} 应为对象，实际为 {type(raw[field]).__name__}"
        for field in _DICT_FIELDS
        if field in raw and not isinstance(raw[field], dict)
    ]


def _validate_danger_flags(record: DailyRecord) -> Tuple[List[str], List[str]]:
    """校验安全红线对象存在且结构合法。返回 (errors, warnings)。

    形状 B：danger_flags.triggered / not_triggered（列表）。
    形状 A：danger_flags 为 {flag_name: {triggered, finding}}。
    严重度：对象/triggered 字段缺失=error；取值类型可疑、finding 为空=warning。
    """
    errors: List[str] = []
    warnings: List[str] = []
    df = record.get_danger_flags()
    if not isinstance(df, dict):
        errors.append("❌ danger_flags 缺失或格式错误，应为对象")
        return errors, warnings

    # 形状 B：triggered/not_triggered 必须是列表——类型错误会让红线状态
    # 被静默"清零"（get_triggered_danger_flags 对非列表回落为 []），
    # 报告显示"✅ 无触发"，这是安全数据，必须 error
    for key in ("triggered", "not_triggered"):
        if key in df and not isinstance(df[key], list):
            errors.append(
                f"❌ danger_flags.{key} 应为列表，实际为 {type(df[key]).__name__}"
                f"（红线状态不可信）"
            )

    # 形状 A：每个 flag 对象应有 triggered 布尔；触发时应有 finding
    for name, flag in df.items():
        if name in ("triggered", "not_triggered"):
            continue  # 形状 B 的列表字段，上面已校验
        if isinstance(flag, dict):
            if "triggered" not in flag:
                errors.append(f"❌ danger_flags.{name} 缺失 'triggered' 字段")
            elif not isinstance(flag["triggered"], bool):
                # 非布尔（如 "yes"）会被 `is True` 严格比较判为未触发——
                # 真值意图的红线被静默清零，必须 error
                errors.append(
                    f"❌ danger_flags.{name}.triggered 应为布尔值，"
                    f"实际为: {type(flag['triggered']).__name__}（红线状态不可信）"
                )
            if flag.get("triggered") is True:
                finding = flag.get("finding", "")
                if not finding or (isinstance(finding, str) and not finding.strip()):
                    warnings.append(
                        f"⚠️ danger_flags.{name}.triggered=true 但 finding 为空"
                    )
        else:
            errors.append(
                f"❌ danger_flags.{name} 应为对象，实际为 {type(flag).__name__}"
            )
    return errors, warnings


def _validate_confidence(record: DailyRecord,
                         covered_count: int) -> Tuple[List[str], List[str]]:
    """校验置信度一致性与安全边界（LOW 禁方剂）。返回 (errors, warnings)。

    安全边界违反是 error——"宁缺毋滥"铁律必须以退出码 1 强制执行，
    否则违规记录照样通过校验（历史 Bug 7）。

    检查以【自报等级】与【覆盖度推断等级】中更严格者执行：
    不自报 confidence、或自报无法解析的值，都按推断等级照样查方剂——
    否则"省略/乱填 confidence 字段"即可绕过铁律（fail-open，对抗验证发现）。
    方剂内容判定用 has_formula_content：无方名但携带药材+剂量同样算方剂。
    """
    errors: List[str] = []
    warnings: List[str] = []
    claimed = record.get_confidence()
    claimed_level = confidence_mod.parse_level(claimed)
    inferred = confidence_mod.from_coverage(covered_count)

    if claimed is None:
        # 形状 A 无 confidence 字段，按覆盖度推断并提示（安全检查照常执行）
        warnings.append(
            f"ℹ️ 记录未自报 confidence；按覆盖 {covered_count}/6 维推断为 {inferred.value}"
        )
    elif claimed_level is None:
        warnings.append(
            f"⚠️ 无法识别的置信度取值: {claimed!r}（应为 LOW/MEDIUM/HIGH）；"
            f"按覆盖度推断为 {inferred.value} 执行安全检查"
        )
    elif not confidence_mod.is_consistent(claimed, covered_count):
        warnings.append(
            f"⚠️ 置信度不一致: 记录声称 {claimed}，但实际覆盖 {covered_count}/6 维 "
            f"应为 {inferred.value}"
        )

    # 安全边界：自报与推断等级任一为 LOW 即禁方剂（取更严格者，error 级）
    check_levels = [lvl for lvl in (claimed_level, inferred) if lvl is not None]
    if any(not confidence_mod.allows_formula(lvl) for lvl in check_levels):
        if has_formula_content(record.get_formula()):
            shown = claimed if claimed is not None else f"推断 {inferred.value}"
            errors.append(
                f"🚨 安全边界违反: confidence={shown}（LOW）不应输出方剂，"
                f"但记录包含方剂内容"
            )

    return errors, warnings


def print_report(filepath: str, record: DailyRecord,
                 errors: List[str], warnings: List[str]) -> None:
    """打印验证报告到 stdout。"""
    print("=" * 60)
    print("📋 中医望诊 Daily Analysis JSON 验证报告")
    print("=" * 60)
    print(f"📂 文件: {filepath}")
    print(f"📅 记录日期: {record.date if record else '未知'}")
    print(f"🧩 记录形状: {record.shape if record else '?'}（A=模板/中文键, B=真实产出/英文键）")
    print()

    if record:
        coverage = record.get_dimension_coverage()
        covered = sum(1 for c in coverage.values() if c)
        print(f"🔍 望诊维度覆盖: {covered}/{len(DIMENSIONS)}")
        for dim in DIMENSIONS:
            mark = "✅" if coverage[dim] else "❌"
            print(f"   {mark} {dim.chinese_name}（{dim.english_name}）")

        asked, total = record.get_inquiry_coverage()
        print(f"🗣️ 问诊覆盖: {asked}/{total}")

        triggered = record.get_triggered_danger_flags()
        if triggered:
            print(f"\n🚨 触发的安全红线 ({len(triggered)}):")
            for name in triggered:
                print(f"   ⚠️ {name}")
        else:
            print("\n✅ 安全红线: 无触发")

        claimed = record.get_confidence()
        covered_count = record.get_covered_dimension_count()
        if claimed:
            consistent = confidence_mod.is_consistent(claimed, covered_count)
            tag = "✅" if consistent else "⚠️"
            print(f"\n{tag} 置信度: 声称 {claimed}，实际覆盖 {covered_count}/6 维")

    print()
    print("-" * 60)
    print(f"验证结果: {len(errors)} 个严重错误, {len(warnings)} 个警告")
    print()
    if errors:
        print("--- 严重错误 ---")
        for e in errors:
            print(e)
        print()
    if warnings:
        print("--- 警告 / 提示 ---")
        for w in warnings:
            print(w)
        print()
    if not errors and not warnings:
        print("✅ 验证通过！记录格式完整且符合规范。")
    print("=" * 60)

    if errors:
        print("\n❌ 存在严重错误，请修正后重新提交。")
    elif warnings:
        print("\n⚠️ 验证通过（有警告），建议检查警告项。")
    else:
        print("\n🎉 完美！记录完全合规。")


def main():
    if len(sys.argv) < 2:
        print("用法: python input_validator.py <daily_analysis_json_path>")
        print("示例: python input_validator.py records/daily/2026-06-25_analysis.json")
        sys.exit(1)

    filepath = sys.argv[1]
    record, errors, warnings = validate_record(filepath)
    print_report(filepath, record, errors, warnings)
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
