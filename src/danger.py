#!/usr/bin/env python3
"""危重信号（danger flags）探测与字典模块（src 层，零第三方依赖）。

红线语义的系统级单一事实来源：
- DANGER_FLAGS：红线键 → {name, sign, note}（探测词表、拦截弹层、详情横幅共用）
- DANGER_PATTERNS：红线键 → 探测词（str 或 tuple 多词，任一命中即触发）
- detect_danger(obs)：观察值/档案文本 → 命中的红线键列表

历史：该能力 2026-10-16 长在 web/ 层（wizard_store），
2026-10-21 下沉至 src/（DANGER_FLAGS_FIX_PLAN_2026-10-21 B 批）——
非 Web 路径（CLI / 其他 agent / validator 一致性提示）同享探测兜底。

探测纪律（勿破坏）：
- 探测词只收照片可判且措辞特异的体征；形态类判据（猪腰/砂皮等）
  受照片质量影响大（教材原注「不能拘泥」），人工填档路径同样可命中
- 否定守卫：匹配位置前 4 字内含「无/不/未/没」即跳过
- 否定窗口限制在单个叶子字段内部，不跨字段拼接
"""
from __future__ import annotations

# ============================================================
# 红线字典（键对齐 templates/multi_dim_record_template.json；
# 中文名对齐 templates/adaptive_analysis_prompt.md §4.5）
# 注明：镜面舌/舌象危重等含通用诊断学概念者已在 note 标注来源
# ============================================================
DANGER_FLAGS = {
    "daiyang":         {"name": "戴阳证",
                        "sign": "面红如妆 + 手足厥逆（可兼身反不恶寒、掀衣揭被、脉暴出）",
                        "note": "真阳欲脱，严禁解表发汗，立即就医（原著救治方向：通脉四逆加猪胆汤，须医师面诊）"},
    "skin_cold":       {"name": "肤冷脉微", "sign": "皮肤触之冰冷 + 脉微",
                        "note": "真阳衰竭，立即就医"},
    "flesh_wasted":    {"name": "大肉已脱", "sign": "大肉已脱 + 大骨陷下",
                        "note": "精血枯竭，预后不良，建议就医"},
    "tongue_rigid":    {"name": "舌体强硬", "sign": "舌体强直，转动不灵，且语言謇涩",
                        "note": "中风痰瘀阻络（《中医诊断学》p118 第 9 项），难治，立即就医"},
    "tongue_critical": {"name": "舌象危重", "sign": "舌质紫暗 + 苔焦黑干裂",
                        "note": "危重症（通用诊断学说法），立即就医"},
    "mirror_tongue":   {"name": "镜面舌",   "sign": "舌深绛无苔而光亮如镜；或舌色白如镜、毫无血色（主营血大亏）",
                        "note": "胃气、胃阴枯涸（《中医诊断学》p118 第 2 项），病重难治，立即就医"},
    "acute_jaundice":  {"name": "急性黄疸", "sign": "巩膜黄染 + 皮肤黄如橘皮",
                        "note": "急性肝胆重症，紧急就医"},
    "wind_stroke":     {"name": "中风重症", "sign": "口不能言 + 身体不收",
                        "note": "中风重症（风痱），立即就医"},
    "throat_erosion":  {"name": "狐惑重症",
                        "sign": "默默欲眠、恶闻食臭、面目乍赤乍黑乍白、蚀喉声嗄",
                        "note": "狐惑（厥阴本病，原著有甘草泻心汤方向），建议尽快就医"},
    "yangming_critical": {"name": "阳明危重", "sign": "神昏谵语、循衣摸床、微喘直视",
                        "note": "阳明病危重证（212条），紧急就医"},
    "collapse_yang":   {"name": "脱阳前兆", "sign": "神识昏昧 + 冷汗如油",
                        "note": "真阳外脱前兆，紧急就医"},
    # 危重舌象 8 项（教材复查 P1，《中医诊断学》p117 附篇全 10 项，
    # 镜面舌/舌强语謇已有对应键 mirror_tongue/tongue_rigid，此处补齐其余 8 项）
    "pigkidney_tongue": {"name": "猪腰舌", "sign": "舌面无苔，如去膜的猪腰",
                        "note": "胃气将绝，主病危，立即就医"},
    "sandy_tongue":    {"name": "砂皮舌", "sign": "舌粗糙有刺，如沙鱼皮，或干燥枯裂",
                        "note": "津液枯竭，病危，立即就医"},
    "litchi_tongue":   {"name": "干荔舌", "sign": "舌敛束而无津，形如干荔肉",
                        "note": "热极津枯，病危，立即就医"},
    "persimmon_tongue": {"name": "火柿舌", "sign": "舌如火柿色，或色紫而干晦如猪肝色",
                        "note": "内脏败坏，病危，立即就医"},
    "ochre_tongue":    {"name": "赭黑舌", "sign": "舌质色赭带黑",
                        "note": "肾阴将绝，病危，立即就医"},
    "thin_coatless":   {"name": "瘦薄无苔舌", "sign": "舌体瘦小薄嫩，光而无苔",
                        "note": "胃气将绝，难治，立即就医"},
    "retracted_tongue": {"name": "囊缩卷舌", "sign": "舌体卷缩，兼阴囊缩入",
                        "note": "厥阴气绝，难治，立即就医（阴囊症状以自陈为准，不采集照片）"},
    "blue_tongue":     {"name": "蓝舌", "sign": "舌质由淡紫转蓝，苔由淡灰转黑或白如霉点",
                        "note": "病危重，难治，立即就医"},
}

