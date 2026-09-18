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
  6. 评分值卫生与词表覆盖（纯告警）：判读注记 / 语义矛盾写法 /
     封闭词表之外的措辞（会被评分层静默读作 0 分）

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
import re
import sys
from typing import Any, Dict, List, Tuple

# 让仓库根可被导入（src 为包）
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from src.record import DailyRecord, SCHEMA, has_formula_content  # noqa: E402
from src.dimensions import DIMENSIONS, VisionDimension  # noqa: E402
from src import confidence as confidence_mod  # noqa: E402
from src.scoring import DIMENSION_RULES, match_keyword  # noqa: E402

# 顶层容器字段:键存在但类型不是 dict → 严重错误(不能静默按空处理,
# 否则红线/方剂等安全数据会被类型错误"清零"后放行)
# vision_analysis/diagnosis 为形状 A 新名；旧名 doubao_vision_analysis/
# deepseek_diagnosis 永久保留——历史档案（不迁移）仍需类型校验。
_DICT_FIELDS = ("observations", "vision_analysis", "doubao_vision_analysis",
                "inquiry", "inquiry_coverage", "diagnosis",
                "deepseek_diagnosis",
                "pattern_differentiation", "danger_flags", "formula",
                # 形状 C 顶层维度键与辨证键
                "tongue", "head_face", "eye", "ear", "hand", "skin",
                "pattern_update")


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

        # ---- 6. 评分值卫生（轮次 8，纯告警，不影响通过/失败判定） ----
        warnings.extend(_validate_scoring_value_hygiene(record))

        # ---- 7. 封闭词表覆盖（纯告警，同上）：词表外措辞会被评分层
        #         静默读作 0 分（正常），此处把它暴露出来 ----
        warnings.extend(_validate_scoring_vocab_coverage(record))
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


# 判读注记特征：值含括号，且括号内出现模型名或判读词
# （保守判据，避免把正常括号描述误报）
_ANNOTATION_BRACKET_RE = re.compile(r"[（(]([^（）()]*)[)）]")
_ANNOTATION_WORD_RE = re.compile(
    r"豆包|DeepSeek|Qwen|K3|Kimi|GPT|Claude|Gemini|用户确认|误判")


def _validate_scoring_value_hygiene(record: DailyRecord) -> List[str]:
    """评分值卫生校验（轮次 8，纯告警 —— 与既有 warning 通道同哲学，
    不改变通过/失败判定，不引入新的失败条件）。防止未来档案数据"乱"：

    1. body_color 与 sublingual_color 同时含「淡紫」→ 两处淡紫同名异义
       （舌质淡紫 = 异常 6 / 舌下浅蓝紫 = 生理性正常 0），提示确认字段归属。
    2. 任一评分类指标的值含判读注记特征（括号内出现模型名/判读词）→
       值应只写当前状态纯描述，判读注记请移入 notes/lessons —— 注记会被
       关键词评分误命中（已有 08-02 palm_color 实测假阳性 4 分）。
    3. 值以「正常」开头且同时含「未拍」（轮次 9 新增）→ 「正常（用户声明，
       未拍摄）」式占位文本语义矛盾（声明未拍摄却写"正常"，与 prompt 约定
       「绝不编造观察」有张力），建议写为「未拍摄（用户声明正常）」。
       判据保守：只抓「正常」打头 + 含「未拍」的组合，不误报推荐写法
       （「未拍摄（用户声明正常）」以「未拍摄」开头，不触发）。
    """
    warnings: List[str] = []

    tongue_obs = record.get_observation(VisionDimension.TONGUE)
    if ("淡紫" in tongue_obs.get("body_color", "")
            and "淡紫" in tongue_obs.get("sublingual_color", "")):
        warnings.append(
            "⚠️ body_color 与 sublingual_color 同时含「淡紫」：两处淡紫同名异义"
            "（舌质=异常6 / 舌下=正常0），请确认字段归属"
        )

    for dim in DIMENSIONS:
        scored = DIMENSION_RULES.get(dim, {})
        if not scored:
            continue
        obs = record.get_observation(dim)
        for indicator in scored:
            value = obs.get(indicator, "")
            if not value:
                continue
            for bracket in _ANNOTATION_BRACKET_RE.findall(value):
                if _ANNOTATION_WORD_RE.search(bracket):
                    warnings.append(
                        f"⚠️ {dim.chinese_name}（{dim.english_name}）指标 "
                        f"{indicator} 的值含判读注记: {value!r} —— "
                        "值应只写当前状态纯描述，判读注记请移入 notes/lessons"
                        "（注记会被关键词评分误命中，已有 08-02 palm_color "
                        "实测假阳性 4 分）"
                    )
                    break  # 同一指标只告警一次
            if value.startswith("正常") and "未拍" in value:
                warnings.append(
                    f"⚠️ {dim.chinese_name}（{dim.english_name}）指标 "
                    f"{indicator} 的值同时声明「未拍摄」与「正常」，语义矛盾: "
                    f"{value!r} —— 建议写为「未拍摄（用户声明正常）」"
                )
    return warnings


