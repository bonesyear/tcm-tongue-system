#!/usr/bin/env python3
"""
偏离度评分模块（Deviation Scoring module）
============================================

把"定性描述 → 0-10 定量分数"的真领域逻辑从 800 行周报脚本里抽出来，
集中持有所有映射表与匹配策略。

Interface：
    score(dimension, observation) -> float          # 维度综合偏离度 0-10
    score_indicators(dimension, observation) -> dict # 各规范指标分数

observation 可为 Record.get_observation() 返回的 {指标: 文本}（推荐，精确），
也可为纯文本（按整段文本对每个指标做匹配，便于测试）。

匹配策略（复用 validator 的三级匹配经验）：
    1. 精确匹配优先（整段文本 == 关键词）
    2. 子串匹配降级 —— 取命中最长的关键词（"红如妆" 优先于 "红"，
       "淡红" 优先于 "红"），消除歧义
    3. 否定守卫（双向） —— 前置：关键词前 6 字内、同一小句（以标点/空白
       为界）出现否定词（无/不/未/没/非，"非常" 是程度副词不算）；
       后置：关键词后紧跟否定短语（不明显/不显著/未见/阴性 等）。
       覆盖 "无明显浮肿"、"未见浮肿"、"没有黄染"、"浮肿不明显" 等真实
       LLM 产出中的常见否定表达；且按关键词的**全部出现位置**判定——
       "舌质不红，但舌边红" 中第二个 "红" 是真阳性，正常计分。

评分基线约定：**正常表现一律 0 分**（淡红舌、薄白苔、润苔、荣润、适中
均为 0）。0 = 正常，10 = 极重度异常，全表统一，杜绝"正常人踩关注线"。

与 Record module 组合：Record 按维度取观测 → Scoring 打分。
"""

import re
from typing import Dict, Union

from .dimensions import VisionDimension


# ============================================================
# 映射表（从 generate_weekly_report.py 迁入，唯一来源）
# ============================================================

# 舌质颜色（偏红/偏淡 → 偏离正常程度；0 = 正常基线）
TONGUE_BODY_COLOR_MAP = {
    "淡红": 0,   # 正常基线
    "淡白": 7,   # 偏寒
    "红": 7,     # 偏热
    "红绛": 8,   # 热甚
    "紫暗": 9,   # 瘀血
    "暗红": 8,   # 瘀热
    "青紫": 10,  # 寒凝瘀血重
}

# 舌苔厚度（0=薄白正常, 10=极重度异常）
TONGUE_COATING_THICKNESS_MAP = {
    "薄白": 0,
    "薄黄": 3,
    "无苔": 8,
    "白厚": 7,
    "黄厚": 7,
    "厚腻": 8,
    "焦黑": 10,
}

# 舌苔润燥（0 = 正常基线）
TONGUE_MOISTURE_MAP = {
    "润": 0,     # 正常基线（润泽为常态）
    "滑": 7,     # 水饮
    "燥": 8,     # 津亏
    "干裂": 10,
}

# 齿痕程度
TOOTH_MARK_MAP = {
    "无": 0,
    "轻度": 4,
    "中度": 7,
    "重度": 10,
}

# 瘀斑
PETECHIAE_MAP = {
    "无": 0,
    "散在": 5,
    "密集": 9,
}

# 舌下络脉迂曲
SUBLINGUAL_VARICOSITY_MAP = {
    "无": 0,
    "轻度": 4,
    "中度": 7,
    "重度": 10,
}

# 裂纹
FISSURE_MAP = {
    "无": 0,
    "浅裂": 4,
    "深裂": 8,
}

# 舌体胖瘦（偏离适中即为异常）
TONGUE_BODY_SIZE_MAP = {
    "适中": 0,
    "胖大": 7,
    "瘦小": 6,
    "肿胀": 9,
}

# 舌质荣枯（有神/无神）
TONGUE_BODY_LUSTER_MAP = {
    "荣润": 0,   # 有神
    "少泽": 5,   # 少神
    "枯槁": 8,   # 无神
}

# 面部光泽
FACE_LUSTER_MAP = {
    "荣润": 0,   # 有神
    "晦暗": 5,   # 少泽
    "枯槁": 8,   # 无神
}

# 巩膜颜色
SCLERA_COLOR_MAP = {
    "黄染": 7,     # 黄疸
    "苍白": 5,     # 血虚/虚寒
    "蓝巩膜": 8,   # 缺铁/虫积
}


