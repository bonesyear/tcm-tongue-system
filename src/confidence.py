#!/usr/bin/env python3
"""
置信度模块（Confidence module）
================================

把"覆盖几维 → 什么置信度 → 允许输出什么"这条系统安全边界从自然语言
（prompt、文档各写一遍）变成可执行、可断言的代码。

规则（与 adaptive_analysis_prompt.md §3.1、dimension-overlap-analysis.md §5.2 同源）：
    1 维   → LOW    （不给方剂，仅给辨证方向 + 鉴别诊断列表）
    2-3 维 → MEDIUM （给方剂大类，不给具体剂量）
    4-6 维 → HIGH   （完整辨证 + 具体方剂与剂量）

Interface：
    from_coverage(n) -> ConfidenceLevel
    allows_formula(level) -> bool
    is_consistent(claimed, covered_count) -> bool
    prompt_paragraph() -> str   # 生成 prompt/文档中引用的置信度段落
"""

from enum import Enum
from typing import Optional, Union


class ConfidenceLevel(Enum):
    """置信度三档枚举。value 为规范大写名。"""
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


def from_coverage(dimensions_covered: int) -> ConfidenceLevel:
    """已覆盖维度数 → 置信度等级。

    1 维 → LOW；2-3 维 → MEDIUM；4-6 维 → HIGH。
    不足 1 维按 LOW；超过 6 维封顶 HIGH。
    """
    n = int(dimensions_covered or 0)
    if n <= 1:
        return ConfidenceLevel.LOW
    if n <= 3:
        return ConfidenceLevel.MEDIUM
    return ConfidenceLevel.HIGH


def allows_formula(level: Union[ConfidenceLevel, str]) -> bool:
    """该置信度等级是否允许输出方剂。

    LOW 不允许给方剂（宁缺毋滥铁律）；MEDIUM/HIGH 允许。
    """
    lvl = _coerce_level(level)
    return lvl in (ConfidenceLevel.MEDIUM, ConfidenceLevel.HIGH)


def allows_dosage(level: Union[ConfidenceLevel, str]) -> bool:
    """该置信度等级是否允许输出具体剂量。

    MEDIUM 仅给方剂大类不给剂量；HIGH 才给具体剂量。
    """
    return _coerce_level(level) is ConfidenceLevel.HIGH


# 中文置信度首字 → 等级
_CHINESE_LEVEL_INDEX = {
    "高": ConfidenceLevel.HIGH,
    "中": ConfidenceLevel.MEDIUM,
    "低": ConfidenceLevel.LOW,
}

# 首字之后允许的中文后缀（"高" + 后缀）：
# 高 / 高度 / 高度确信 / 高度置信 / 高置信 / 高置信度 / 中等
_CHINESE_LEVEL_SUFFIXES = ("", "度", "度确信", "度置信", "置信", "置信度", "等")


def parse_level(text: Optional[str]) -> Optional[ConfidenceLevel]:
    """把记录自报的置信度字符串解析为枚举。无法识别（含空白串）返回 None。

    兼容三类写法：
      - 英文规范值："HIGH" / "high"（大小写不敏感）
      - 英文带后缀："HIGH CONFIDENCE"、"HIGH置信度" 等——仅当规范值后
        紧跟非英文字母（"HIGHEST" 不算 HIGH；CJK 字符是合法边界，
        不能用 isalpha() 判断——CJK 的 isalpha() 为 True）
      - 中文："高" / "高度" / "高度确信" / "高置信度" / "中等"（中/低 同理）
    """
    if text is None:
        return None
    name = str(text).strip()
    if not name:
        # 纯空白：strip 后为空串，直接返回 None（曾因 name[0] 抛 IndexError）
        return None
    upper = name.upper()
    for lvl in ConfidenceLevel:
        value = lvl.value
        if upper == value:
            return lvl
        # 词边界前缀：后随字符不是 ASCII 字母即可（空格/连字符/中文均可）
        if (upper.startswith(value)
                and len(upper) > len(value)
                and not ("A" <= upper[len(value)] <= "Z")):
            return lvl
    first = name[0]
    if first in _CHINESE_LEVEL_INDEX and name[1:] in _CHINESE_LEVEL_SUFFIXES:
        return _CHINESE_LEVEL_INDEX[first]
    return None


def is_consistent(claimed: Optional[str], dimensions_covered: int) -> bool:
    """记录声称的置信度与实际覆盖维度数是否一致。

    供 validator / 周报断言：LLM 自填的 confidence 必须与
    from_coverage(实际覆盖维度数) 给出的等级一致，否则规则与执行脱节。
    """
    claimed_level = parse_level(claimed)
    if claimed_level is None:
        return False
    return claimed_level is from_coverage(dimensions_covered)


def prompt_paragraph() -> str:
    """生成 prompt / 文档中引用的置信度规则段落（规则一处定义，多处引用）。"""
    return (
        "置信度由拍照覆盖维度数决定（问诊不改变等级，仅提升同等级内精度）：\n"
        "  - 1 维 → 🟡 LOW：仅给辨证方向 + 鉴别诊断列表，不给方剂；\n"
        "  - 2-3 维 → 🟠 MEDIUM：给方剂大类，不给具体剂量；\n"
        "  - 4-6 维 → 🟢 HIGH：完整辨证 + 具体方剂与剂量。\n"
        "安全铁律：LOW 置信度下不得输出方剂（宁缺毋滥）。"
    )


def _coerce_level(level: Union[ConfidenceLevel, str]) -> ConfidenceLevel:
    if isinstance(level, ConfidenceLevel):
        return level
    parsed = parse_level(level)
    if parsed is None:
        raise ValueError(f"无法识别的置信度: {level!r}")
    return parsed