# 词表覆盖检查的豁免：值本身在声明「无/未见/正常/未拍摄/生理性」等
# 正常或否定语义。评分词表只收异常词与显式基线词，这类正常/否定描述
# 本就不入词表（评分 0 = 正常，结果正确），不是模型措辞问题。
# 判据保守：宁可漏报，不可刷屏——词表外措辞只在「既未命中词表、
# 又无任何正常/否定语义标记」时才告警。
_NORMAL_STATEMENT_RE = re.compile(r"无|未|没|不|正常|阴性|生理性|非病理")


def _validate_scoring_vocab_coverage(record: DailyRecord) -> List[str]:
    """封闭词表覆盖校验（纯告警 —— 与既有 warning 通道同哲学，不改变
    通过/失败判定）。把「词表外措辞 → 静默读作 0 分」暴露出来：

    危险链条：换用非默认模型 → 模型用词表外的措辞（如把「偏胖」写成
    「较丰满」）→ scoring 词表匹配不到 → 该指标静默按 0 分（正常）
    计入评分与红线推断 → 使用者永远无法察觉该维度没被正确评估。

    豁免情形（全部满足保守优先原则）：
      - 值为空：缺失由覆盖度检查负责，不归本检查；
      - 命中词表任一词条：判据与 scoring.match_keyword 完全一致（含
        双向否定守卫），单一事实来源，不与评分层漂移；
      - 值含正常/否定语义标记（无/未/没/不/正常/阴性/生理性/非病理）
        ——正常/否定描述本就不入词表，0 分是正确结果；
      - 值已被「判读注记」检查告警（_validate_scoring_value_hygiene
        第 2 类）：同一值不重复告警。
    只查 DIMENSION_RULES 收录的封闭词表指标；自由文本指标
    （body_luster / body_dynamics / coating_distribution / prickles /
    palm_temp / lip_around / nose_color / nose_bleeding 等无词表指标）
    不适用本检查。

    告警文案按「正常描述可忽略 / 异常描述改用规范词」两分支给出处置
    指引：词表数据无法可靠区分良性与漏判（如齿痕表含显式正常词
    「无:0」而巩膜表无 0 词条，与实测良恶性分布不相关），故不按情形
    分级措辞，把判断规则直接交给使用者；「静默按 0 分」的核心事实
    两种分支下均原样保留。

    规范词清单的语义：清单是「合法写法全集」（全量封闭词表），不是
    「推荐值」——含 0 分基线词。例如齿痕清单「无/轻度/中度/重度」
    里的「无:0」是正常基线词，body_color 的「淡红:0」同理（见
    src/scoring.py 评分基线约定：正常表现一律 0 分）。

    为何不过滤 0 分词条：过滤后清单会退化为「纯异常词表」，在告警
    文案中展示会诱导使用者填报异常值；这类假阳性发生在数据源头，
    评分层无法检测——与项目既定的「不给不可靠数据建展示位」纪律
    冲突（docs/KNOWN_ISSUES.md 豆包舌底过度判读、面色虚象链假阳性；
    src/scoring.py TONGUE_RADAR_METRIC_KEYS 上方注释）。

    注：若未来做「分组标注」展示（词条按分值分组呈现），标签应写
    「基线词」而非「正常词」——0 分词不全是常态，如舌下「淡紫:0」
    属生理性、苔色「白:0」属色基。
    """
    warnings: List[str] = []

    for dim in DIMENSIONS:
        scored = DIMENSION_RULES.get(dim, {})
        if not scored:
            continue
        obs = record.get_observation(dim)
        for indicator, rules in scored.items():
            value = obs.get(indicator, "")
            if not value:
                continue
            if match_keyword(rules, value) is not None:
                continue
            if _NORMAL_STATEMENT_RE.search(value):
                continue
            # 判读注记检查已告警的值不重复告警（同一值两条 warning 是噪声）
            if any(_ANNOTATION_WORD_RE.search(b)
                   for b in _ANNOTATION_BRACKET_RE.findall(value)):
                continue
            warnings.append(
                f"⚠️ 词表外措辞: {dim.chinese_name}（{dim.english_name}）指标 "
                f"{indicator} 的值 {value!r} 未命中评分词表任何词条——"
                f"该指标将被静默按 0 分（正常）计入评分与红线推断。"
                f"处置取决于该值的语义：若确为正常描述，0 分即正确结果，"
                f"可忽略本告警；若意在描述异常表现，则属模型措辞问题而非数据错误，"
                f"请改用该指标的规范词（{'/'.join(rules)}），"
                f"否则异常将被静默漏判"
            )
    return warnings


def print_report(filepath: str, record: DailyRecord,
                 errors: List[str], warnings: List[str]) -> None:
    """打印验证报告到 stdout。"""
    print("=" * 60)
    print("📋 中医望诊 Daily Analysis JSON 验证报告")
    print("=" * 60)
    print(f"📂 文件: {filepath}")
    print(f"📅 记录日期: {record.date if record else '未知'}")
    print(f"🧩 记录形状: {record.shape if record else '?'}"
          "（A=模板/中文键, B=observations/英文键, C=顶层英文维度键）")
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