# ============================================================
# 各维度的规范指标 → 规则表
# ============================================================
# 每条规则：关键词 → 分值。关键词尽量用多字特异词，避免裸 "明显"/"轻度"
# 跨字段误命中；不可避开的（如鼻翼煽动）由否定守卫与按指标独立匹配兜底。

DIMENSION_RULES: Dict[VisionDimension, Dict[str, Dict[str, int]]] = {
    VisionDimension.TONGUE: {
        "body_color": TONGUE_BODY_COLOR_MAP,
        "coating_thickness": TONGUE_COATING_THICKNESS_MAP,
        "coating_moisture": TONGUE_MOISTURE_MAP,
        "tooth_marks": TOOTH_MARK_MAP,
        "petechiae": PETECHIAE_MAP,
        "sublingual_varicosity": SUBLINGUAL_VARICOSITY_MAP,
        "fissure": FISSURE_MAP,
        "body_size": TONGUE_BODY_SIZE_MAP,
        "body_luster": TONGUE_BODY_LUSTER_MAP,
    },
    VisionDimension.HEAD_FACE: {
        "face_color":    {"萎黄": 5, "晦暗": 5, "黧黑": 5, "青灰": 5, "红如妆": 9},
        "face_luster":   FACE_LUSTER_MAP,
        "face_edema":    {"明显浮肿": 4, "轻度浮肿": 2, "面目鲜泽": 4, "卧蚕": 4},
        "lip_color":     {"紫暗": 3, "青紫": 3},
        "lip_moisture":  {"燥裂": 3, "干枯": 3},
        "nose_flare":    {"明显": 4, "轻度": 2},
    },
    VisionDimension.EYE: {
        "redness":      {"充血": 6, "赤丝": 3, "红赤": 4, "红血丝": 3},
        "sclera_color": SCLERA_COLOR_MAP,
        "jaundice":     {"黄染明显": 8, "黄染轻度": 4, "黄染": 4},
        "edema":        {"卧蚕": 6, "浮肿明显": 4, "浮肿": 4, "微肿": 2},
        "dark_orbit":   {"黯黑": 4, "黑眼圈": 4},
    },
    VisionDimension.EAR: {
        "color":  {"红赤": 3, "青黑": 3, "淡白": 2},
        "helix":  {"干枯": 4},
    },
    VisionDimension.HAND: {
        "palm_temp":   {"厥冷": 8, "不温": 4, "凉": 4, "温": 0},
        "palm_color":  {"淡白": 2, "暗红": 2, "紫暗": 4},
        "nail_color":  {"紫暗": 4, "暗紫": 4, "淡白": 2},
        "nail_shape":  {"甲错": 3},
        "ecchymosis":  {"散在": 5, "密集": 9},
    },
    VisionDimension.SKIN: {
        "color":        {"黄如橘皮": 8, "橘皮": 8, "烟熏": 5, "萎黄": 3},
        "cuo":          {"广泛": 5, "局部": 2},
        "yellow_sweat": {"色正黄": 5, "明显": 5},
        "edema":        {"凹陷": 4, "全身浮肿": 8},
        "dryness":      {"龟裂": 6, "粗糙": 2},
    },
}


# 舌诊的雷达图指标名 → 规范指标 key（供周报 extract_tongue_metrics 复用）
TONGUE_RADAR_METRIC_KEYS = {
    "舌质颜色": "body_color",
    "舌苔厚度": "coating_thickness",
    "舌苔润燥": "coating_moisture",
    "齿痕": "tooth_marks",
    "瘀斑": "petechiae",
    "舌下络脉": "sublingual_varicosity",
    "裂纹": "fissure",
    "舌体胖瘦": "body_size",
}


# ============================================================
# 匹配策略
# ============================================================

# 否定词：无/不/未/没/非（"非常" 是程度副词，用负向前瞻排除）
_NEGATION_RE = re.compile(r"无|不|未|没|非(?!常)")
# 后置否定短语（"浮肿不明显""黄染未见" 等"关键词+否定"句式），
# 必须锚定在关键词之后的小句开头，避免"充血无改善"这类误杀
_POST_NEGATION_RE = re.compile(r"不明显|不显著|不突出|不著|未见|阴性")
# 否定守卫回看/后看窗口（字数）。窗口内以最近的标点/空白截断，
# 否定词只在与关键词同一小句内才生效（"无瘀点，散在瘀斑" 的 "无" 不跨逗号）。
_NEGATION_WINDOW = 6
_CLAUSE_SPLIT_RE = re.compile(r"[，。；、,;:：\s]")


