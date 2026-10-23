"""本地规则「四证倾向速览」——未启用辨证模型时的报告区内容。

把当日记录做**确定性聚类**（无任何推理/LLM）：
1. 体质格局倾向：阳性体征按 正虚/邪实、水停/津亏 两轴聚合出的倾向陈述；
2. 四证倾向：阳性体征按 水/火/气/血 四证方向聚类；
3. 饮食宜忌方向：按聚出的四证查 knowledge_base diet-therapy.md 的体质节；
4. 明日问诊优先项：按前两名倾向推荐最具鉴别价值的未答问诊项。

以上都是证据清单的聚合视图与库内查表，**不是辨证结论**——六病归属、
病机合成、方药建议必须走辨证 LLM（见 adaptive_analysis_prompt.md）。

指标映射只收有出处支撑者（宁缺毋滥），逐条标注：
【KB L##】= knowledge_base/diagnostics/smartphone-visual-diagnostics.md 行号；
【食疗 L##】= knowledge_base/diet-lifestyle/diet-therapy.md 行号；
【台账】= docs/VOCAB_PROVENANCE_2026-10-16.md；【验】= 经验映射，无书籍直接出处。
"""

# PATTERN_MAP[dim_english][indicator] = [(match_values|None, 四证, 正邪, 出处注记), …]
# match_values 为 None 时任意阳性措辞都归入；正邪用于体质格局两轴聚合。
PATTERN_MAP = {
    "tongue": {
        "body_color": [({"红", "红绛"}, "火证", "邪", "舌红苔黄燥→火【KB L51】"),
                       ({"淡白"}, "气证", "正", "舌淡嫩薄白→气【KB L52】"),
                       ({"紫暗"}, "血证", "邪", "舌紫暗瘀斑→血（瘀）【KB L53】")],
        "body_size": [(None, "水证", "邪", "舌淡胖齿痕苔滑→水【KB L50】")],
        "tooth_marks": [(None, "水证", "邪", "舌淡胖齿痕苔滑→水【KB L50】")],
        "petechiae": [(None, "血证", "邪", "舌紫暗瘀斑→血（瘀）【KB L53】")],
        "coating_color": [({"黄", "黄腻"}, "火证", "邪", "舌红苔黄燥→火【KB L51】")],
        "coating_moisture": [({"偏干", "干", "燥"}, "火证", "邪", "苔燥→热盛津亏【KB L51】")],
        "coating_greasy": [(None, "水证", "邪", "苔滑腻→水湿内停【KB L50 语境】")],
        "coating_thickness": [(None, "水证", "邪", "苔厚→湿浊偏盛【验】")],
        "coating_peeling": [(None, "气证", "正", "剥落苔→胃气虚【验】")],
        "sublingual_color": [(None, "血证", "邪", "舌下络脉色深→血行不利【KB L53 语境】")],
        "sublingual_thickness": [(None, "血证", "邪", "舌下络脉粗张→血行不利【KB L53 语境】")],
        "sublingual_varicosity": [(None, "血证", "邪", "舌下络脉迂曲→血行不利【KB L53 语境】")],
        "sublingual_petechiae": [(None, "血证", "邪", "舌下瘀点→血行不利【KB L53 语境】")],
    },
    "head_face": {
        "face_color": [({"红赤"}, "火证", "邪", "面赤（缘缘正赤）→火【KB L95】"),
                       ({"黄", "黄肿"}, "水证", "邪", "面黄/黄肿→水【KB L96】"),
                       ({"晦暗", "萎黄", "淡白", "苍白"}, "血证", "正",
                        "面萎黄/苍白→伤营【KB L97】【台账】")],
        "face_edema": [(None, "水证", "邪", "面肿→津液不化【KB L96】")],
        "lip_color": [({"淡白", "苍白"}, "血证", "正", "唇淡白→血少【KB L97】"),
                      ({"紫暗"}, "血证", "邪", "唇紫暗→瘀血【KB L99】"),
                      ({"红赤", "鲜红"}, "火证", "邪", "唇鲜红→热盛【KB L99 语境】")],
        "nose_flare": [(None, "气证", "邪", "鼻翼煽动→肺气不利【KB L100】")],
    },
    "eye": {
        "redness": [(None, "火证", "邪", "目赤→上焦郁火【KB L134】")],
        "jaundice": [(None, "火证", "邪", "黄染→湿热/黄疸方向【验】")],
        "edema": [(None, "水证", "邪", "目下卧蚕/睑肿→水【KB L135】")],
        "dark_orbit": [(None, "血证", "邪", "两目黯黑→干血【KB L136】")],
        "lower_lid": [(None, "血证", "正", "下睑淡白→血少【台账】")],
    },
    "ear": {
        "color": [({"红赤"}, "火证", "邪", "耳色红赤→少阳郁火【KB L134 语境】")],
    },
    "hand": {
        "palm_color": [({"淡白", "偏淡白"}, "血证", "正", "掌色淡白→血少【台账】")],
        "nail_color": [({"淡白"}, "血证", "正", "甲床淡白→血少【台账】"),
                       ({"紫暗"}, "血证", "邪", "甲紫暗→瘀【KB L99 语境】")],
    },
    "skin": {
        "color": [({"黄如橘皮"}, "火证", "邪", "阳黄→湿热【验】"),
                  ({"烟熏"}, "水证", "邪", "阴黄→寒湿【验】"),
                  ({"萎黄"}, "血证", "正", "萎黄→血少不荣【验】")],
        "cuo": [(None, "血证", "邪", "肌肤甲错→干血/伤营【台账】")],
        "yellow_sweat": [(None, "水证", "邪", "黄汗→水热【台账 L1264】")],
        "edema": [(None, "水证", "邪", "浮肿→水饮外溢【KB L96 语境】")],
        # dryness（皮肤干燥/粗糙）：津亏方向不唯一（可热可虚），四证不映射
    },
}

