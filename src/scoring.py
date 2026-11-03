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
    3. 文本证据由 `src.text_analysis` 与预警共享：同一小句内处理
       前置/后置否定（含并非、绝非、排除），跨逗号/分号及无标点转折复位；
       鉴别比较与光学反光不计患者阳性。"非典型"不当作否定。
       每个关键词均检查全部出现位置，"舌不红但舌边红" 中第二个红为真阳性。

评分基线约定：**正常表现一律 0 分**（淡红舌、薄白苔、润苔、适中
均为 0）。0 = 正常，10 = 极重度异常，全表统一，杜绝"正常人踩关注线"。

与 Record module 组合：Record 按维度取观测 → Scoring 打分。
"""

import re
from dataclasses import dataclass, field
from typing import Dict, Optional

from .dimensions import VisionDimension
from .text_analysis import find_term


# ============================================================
# 映射表（从 generate_weekly_report.py 迁入，唯一来源）
# ============================================================

# 舌质颜色（偏红/偏淡 → 偏离正常程度；0 = 正常基线）
# 2026-10-20 主人定：九档并五档（暗红→红绛、青紫/淡紫→紫暗归并，
# 超模型色分辨力的细分删除；红润盾牌词随枚举收敛一并移除——
# prompt 只产五档词，不再担心裸「红」误命中）。历史档案不追溯。
TONGUE_BODY_COLOR_MAP = {
    "淡红": 0,   # 正常基线
    "淡白": 7,   # 偏寒
    "红": 7,     # 偏热
    "红绛": 8,   # 热甚（暗红归并于此）
    "紫暗": 9,   # 瘀血（青紫/淡紫归并于此）
}

# 舌苔厚度（0=薄白正常, 10=极重度异常）
TONGUE_COATING_THICKNESS_MAP = {
    "薄": 0,     # 轮次 8 新增：显式基线（实测"薄"裸词漏判）；**不收缩裸"厚"**——
                 # 裸字会放大否定窗口边缘案例（"苔不厚但稍厚"），故厚度异常只收
                 # 多字特异词，"厚"不入表
    "薄白": 0,
    "薄黄": 3,
    "略厚": 3,   # 轮次 8 新增（中间态，分值用户签认）
    "稍厚": 3,   # 轮次 8 新增（中间态，分值用户签认）
    "偏厚": 4,   # 轮次 8 新增（中间态，分值用户签认）
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
# 轮次 7 补漏（2026-09-18 实测漏判 "偏胖" → 0 分，分值经用户签认）：
# ① 偏胖/偏瘦为中间态，偏离适中即为轻中度异常（3-4 分，低于胖大 7/瘦小 6）。
# ② 复合词（胖嫩/瘦薄）不收 —— 它们混入老嫩维度，与「评分层只收静态照片
#    可客观判读指标」的统一原则冲突（荣枯/老嫩已整体降级到辨证层），老嫩应
#    走 prompt 规范化或辨证层，不得隐式计入胖瘦轴。
# 硬约束：偏胖必须 ≤ 7。若 ≥ 8，"偏胖大" 文本中 "胖大"(2字) 与 "偏胖"(2字)
# 同长度平局、取分值高者会翻转取偏胖，导致 tests/test_scoring.py:332 与
# 周报 fixture 期望值全部变红（独立复验实测）。
TONGUE_BODY_SIZE_MAP = {
    "适中": 0,
    "稍胖": 3,   # 轮次 7 新增（中间态，分值用户签认）
    "略瘦": 3,   # 轮次 7 新增（中间态，分值用户签认）
    "偏胖": 4,   # 轮次 7 新增（中间态，分值用户签认；硬约束 ≤ 7）
    "偏瘦": 4,   # 轮次 7 新增（中间态，分值用户签认）
    "胖大": 7,
    "瘦小": 6,
    "肿胀": 9,
}

# ============================================================
# 轮次 3（评分覆盖扩展）新增映射表 —— 分值经用户签认（2026-09-17）
# ------------------------------------------------------------
# 统一原则：评分层只收"静态照片可客观判读"的指标；需动态观察或对
# 光线/拍摄条件敏感的主观判断，降级为辨证层。剥落/腻腐/苔色/点刺/
# 舌下颜色与粗细均为静态可判的形态学体征，故补入评分；对称地，
# body_dynamics（颤动/痿软/歪斜）静态照片不可判、coating_distribution
# （异常语义已被剥落/厚度覆盖）不收规则。
# 0 = 正常基线，越高越异常；正常描述（"无剥落/不腻/无点刺"）由否定
# 守卫归零，无需显式 0 词条。
# ============================================================

# 舌苔剥落（结构性形态，静态照片完全可判；核心观察点）
TONGUE_COATING_PEELING_MAP = {
    "剥落": 6,
    "剥脱": 6,
    "花剥": 6,
    "地图舌": 7,
    "镜面": 9,
}

# 舌苔腻腐（苔质附着形态；"不腻"中"腻"被前置否定守卫拦截）
TONGUE_COATING_GREASY_MAP = {
    "微腻": 2,   # 轮次 8 新增（中间态，分值用户签认；硬约束 ≤ 稍腻 3）
    "稍腻": 3,
    "偏腻": 4,   # 轮次 9 新增（中间态，分值用户签认 2026-09-18）：实测「偏腻」
                 # 命中裸「腻」得 5 分偏重；「偏腻:4」最长匹配压过裸「腻」，
                 # 顺序理顺：微腻2 < 稍腻3 < 偏腻4 < 腻5
    "腻": 5,
    "厚腻": 8,
    "腐苔": 7,
}

# 舌苔颜色（颜色是照片最可靠的维度；"灰黑"靠最长匹配压过"灰"）
TONGUE_COATING_COLOR_MAP = {
    "白": 0,
    "黄": 3,
    "灰": 6,
    "黑": 7,
    "灰黑": 8,
}

# 点刺（凸起红点，分辨率敏感 → 分值保守）
# ⚠️ 2026-09-18 起**已退出评分层**（见下方 DIMENSION_RULES 注释）：实测同一真实
# 舌照 9/9 判「有」而用户肉眼为「无」——凸起度需触诊/动态观察，不满足
# scoring.py:139-143 的收录原则（「评分层只收静态照片可客观判读的指标」），
# 同 #18 palm_temp 先例降级到辨证层。本表保留备查（含轮次 11 的「少量: 2」
# 兜底语义记录）；档案的 prickles 字段（用户肉眼值）继续保留供辨证层使用。
TONGUE_PRICKLES_MAP = {
    "点刺": 5,
    "芒刺": 6,
    # 轮次 11 新增（KNOWN_ISSUES #6，分值 2 经用户签认 2026-09-18）：补真实档案
    # 「少量」漏判（MISS → 0）。2 分保守（远低于点刺 5/芒刺 6），符合本表
    # 「分辨率敏感 → 分值保守」的既定口径。无长度压制（"少量"2 字 = "点刺"
    # 2 字，同长平局取高：「少量点刺」→ 5，方向正确）；「无点刺」「点刺不
    # 明显」仍由否定守卫归零；其余 38 个指标表均未收「少量」，无跨字段串扰。
    "少量": 2,
}

# 舌下络脉颜色（前提：拍了舌下照；淡紫为正常基线）
SUBLINGUAL_COLOR_MAP = {
    "淡紫": 0,
    "紫暗": 6,
    "青紫": 8,
}

# 舌下络脉粗细
SUBLINGUAL_THICKNESS_MAP = {
    "增粗": 5,
    "怒张": 7,
}

# 面部光泽
FACE_LUSTER_MAP = {
    "荣润": 0,   # 有神
    "晦暗": 5,   # 少泽
    "枯槁": 8,   # 无神
}

# 巩膜颜色
SCLERA_COLOR_MAP = {
    "无黄染": 0,   # 旧记录的正常表述；阳性黄染只由 jaundice 评分
    "苍白": 5,     # 血虚/虚寒
    "蓝巩膜": 8,   # 弥漫蓝色观察；与白睛蓝斑及病因判断分开
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
        # 轮次 3 新增（统一原则：均为静态照片可判的形态学体征）
        "coating_peeling": TONGUE_COATING_PEELING_MAP,
        "coating_greasy": TONGUE_COATING_GREASY_MAP,
        "coating_color": TONGUE_COATING_COLOR_MAP,
        # 2026-09-18：prickles 从评分表降级——凸起度需触诊/动态观察，静态照片
        # 判不准（实测同一真实舌照 9/9 判「有」而用户肉眼为「无」），违反统一
        # 原则「评分层只收静态照片可客观判读的指标」（:139-143）；同轮次 9
        # palm_temp 先例降级到辨证层。观测层（record.py 指标路径与档案
        # prickles 字段）保留——用户肉眼值仍可进档案供辨证，只是不参与数值
        # 评分。词表 TONGUE_PRICKLES_MAP 留存备查（移除理由与日期如上）。
        "sublingual_color": SUBLINGUAL_COLOR_MAP,
        "sublingual_thickness": SUBLINGUAL_THICKNESS_MAP,
        "sublingual_petechiae": PETECHIAE_MAP,  # 直接复用既有瘀斑表
    },
    VisionDimension.HEAD_FACE: {
        "face_color":    {"萎黄": 5, "晦暗": 5, "黧黑": 5, "青灰": 5, "红如妆": 9,
                          "苍白": 7, "㿠白": 7,  # 2026-10-16 P0（原著审查）：
                                     # 面色苍白/㿠白为伤精血少重证（《经方探源》
                                     # L3603），此前无词条被 fail-open 静默归零
                          "淡白": 4,            # 面色淡白 = 血虚（同书 L7228 唇甲
                                     # 暗黄或淡白为血少明证）；封闭词表含此值
                          "红赤": 3,            # 2026-10-20：太阳面赤（热证表证），
                                     # 分值 3 参照唇色「红:3」先例（待主人签认）；
                                     # 识图 prompt 枚举词此前静默归零
                                     },
        "face_luster":   FACE_LUSTER_MAP,
        "face_edema":    {"明显浮肿": 4, "轻度浮肿": 2, "面目鲜泽": 4},
        "lip_color":     {"淡白": 5, "暗黄": 5,  # 2026-10-16 P0（原著审查）：
                                     # 唇甲暗黄或淡白为血少定性证据（L7228），
                                     # 此前无词条被 fail-open 静默归零
                          "淡红": 0,  # 轮次 8 新增：**盾牌词** —— 压制裸「红: 3」；
                                     # 否则「淡红」会误命中「红」（同「红润:0」压
                                     # 「红:7」的既有先例，见 TONGUE_BODY_COLOR_MAP
                                     # 注释）；与「红: 3」必须成对落地
                          "红润": 0,  # 轮次 8 新增：盾牌词（唇色正常描述，同
                                     # TONGUE_BODY_COLOR_MAP「红润:0」先例）——
                                     # 缺它纯文本"红润有光泽"会误命中裸「红」
                          "淡粉红": 0,  # 轮次 9 新增：盾牌词（预防裸『红: 3』误命中，
                                       # 分值用户签认 2026-09-18）——实测「淡粉红」
                                       # 误命中裸「红」得 3 分；最长匹配压过
                          "红": 3,    # 轮次 8 新增（唇色偏红 = 轻度异常，分值用户签认）
                          "紫暗": 3, "青紫": 3},
        "lip_moisture":  {"润": 0,    # 轮次 8 新增：显式基线
                          "稍干": 2,  # 轮次 8 新增（中间态，分值用户签认）
                          "偏干": 2,  # 轮次 8 新增（中间态，分值用户签认）
                          "干燥": 2,  # 轮次 8 新增（分值用户签认）
                          "燥裂": 3, "干枯": 3},
        "nose_flare":    {"明显": 4, "轻度": 2},
    },
    VisionDimension.EYE: {
        "redness":      {"充血": 6, "赤丝": 3, "红赤": 4, "红血丝": 3,
                         "血丝": 2,  # 轮次 9 新增（分值用户签认 2026-09-18）：
                                    # 补「轻度，可见少量血丝」漏判；3 字「红血丝:3」
                                    # 仍靠最长匹配压过（既有行为不变）
                         },
        "sclera_color": SCLERA_COLOR_MAP,
        "jaundice":     {"黄染明显": 8, "黄染轻度": 4, "黄染": 4},
        "edema":        {"卧蚕": 6, "浮肿明显": 4, "浮肿": 4, "微肿": 2},
        "dark_orbit":   {"黯黑": 4, "黑眼圈": 4},
        "lower_lid":    {"淡红": 0,  # 基线（prompt 指示正常填淡红，缺它会
                                    # 每条正常记录收「词表外措辞」告警）
                         "淡白": 5, "淡黄": 5, "苍白": 5,  # 2026-10-16 P1：
                                    # 下睑淡黄/苍白为血少定性证据（L7228）
                         },
    },
    VisionDimension.EAR: {
        "color":  {"红赤": 3, "青黑": 3, "淡白": 2},
        "helix":  {"润泽": 0,  # 轮次 9 新增：基线（分值用户签认 2026-09-18）
                   "略枯": 2,  # 轮次 9 新增：补「尚润，略枯」轻度漏判（分值用户签认）
                   "干枯": 4},
    },
    VisionDimension.HAND: {
        # 轮次 9（2026-09-18）：palm_temp 从评分表降级——掌温需触诊/问诊，
        # 静态照片判不了，违反统一原则「评分层只收静态照片可客观判读的指标」
        # （历史轮次记录已归入 CHANGELOG.md）；且为 6 维度中唯一零语料指标
        # （从无档案赋值）。降级到辨证层（由问诊采集掌温，见 docs/user-guide.md）。
        # 观测层（record.py 指标路径）保留——问诊文本仍可进辨证 prompt。
        # 原词表留存备查（移除理由与日期如上）：
        #   "palm_temp": {"厥冷": 8, "不温": 4, "凉": 4, "温": 0},
        "palm_color":  {"淡红": 0,  # 轮次 8 新增：**盾牌词** —— 压制裸「红: 3」，
                                    # 与「红: 3」必须成对落地（否则「淡红」误命中
                                    # 「红」，同 lip_color 与「红润:0」先例）
                        "红润": 0,  # 轮次 8 新增：盾牌词（掌色正常描述，同
                                    # TONGUE_BODY_COLOR_MAP「红润:0」先例）
                        "红": 3,    # 轮次 8 新增（掌色偏红 = 轻度异常，分值用户签认）
                        "淡白": 2, "暗红": 2, "紫暗": 4},
        "nail_color":  {"紫暗": 4, "暗紫": 4,
                        "淡白": 4,  # 2026-10-16 P0（原著审查）：甲床淡白为血少
                                    # 定性证据（L7228），原值 2 偏低，与唇色对齐
                        "红润": 0,  # 2026-10-20：正常基线（同 palm_color/lip_color
                                    # 「红润:0」先例）——prompt 枚举词此前静默 0
                                    # 且每条正常甲床记录收词表外告警
                        },
        "nail_shape":  {"甲错": 3},
        "ecchymosis":  {"散在": 5, "密集": 9},
    },
    VisionDimension.SKIN: {
        "color":        {"黄如橘皮": 8, "橘皮": 8, "烟熏": 5, "萎黄": 3},
        "cuo":          {"甲错": 5,  # 2026-10-16 P0（原著审查）：肌肤甲错为
                                    # 伤营/瘀血皮肤体征（L3595）；此前仅有
                                    # 「广泛/局部」程度词，直书「甲错」MISS 归零。
                                    # 「无甲错」由否定守卫拦截，不误中
                         "广泛": 5, "局部": 2},
        "yellow_sweat": {"色正黄": 5, "明显": 5},
        "edema":        {"凹陷": 4, "全身浮肿": 8},
        "dryness":      {"龟裂": 6, "粗糙": 2},
    },
}


# 舌诊的雷达图指标名 → 规范指标 key（供周报 extract_tongue_metrics 复用）
# body_luster（舌质润燥，原"舌质荣枯"）不进雷达图也不参与评分：光泽受
# 照片光线干扰（顺光/闪光灯观感完全不同），且神气/荣枯需动态观察，
# 静态照片不可判——不给不可靠数据建展示位（方案 A，评分层降级到辨证层）。
TONGUE_RADAR_METRIC_KEYS = {
    "舌质颜色": "body_color",
    "舌苔厚度": "coating_thickness",
    "舌苔润燥": "coating_moisture",
    "齿痕": "tooth_marks",
    "瘀斑": "petechiae",
    "舌下络脉": "sublingual_varicosity",
    "裂纹": "fissure",
    "舌体胖瘦": "body_size",
    # 轮次 3 新增第 9 轴：剥落是核心观察点，
    # 不进雷达图则只在维度均分里体现，趋势图看不到
    "舌苔剥落": "coating_peeling",
}


# ============================================================
# 匹配策略
# ============================================================

def _has_unnegated_occurrence(text: str, kw: str) -> bool:
    """文本与预警共享同一肯定匹配；鉴别和反光语境不计阳性。"""
    return find_term(text, kw).state == "matched"


def match_keyword(rules: Dict[str, int], text: str) -> Optional[str]:
    """返回 text 命中的词表键；无命中返回 None。

    判据与评分完全一致（精确匹配优先 → 存在未否定出现的最长子串，
    同长度取分值最高者），供校验器判断「值是否落在词表内」——
    单一事实来源，避免校验器与评分层的匹配逻辑各自漂移。
    """
    if not isinstance(text, str):
        return None
    from .textnorm import normalize_text
    text = normalize_text(text.strip())
    if not text:
        return None

    # 1. 精确匹配优先（"不温" 等含否定字的枚举值经此路径直接命中）
    if text in rules:
        return text

    # 2. 子串匹配降级：取存在未否定出现的最长关键词；
    #    同长度时取分值最高者（fail-loud：宁可高估不漏估——"湿润偏滑"
    #    应命中"滑"=7，不能因"润"=0 排在前面而漏掉湿盛信号）
    best_kw = None
    for kw in rules:
        if normalize_text(kw) not in text:
            continue
        if not _has_unnegated_occurrence(text, kw):
            continue
        if (best_kw is None or len(kw) > len(best_kw)
                or (len(kw) == len(best_kw) and rules[kw] > rules[best_kw])):
            best_kw = kw
    return best_kw


def _match_score(rules: Dict[str, int], text: str) -> int:
    """单指标打分：命中的词表键对应分值；非字符串或无命中返回 0。"""
    kw = match_keyword(rules, text)
    return rules[kw] if kw is not None else 0


def _normalize_observation(observation) -> Dict[str, str]:
    """把入参规范为 {指标: 文本}。

    - dict：直接用（Record.get_observation 的产出）
    - str：对每个指标都用整段文本做匹配（便于直接断言）
    """
    if isinstance(observation, dict):
        return observation
    text = observation if isinstance(observation, str) else str(observation)
    return {"__text__": text}


def _normalize_dimension_observation(dim: VisionDimension, observation) -> Dict[str, str]:
    obs = _normalize_observation(observation)
    if "__text__" not in obs:
        from .indicators import INDICATOR_REGISTRY
        return INDICATOR_REGISTRY.normalize_observation(dim, obs)
    return obs


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
    obs = _normalize_dimension_observation(dim, observation)
    return {
        indicator: _match_score(rules, _indicator_text(obs, indicator))
        for indicator, rules in rules_map.items()
    }


def score(dimension: VisionDimension, observation) -> float:
    """维度综合偏离度（0-10）。

    舌诊取**最重单项**（2026-10-16 v1.7.21 口径变更，原著审查 P1）：
    经方「一证定方」——单项危证（如青紫 10）不应被多项正常稀释；
    此前 sparse 均值会把 青紫10+略厚3+微腻2 压成 5.0。
    其余维度取各项指标之和并封顶 10（与原 compute_dimension_deviation 一致，
    非舌维度指标少、多项轻度异常按累积负荷计）。

    observation 传纯文本时会对每个指标分别匹配；结构化 dict 中的旧
    sclera_color 黄染别名会归入 jaundice，不再重复计分。
    需要精确口径请传 Record.get_observation() 的结构化 dict。
    """
    dim = dimension if isinstance(dimension, VisionDimension) else VisionDimension(dimension)
    indicators = score_indicators(dim, observation)
    if not indicators:
        return 0.0

    if dim == VisionDimension.TONGUE:
        return round(float(max(indicators.values())), 1)

    # 其余维度：累加并封顶；float() 统一返回类型——round(int, 1) 在
    # Python 3 返回 int，会让 mean 出现 0（int）与 max 0.0（float）并列
    return round(float(min(sum(indicators.values()), 10)), 1)


SCORING_RULESET_VERSION = "2026-10-26.b06.1"


@dataclass(frozen=True)
class ScoreResult:
    state: str
    value: float | None
    matched_terms: Dict[str, str] = field(default_factory=dict)
    unknown_indicators: tuple = ()
    missing_indicators: tuple = ()
    ruleset_version: str = SCORING_RULESET_VERSION

    @property
    def unknown_count(self) -> int:
        return len(self.unknown_indicators)


_EXPLICIT_NORMAL_TEXTS = frozenset({
    "无", "正常", "未见异常", "未见", "阴性", "生理性", "非病理", "不明显", "光滑",
})


def _is_explicit_normal(rules: Dict[str, int], text: str) -> bool:
    stripped = text.strip()
    if stripped in _EXPLICIT_NORMAL_TEXTS:
        return True
    if "正常" in stripped and "不正常" not in stripped:
        return True
    if re.match(r"^不(?:粗|红|肿|黄|黑|紫|热|冷|干|湿|腻|厚|硬|软|长|短|大|小|多|少|明显)", stripped):
        return True
    return any(kw in text and not _has_unnegated_occurrence(text, kw)
               for kw in rules)


def assess_indicators(dimension: VisionDimension, observation) -> Dict[str, ScoreResult]:
    """逐指标返回状态化评分；旧 score_indicators 的数值契约保持不变。"""
    dim = dimension if isinstance(dimension, VisionDimension) else VisionDimension(dimension)
    rules_map = DIMENSION_RULES.get(dim, {})
    obs = _normalize_dimension_observation(dim, observation)
    results = {}
    for indicator in sorted(set(rules_map) | set(obs)):
        rules = rules_map.get(indicator)
        if not rules:
            results[indicator] = ScoreResult("not_applicable", None)
            continue
        text = _indicator_text(obs, indicator)
        if not isinstance(text, str):
            results[indicator] = ScoreResult(
                "unknown" if text else "not_applicable", None)
            continue
        if not text.strip():
            results[indicator] = ScoreResult("not_applicable", None)
            continue
        keyword = match_keyword(rules, text)
        if keyword is None:
            if _is_explicit_normal(rules, text):
                results[indicator] = ScoreResult("normal", 0.0)
            else:
                results[indicator] = ScoreResult("unknown", None)
            continue
        value = rules[keyword]
        state = "normal" if value == 0 else "abnormal"
        results[indicator] = ScoreResult(state, float(value), {indicator: keyword})
    return results


def assess(dimension: VisionDimension, observation) -> ScoreResult:
    """聚合一个维度；有异常先聚合，未知存在时不把全维称为正常。"""
    dim = dimension if isinstance(dimension, VisionDimension) else VisionDimension(dimension)
    obs = _normalize_dimension_observation(dim, observation)
    details = assess_indicators(dim, obs)
    abnormal = [r for r in details.values() if r.state == "abnormal"]
    unknown = sorted(ind for ind, r in details.items() if r.state == "unknown")
    normal = [r for r in details.values() if r.state == "normal"]
    missing = sorted(
        ind for ind, r in details.items()
        if r.state == "not_applicable" and ind in DIMENSION_RULES.get(dim, {})
        and (not isinstance(_indicator_text(obs, ind), str)
             or not _indicator_text(obs, ind).strip())
    )
    matched = {}
    for indicator, result in details.items():
        matched.update(result.matched_terms)

    if abnormal:
        values = [r.value for r in abnormal]
        value = max(values) if dim == VisionDimension.TONGUE else min(sum(values), 10)
        return ScoreResult("abnormal", round(float(value), 1), matched,
                           tuple(unknown), tuple(missing))
    if unknown:
        return ScoreResult("unknown", None, matched, tuple(unknown), tuple(missing))
    if normal:
        return ScoreResult("normal", 0.0, matched, (), tuple(missing))
    return ScoreResult("not_applicable", None, matched, (), tuple(missing))