# ============================================================
# 探测词表（仅含措辞特异的体征表述；tuple = 多词任一命中即触发）
# ============================================================
DANGER_PATTERNS = {
    "daiyang": "面红如妆",
    "tongue_rigid": "强硬",
    "tongue_critical": "焦黑",
    # 镜面舌探测：剥落封闭枚举含「镜面」（无/剥落/花剥/地图舌/镜面/剥脱），
    # 「光剥无苔」为人工填档路径的另一口径；不以裸「无苔」探测
    #（「局部无苔」是花剥/地图舌，非镜面）
    "mirror_tongue": ("镜面", "光剥无苔"),
    "acute_jaundice": "黄如橘皮",
    "flesh_wasted": "大肉已脱",
    "wind_stroke": "口不能言",
    "skin_cold": "触之冰冷",
    "throat_erosion": "狐惑",
    # P1（原著审查）补两条红线探测（均为低特异但值得复核的表述）
    "yangming_critical": "直视",
    "collapse_yang": ("冷汗", "绝汗"),
    # 教材复查 P1：危重舌象 8 项文本探测（《中医诊断学》p117）
    "pigkidney_tongue": "猪腰",
    "sandy_tongue": "砂皮",
    "litchi_tongue": "干荔",
    "persimmon_tongue": "火柿",
    "ochre_tongue": "赭黑",
    "thin_coatless": "瘦薄无苔",
    "retracted_tongue": "囊缩",
    "blue_tongue": "蓝舌",
}

_NEG_WORDS = ("无", "不", "未", "没")


def _leaf_texts(obj):
    """递归产出对象内所有非空字符串叶子（generator）。

    探测按叶子逐个扫描、否定窗口限制在叶子内部——拼接整串会让窗口
    吃进前一字段的结尾字（「无汗」+「绝汗」跨字段误抑制红线漏报）。
    """
    if isinstance(obj, dict):
        for v in obj.values():
            yield from _leaf_texts(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _leaf_texts(v)
    elif obj is not None:
        s = str(obj).strip()
        if s:
            yield s


def detect_danger(observations) -> list:
    """扫描观察值文本，返回命中的危险信号键列表（无命中返回 []）。

    带否定守卫（与评分层同原则）：匹配位置前 4 字内含否定词即跳过——
    「无苔」不命中「局部无苔」前的「无」，「冷汗」不命中「无冷汗」。
    """
    out = []
    for key, pats in DANGER_PATTERNS.items():
        for pat in (pats if isinstance(pats, tuple) else (pats,)):
            hit = False
            for text in _leaf_texts(observations):
                idx = text.find(pat)
                while idx != -1:
                    window = text[max(0, idx - 4):idx]
                    if not any(n in window for n in _NEG_WORDS):
                        hit = True
                        break
                    idx = text.find(pat, idx + 1)
                if hit:
                    break
            if hit:
                out.append(key)
                break
    return out
