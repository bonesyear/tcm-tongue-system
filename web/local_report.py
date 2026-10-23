"""本地规则「四证倾向速览」——未启用辨证模型时的报告区内容。

把当日记录的阳性体征按 水/火/气/血 四证方向做**确定性聚类**：
这是证据清单的聚合视图，**不是辨证结论**——六病归属、病机合成、
方药建议必须走辨证 LLM（见 adaptive_analysis_prompt.md）。

指标→方向映射见 PATTERN_MAP：只收有出处支撑的映射（宁缺毋滥），
逐条标注来源——【KB L##】= knowledge_base/diagnostics/smartphone-visual-diagnostics.md
行号（四证映射节）；【台账】= docs/VOCAB_PROVENANCE_2026-10-16.md；
【验】= 经验映射，无书籍直接出处。
"""

# PATTERN_MAP[dim_english][indicator] = [(match_values|None, 四证, 出处注记), …]
# match_values 为 None 时任意阳性措辞都归入；否则仅当观察值命中集合时归入。
PATTERN_MAP = {
    "tongue": {
        "body_color": [({"红", "红绛"}, "火证", "舌红苔黄燥→火【KB L51】"),
                       ({"淡白"}, "气证", "舌淡嫩薄白→气【KB L52】"),
                       ({"紫暗"}, "血证", "舌紫暗瘀斑→血【KB L53】")],
        "body_size": [(None, "水证", "舌淡胖齿痕苔滑→水【KB L50】")],
        "tooth_marks": [(None, "水证", "舌淡胖齿痕苔滑→水【KB L50】")],
        "petechiae": [(None, "血证", "舌紫暗瘀斑→血【KB L53】")],
        "coating_color": [({"黄", "黄腻"}, "火证", "舌红苔黄燥→火【KB L51】")],
        "coating_moisture": [({"偏干", "干", "燥"}, "火证", "苔燥→热盛津亏【KB L51】")],
        "coating_greasy": [(None, "水证", "苔滑腻→水湿内停【KB L50 语境】")],
        "coating_thickness": [(None, "水证", "苔厚→湿浊偏盛【验】")],
        "coating_peeling": [(None, "气证", "剥落苔→胃气虚【验】")],
        "sublingual_color": [(None, "血证", "舌下络脉色深→血行不利【KB L53 语境】")],
        "sublingual_thickness": [(None, "血证", "舌下络脉粗张→血行不利【KB L53 语境】")],
        "sublingual_varicosity": [(None, "血证", "舌下络脉迂曲→血行不利【KB L53 语境】")],
        "sublingual_petechiae": [(None, "血证", "舌下瘀点→血行不利【KB L53 语境】")],
    },
    "head_face": {
        "face_color": [({"红赤"}, "火证", "面赤（缘缘正赤）→火【KB L95】"),
                       ({"黄", "黄肿"}, "水证", "面黄/黄肿→水【KB L96】"),
                       ({"晦暗", "萎黄", "淡白", "苍白"}, "血证",
                        "面萎黄/苍白→伤营【KB L97】【台账】")],
        "face_edema": [(None, "水证", "面肿→津液不化【KB L96】")],
        "lip_color": [({"淡白", "苍白"}, "血证", "唇淡白→血少【KB L97】"),
                      ({"紫暗"}, "血证", "唇紫暗→瘀血【KB L99】"),
                      ({"红赤", "鲜红"}, "火证", "唇鲜红→热盛【KB L99 语境】")],
        "nose_flare": [(None, "气证", "鼻翼煽动→肺气不利【KB L100】")],
    },
    "eye": {
        "redness": [(None, "火证", "目赤→上焦郁火【KB L134】")],
        "jaundice": [(None, "火证", "黄染→湿热/黄疸方向【验】")],
        "edema": [(None, "水证", "目下卧蚕/睑肿→水【KB L135】")],
        "dark_orbit": [(None, "血证", "两目黯黑→干血【KB L136】")],
        "lower_lid": [(None, "血证", "下睑淡白→血少【台账】")],
    },
    "ear": {
        "color": [({"红赤"}, "火证", "耳色红赤→少阳郁火【KB L134 语境】")],
    },
    "hand": {
        "palm_color": [({"淡白", "偏淡白"}, "血证", "掌色淡白→血少【台账】")],
        "nail_color": [({"淡白"}, "血证", "甲床淡白→血少【台账】"),
                       ({"紫暗"}, "血证", "甲紫暗→瘀【KB L99 语境】")],
    },
    "skin": {
        "color": [({"黄如橘皮"}, "火证", "阳黄→湿热【验】"),
                  ({"烟熏"}, "水证", "阴黄→寒湿【验】"),
                  ({"萎黄"}, "血证", "萎黄→血少不荣【验】")],
        "cuo": [(None, "血证", "肌肤甲错→干血/伤营【台账】")],
        "yellow_sweat": [(None, "水证", "黄汗→水热【台账 L1264】")],
        "edema": [(None, "水证", "浮肿→水饮外溢【KB L96 语境】")],
        # dryness（皮肤干燥/粗糙）：津亏方向不唯一（可热可虚），宁缺毋滥不映射
    },
}

PATTERNS = ("水证", "火证", "气证", "血证")


def build_pattern_overview(rec) -> dict:
    """阳性体征 → 四证倾向聚类。

    返回 {"directions": [{name, total, signs:[{dim,label,v,s,note}]}…按总分降序],
          "positive_n": 归入的阳性体征总数}
    无任何归入项时 directions 为空（调用方显示「未见阳性倾向」）。
    参考项字段（REF_FIELDS，无分值）与未映射指标一律不参与（宁缺毋滥）。
    """
    from src.dimensions import DIMENSIONS
    from src.scoring import score_indicators
    import records_store

    buckets = {p: [] for p in PATTERNS}
    for dim in DIMENSIONS:
        obs = rec.get_observation(dim)
        if not dim.is_covered(obs) or records_store._is_declared_normal(obs):
            continue
        rules_dim = PATTERN_MAP.get(dim.english_name, {})
        for ind, s in score_indicators(dim, obs).items():
            if not s or s <= 0:
                continue
            rules = rules_dim.get(ind)
            if not rules:
                continue
            v = str(obs.get(ind, ""))
            for values, pattern, note in rules:
                if values is None or v in values:
                    buckets[pattern].append({
                        "dim": dim.chinese_name,
                        "label": records_store.INDICATOR_LABELS.get(ind, ind),
                        "v": v, "s": s, "note": note,
                    })
                    break
    directions = []
    for p in PATTERNS:
        signs = sorted(buckets[p], key=lambda e: -e["s"])
        if signs:
            directions.append({"name": p,
                               "total": round(sum(e["s"] for e in signs), 1),
                               "signs": signs})
    directions.sort(key=lambda d: -d["total"])
    return {"directions": directions,
            "positive_n": sum(len(ev) for ev in buckets.values())}