# 津液观轴：水停 vs 津亏（独立于四证，指标维度）
FLUID_MAP = {
    "tongue": {
        "body_size": [(None, "水停", "舌胖大→水停【KB L50】")],
        "tooth_marks": [(None, "水停", "齿痕→水停【KB L50】")],
        "coating_greasy": [(None, "水停", "苔腻→水湿【KB L50 语境】")],
        "coating_moisture": [({"偏干", "干", "燥"}, "津亏", "苔燥→津亏【KB L51】")],
        "coating_peeling": [(None, "津亏", "剥落→胃津不足【验】")],
    },
    "head_face": {
        "face_edema": [(None, "水停", "面肿→水【KB L96】")],
        "lip_moisture": [({"偏干", "干", "燥"}, "津亏", "唇干→津不上承【验】")],
    },
    "eye": {
        "edema": [(None, "水停", "睑肿→水【KB L135】")],
    },
    "skin": {
        "edema": [(None, "水停", "浮肿→水【KB L96 语境】")],
        "yellow_sweat": [(None, "水停", "黄汗→水热【台账 L1264】")],
        "dryness": [(None, "津亏", "皮肤干燥粗糙→津亏不荣【验】")],
    },
}

# 四证 → 饮食宜忌（diet-therapy.md 体质节查表）
DIET_MAP = {
    "水证": {"宜": "甘淡利湿——薏米赤小豆粥、茯苓山药糕、冬瓜汤、白萝卜",
             "忌": "肥甘厚腻、甜食乳制品、生冷助湿、过甘",
             "src": "diet-therapy.md:52（痰湿质·太阴水证方向）"},
    "火证": {"宜": "苦寒清热利湿——绿豆薏米汤、茵陈茶、冬瓜排骨汤、苦瓜炒蛋",
             "忌": "辛辣燥热助火、肥甘厚腻助湿、酒酪臭恶",
             "src": "diet-therapy.md:57（湿热质方向）"},
    "气证": {"宜": "甘温补气——黄芪炖鸡、党参粥、山药排骨汤、大枣桂圆",
             "忌": "生冷瓜果、苦寒败胃之品、过辛耗气",
             "src": "diet-therapy.md:37（气虚质·太阴方向）"},
    "血证": {"宜": "辛温活血——山楂红糖水、当归田七炖鸡、桃仁粥、醋泡花生",
             "忌": "寒凉凝滞（冰饮、生冷）、肥腻",
             "src": "diet-therapy.md:62（血瘀质·血证方向）"},
}

# 四证 → 最具鉴别价值的问诊项（KB L257 问诊鉴别表）
INQUIRY_FOR = {
    "水证": [("小便？", "水证/热证鉴别"), ("口渴？", "津液观核心"),
             ("大便？", "太阴vs阳明")],
    "火证": [("睡眠？", "火证/阳虚鉴别"), ("口渴？", "津液观核心"),
             ("小便？", "水热鉴别")],
    "气证": [("食欲？", "胃气虚实"), ("大便？", "太阴vs阳明")],
    "血证": [("口渴？", "口燥漱水不欲咽=瘀血"), ("大便？", "太阴vs阳明"),
             ("睡眠？", "火证/阳虚鉴别")],
}

