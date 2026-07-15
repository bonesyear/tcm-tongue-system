#!/usr/bin/env python3
"""
六维望诊维度规范模块（Vision Dimension module）
=================================================

把"舌/头面/目/耳/手/皮肤"这一承重的领域概念收敛为单一来源：
六个维度的规范枚举，每维携带中文名、英文名、子域列表与计数规则，
并提供中↔英双向 adapter。

消费方（validator / weekly_report / prompt 文档）一律引用本模块，
不再各自硬编码中英文维度名，从而消除"head_face vs 头面诊"式的拼写漂移。

设计语汇（/codebase-design）：本模块是一个深 module——interface 很小
（六个枚举 + 两个 adapter），implementation 持有全部维度元数据。
两个 adapter（中/英）同时存在 → 这是个真 seam，不是假想。
"""

from enum import Enum
from typing import Dict, List, Optional


class VisionDimension(Enum):
    """六大望诊维度的规范枚举。

    每个成员的 value 为规范英文名（与真实记录 observations / photo_coverage
    的英文键一致），同时携带 chinese_name、subdomains 与计数规则。
    """

    TONGUE = ("tongue", "舌诊", ["舌质", "舌苔", "舌下络脉"])
    HEAD_FACE = ("head_face", "头面诊", ["面域", "唇域", "鼻域"])
    EYE = ("eye", "目诊", ["目赤", "巩膜黄染", "眼睑浮肿", "目眶黯黑"])
    EAR = ("ear", "耳诊", ["耳色", "耳轮"])
    HAND = ("hand", "手诊", ["手掌颜色", "手掌温度", "甲床颜色", "甲床形态", "手掌瘀斑"])
    SKIN = ("skin", "皮肤诊", ["肤色", "甲错", "黄汗", "水肿", "干燥"])

    def __new__(cls, english_name: str, chinese_name: str, subdomains: List[str]):
        obj = object.__new__(cls)
        obj._value_ = english_name
        obj.english_name = english_name
        obj.chinese_name = chinese_name
        obj.subdomains = list(subdomains)
        return obj

    # ---- 计数规则 ----
    def is_covered(self, observation) -> bool:
        """计数规则：该维度存在非空观测即计为"已覆盖"（计 1 维）。

        observation 可为 Record.get_observation() 返回的结构化 dict，
        也可为纯文本；任一字段有非空文本即算覆盖。
        """
        if observation is None:
            return False
        if isinstance(observation, dict):
            return any(bool(v) for v in observation.values())
        return bool(str(observation).strip())


# 全部维度的规范顺序（舌→头面→目→耳→手→皮肤）
DIMENSIONS: List[VisionDimension] = list(VisionDimension)

# 中文 → 英文 适配表（由枚举自动生成，避免再次手抄）
_CHINESE_INDEX: Dict[str, VisionDimension] = {d.chinese_name: d for d in DIMENSIONS}
_ENGLISH_INDEX: Dict[str, VisionDimension] = {d.english_name: d for d in DIMENSIONS}


def from_chinese(name: str) -> Optional[VisionDimension]:
    """中文维度名 → VisionDimension（adapter）。未知返回 None。"""
    if name is None:
        return None
    return _CHINESE_INDEX.get(name.strip())


def from_english(name: str) -> Optional[VisionDimension]:
    """英文维度名 → VisionDimension（adapter）。未知返回 None。"""
    if name is None:
        return None
    return _ENGLISH_INDEX.get(name.strip())


def chinese_to_english(name: str) -> Optional[str]:
    """中文维度名 → 英文维度名。"""
    dim = from_chinese(name)
    return dim.english_name if dim else None


def english_to_chinese(name: str) -> Optional[str]:
    """英文维度名 → 中文维度名。"""
    dim = from_english(name)
    return dim.chinese_name if dim else None


def all_chinese_names() -> List[str]:
    """规范六维的中文名列表（供 prompt / 文档引用）。"""
    return [d.chinese_name for d in DIMENSIONS]


def all_english_names() -> List[str]:
    """规范六维的英文名列表（供记录键名校验引用）。"""
    return [d.english_name for d in DIMENSIONS]