def _is_negated(text: str, idx: int, kw_len: int) -> bool:
    """判断 text 中 idx 处开始、长 kw_len 的关键词该次出现是否被否定。

    前置否定：关键词前同一小句、窗口内出现否定字（无明显浮肿/未见黄染）。
    后置否定：关键词后紧跟否定短语（浮肿不明显/黄染未见/充血阴性）。
    """
    before = text[max(0, idx - _NEGATION_WINDOW):idx]
    before = _CLAUSE_SPLIT_RE.split(before)[-1]  # 只保留最近标点之后（同一小句）
    if _NEGATION_RE.search(before):
        return True
    after = text[idx + kw_len: idx + kw_len + _NEGATION_WINDOW]
    after = _CLAUSE_SPLIT_RE.split(after)[0]     # 只看关键词所在小句的剩余部分
    return bool(_POST_NEGATION_RE.match(after))


def _has_unnegated_occurrence(text: str, kw: str) -> bool:
    """kw 在 text 中是否存在**未被否定**的出现。

    必须检查全部出现位置，不能只看首个——"舌质不红，但舌边红" 中
    首个 "红" 被否定，第二个 "红" 是真阳性，只查首位会漏报异常。
    """
    idx = text.find(kw)
    while idx != -1:
        if not _is_negated(text, idx, len(kw)):
            return True
        idx = text.find(kw, idx + 1)
    return False


def _match_score(rules: Dict[str, int], text: str) -> int:
    """单指标打分：精确匹配优先 → 最长子串匹配（带双向否定守卫）。

    返回命中的分值；无命中返回 0。
    已知局限：无标点连写（如"手足不温伴厥冷"）中，否定词可能误伤
    窗口内的下一个关键词；规范指标文本通常简短，实际影响有限。
    """
    if not text:
        return 0
    text = text.strip()

    # 1. 精确匹配优先（"不温" 等含否定字的枚举值经此路径直接命中）
    if text in rules:
        return rules[text]

    # 2. 子串匹配降级：取存在未否定出现的最长关键词
    best_kw = None
    for kw in rules:
        if kw not in text:
            continue
        if not _has_unnegated_occurrence(text, kw):
            continue
        if best_kw is None or len(kw) > len(best_kw):
            best_kw = kw

    return rules[best_kw] if best_kw is not None else 0


def _normalize_observation(observation) -> Dict[str, str]:
    """把入参规范为 {指标: 文本}。

    - dict：直接用（Record.get_observation 的产出）
    - str：对每个指标都用整段文本做匹配（便于直接断言）
    """
    if isinstance(observation, dict):
        return observation
    text = observation if isinstance(observation, str) else str(observation)
    return {"__text__": text}


def _indicator_text(obs: Dict[str, str], indicator: str) -> str:
    """从规范化观测中取某指标的文本。"""
    if indicator in obs:
        return obs[indicator]
    # 字符串入参时统一放在 __text__
    return obs.get("__text__", "")


def score_indicators(dimension: VisionDimension,
                     observation) -> Dict[str, int]:
    """返回某维度各规范指标的分数（0-10）。"""
    dim = dimension if isinstance(dimension, VisionDimension) else VisionDimension(dimension)
    rules_map = DIMENSION_RULES.get(dim, {})
    obs = _normalize_observation(observation)
    return {
        indicator: _match_score(rules, _indicator_text(obs, indicator))
        for indicator, rules in rules_map.items()
    }


def score(dimension: VisionDimension, observation) -> float:
    """维度综合偏离度（0-10）。

    舌诊取「已覆盖指标」均值 —— 分母用有分的指标数而非固定 8，
    避免稀疏记录（只描述了舌质颜色等少数指标）被未提及的指标稀释；
    至少 1 项有分才计算均值，全无分则返回 0。
    其余维度取各项指标之和并封顶 10（与原 compute_dimension_deviation 一致）。

    注意：observation 传**纯文本**时，同一段话会对每个指标分别匹配，
    可能重复计分（如"黄染明显"同时命中 jaundice 与 sclera_color）；
    需要精确口径请传 Record.get_observation() 的结构化 dict。
    """
    dim = dimension if isinstance(dimension, VisionDimension) else VisionDimension(dimension)
    indicators = score_indicators(dim, observation)
    if not indicators:
        return 0.0

    if dim == VisionDimension.TONGUE:
        total = sum(indicators.values())
        covered = sum(1 for v in indicators.values() if v > 0)
        if covered == 0:
            return 0.0
        return round(total / covered, 1)

    # 其余维度：累加并封顶
    return round(min(sum(indicators.values()), 10), 1)