PATTERNS = ("水证", "火证", "气证", "血证")


def _bucket(rec, rules_map, key_index):
    """通用聚合：按 rules_map 把阳性体征归入桶。
    key_index：规则元组里目标键的位置（PATTERN_MAP=1 四证，FLUID_MAP=1 轴名）。"""
    from src.dimensions import DIMENSIONS
    from src.scoring import score_indicators
    import records_store

    out = {}
    for dim in DIMENSIONS:
        obs = rec.get_observation(dim)
        if not dim.is_covered(obs) or records_store._is_declared_normal(obs):
            continue
        rules_dim = rules_map.get(dim.english_name, {})
        for ind, s in score_indicators(dim, obs).items():
            if not s or s <= 0:
                continue
            for rule in rules_dim.get(ind) or []:
                values, target = rule[0], rule[key_index]
                if values is None or str(obs.get(ind, "")) in values:
                    sign = {"dim": dim.chinese_name,
                            "label": records_store.INDICATOR_LABELS.get(ind, ind),
                            "v": str(obs.get(ind, "")), "s": s,
                            "note": rule[-1], "rule": rule}
                    out.setdefault(target, []).append(sign)
                    break
    return out


def _statement(zheng, xie):
    zn, xn = sum(e["s"] for e in zheng), sum(e["s"] for e in xie)
    if not zn and not xn:
        return None
    detail = f"正虚证据 {len(zheng)} 项 {zn:g} 分 · 邪实证据 {len(xie)} 项 {xn:g} 分"
    if zn >= max(4, xn * 2):
        text = "正虚为主"
    elif xn >= max(4, zn * 2):
        text = "邪实为主"
    elif zn >= xn:
        text = "虚实夹杂，正虚为显" if xn else "正虚为主"
    else:
        text = "虚实夹杂，邪实为显"
    return {"text": text, "detail": detail, "zheng_n": zn, "xie_n": xn}


def _fluid_statement(water, depletion):
    wn, dn = sum(e["s"] for e in water), sum(e["s"] for e in depletion)
    if not wn and not dn:
        return None
    detail = f"水停证据 {len(water)} 项 {wn:g} 分 · 津亏证据 {len(depletion)} 项 {dn:g} 分"
    if wn and dn:
        text = "水饮内停，津不上承"
    elif wn:
        text = "水饮内停"
    else:
        text = "津液不足"
    return {"text": text, "detail": detail}


def build_pattern_overview(rec) -> dict:
    """当日记录的本地规则速览（四段：体质格局/四证聚类/饮食宜忌/问诊优先）。"""
    # ---- 四证聚类（兼产正邪轴）----
    pat = _bucket(rec, PATTERN_MAP, 1)
    zheng, xie = [], []
    directions = []
    for p in PATTERNS:
        signs = sorted(pat.get(p, []), key=lambda e: -e["s"])
        if not signs:
            continue
        for e in signs:
            (zheng if e["rule"][2] == "正" else xie).append(e)
        directions.append({"name": p,
                           "total": round(sum(e["s"] for e in signs), 1),
                           "signs": signs})
    directions.sort(key=lambda d: -d["total"])

    # ---- 体质格局（正邪轴 + 津液轴）----
    flu = _bucket(rec, FLUID_MAP, 1)
    constitution = None
    zx = _statement(zheng, xie)
    fs = _fluid_statement(flu.get("水停", []), flu.get("津亏", []))
    if zx or fs:
        constitution = {"zheng_xie": zx, "fluid": fs}

    # ---- 饮食宜忌（按在场四证查表）----
    diet = [{"name": d["name"], **DIET_MAP[d["name"]]} for d in directions]

    # ---- 明日问诊优先项（前两名倾向 × 未答 × 去重 ≤3）----
    inquiry_raw = rec.raw.get("inquiry") or {}
    answered = {q for q, v in inquiry_raw.items()
                if isinstance(v, dict) and v.get("asked") and v.get("answer")}
    inquiry = []
    for d in directions[:2]:
        for q, why in INQUIRY_FOR[d["name"]]:
            if q not in answered and q not in [x["q"] for x in inquiry]:
                inquiry.append({"q": q, "why": why})
            if len(inquiry) >= 3:
                break
        if len(inquiry) >= 3:
            break

    return {"directions": directions,
            "positive_n": sum(len(v) for v in pat.values()),
            "constitution": constitution,
            "diet": diet,
            "inquiry": inquiry}
