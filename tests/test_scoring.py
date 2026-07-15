"""Scoring module 测试：打分命中、误匹配不出现。"""
from src.dimensions import VisionDimension
from src.scoring import score, score_indicators


def test_tongue_score_positive_on_red_yellow():
    # "舌红苔黄" 应给出 >0 的偏离度（舌质颜色「红」命中）
    assert score(VisionDimension.TONGUE, "舌红苔黄") > 0


def test_tongue_score_on_clean_keywords():
    # 精确枚举值
    assert score(VisionDimension.TONGUE, "舌质红绛苔黄厚") > 0
    # 舌体胖大应高分
    inds = score_indicators(VisionDimension.TONGUE, "舌体胖大")
    assert inds["body_size"] == 7


def test_longest_match_avoids_ambiguity():
    # "淡红为底" 应命中「淡红」(正常基线 0)，而非裸「红」(7)——
    # 若最长匹配失效，裸「红」会把正常舌色误判为 7 分
    inds = score_indicators(VisionDimension.TONGUE, "淡红为底，花剥区偏红")
    assert inds["body_color"] == 0
    # 对照：真正的偏红（无「淡红」在场）应命中「红」
    assert score_indicators(VisionDimension.TONGUE, "舌质偏红")["body_color"] == 7


def test_no_false_match_red_ruyang():
    # 戴阳「红如妆」应高分
    assert score(VisionDimension.HEAD_FACE, "面色红如妆") == 9
    # 普通红润/正常不应误命中「红如妆」
    assert score(VisionDimension.HEAD_FACE, "面色正常 红润有光泽") == 0
    assert score(VisionDimension.HEAD_FACE, "面色红赤") == 0  # 头面诊未定义红赤规则


def test_negation_guard_on_edema():
    # "无明显浮肿" 不应命中「明显浮肿」
    inds = score_indicators(VisionDimension.HEAD_FACE, "面部无明显浮肿")
    assert inds["face_edema"] == 0
    # 真阳性
    inds2 = score_indicators(VisionDimension.HEAD_FACE, "面部明显浮肿")
    assert inds2["face_edema"] == 4


def test_negation_guard_on_jaundice():
    # "无黄染" 不应命中黄染
    inds = score_indicators(VisionDimension.EYE, "巩膜无黄染")
    assert inds["jaundice"] == 0
    # 真阳性
    inds2 = score_indicators(VisionDimension.EYE, "巩膜黄染明显")
    assert inds2["jaundice"] == 8


def test_negation_guard_on_eye_edema():
    # EYE edema: "无明显浮肿" 中 "无" 距 "浮肿" 3 字，
    # 2 字窗口会漏看而误命中「浮肿」——扩大窗口后应被否定守卫拦截
    inds = score_indicators(VisionDimension.EYE, "眼睑无明显浮肿")
    assert inds["edema"] == 0
    # 真阳性
    inds2 = score_indicators(VisionDimension.EYE, "眼睑浮肿明显")
    assert inds2["edema"] > 0


def test_negation_guard_extended_words():
    # 否定词集扩充：未/没/非（历史 Bug 5——真实 LLM 产出常用"未见/没有"）
    assert score_indicators(VisionDimension.HEAD_FACE,
                            {"face_edema": "未见明显浮肿"})["face_edema"] == 0
    assert score_indicators(VisionDimension.EYE,
                            {"jaundice": "没有黄染"})["jaundice"] == 0
    # 窗口放宽：否定词距关键词 4 字（"无明显的浮肿"）也应被拦截
    assert score_indicators(VisionDimension.EYE,
                            {"edema": "无明显的浮肿"})["edema"] == 0


def test_negation_guard_clause_boundary():
    # 否定词只在同一小句内生效："无瘀点，散在瘀斑" 的"无"不应跨逗号抹掉"散在"
    inds = score_indicators(VisionDimension.TONGUE, {"petechiae": "无瘀点，散在瘀斑"})
    assert inds["petechiae"] == 5


def test_intensifier_feichang_not_negation():
    # "非常" 是程度副词，其中的"非"不应触发否定守卫
    inds = score_indicators(VisionDimension.EYE, {"edema": "非常明显的浮肿"})
    assert inds["edema"] > 0


def test_palm_not_warm_scores_as_cool():
    # "不温" 语义上等同"凉"，应得分而非被否定守卫抹成 0
    assert score_indicators(VisionDimension.HAND, {"palm_temp": "不温"})["palm_temp"] == 4
    assert score_indicators(VisionDimension.HAND, {"palm_temp": "温"})["palm_temp"] == 0


def test_all_occurrences_checked_not_just_first():
    """对抗验证发现：只查关键词首个出现位置会吞掉后文的真阳性。
    "舌质不红，但舌边红" 中首个"红"被否定，第二个"红"必须计分。"""
    inds = score_indicators(VisionDimension.TONGUE, {"body_color": "舌质不红，但舌边红"})
    assert inds["body_color"] == 7
    inds2 = score_indicators(VisionDimension.EYE, {"redness": "无充血，内眦充血明显"})
    assert inds2["redness"] == 6


def test_post_negation_guard():
    """后置否定："浮肿不明显""黄染未见" 等"关键词+否定"句式不应计分。"""
    assert score_indicators(VisionDimension.EYE, {"edema": "浮肿不明显"})["edema"] == 0
    assert score_indicators(VisionDimension.EYE, {"jaundice": "黄染未见"})["jaundice"] == 0
    # 不误伤：程度加重、"厥冷不温"连写（"不温"非否定短语）
    assert score_indicators(VisionDimension.EYE, {"edema": "浮肿明显加重"})["edema"] > 0
    assert score_indicators(VisionDimension.HAND, {"palm_temp": "厥冷不温"})["palm_temp"] == 8


def test_normal_tongue_scores_zero():
    """基线回归（历史 Bug 4）：完全正常的舌象综合偏离度必须为 0，
    不得因「淡红/润」的历史基线 5 而被抬到关注线。"""
    normal = {
        "body_color": "淡红",
        "coating_thickness": "薄白",
        "coating_moisture": "润",
        "tooth_marks": "无",
        "petechiae": "无",
        "sublingual_varicosity": "无",
        "fissure": "无",
        "body_size": "适中",
        "body_luster": "荣润",
    }
    assert score(VisionDimension.TONGUE, normal) == 0.0
    inds = score_indicators(VisionDimension.TONGUE, normal)
    assert all(v == 0 for v in inds.values()), f"正常舌象各指标应全 0: {inds}"


def test_tongue_score_sparse_not_diluted():
    # 单条「青紫」只覆盖舌质颜色一项，不应被固定 8 项均值稀释为 1.2
    assert score(VisionDimension.TONGUE, "青紫") == 10


def test_body_luster_scoring():
    # 舌质荣枯：枯槁高分、荣润正常
    inds = score_indicators(VisionDimension.TONGUE, {"body_luster": "枯槁"})
    assert inds["body_luster"] == 8
    inds2 = score_indicators(VisionDimension.TONGUE, {"body_luster": "少泽"})
    assert inds2["body_luster"] == 5
    inds3 = score_indicators(VisionDimension.TONGUE, {"body_luster": "荣润"})
    assert inds3["body_luster"] == 0


def test_face_luster_scoring():
    # 面部光泽：晦暗/枯槁分级
    inds = score_indicators(VisionDimension.HEAD_FACE, {"face_luster": "晦暗"})
    assert inds["face_luster"] == 5
    inds2 = score_indicators(VisionDimension.HEAD_FACE, {"face_luster": "枯槁"})
    assert inds2["face_luster"] == 8
    inds3 = score_indicators(VisionDimension.HEAD_FACE, {"face_luster": "荣润"})
    assert inds3["face_luster"] == 0


def test_sclera_color_scoring():
    # 巩膜颜色：黄染/苍白/蓝巩膜
    inds = score_indicators(VisionDimension.EYE, {"sclera_color": "蓝巩膜"})
    assert inds["sclera_color"] == 8
    inds2 = score_indicators(VisionDimension.EYE, {"sclera_color": "黄染"})
    assert inds2["sclera_color"] == 7
    inds3 = score_indicators(VisionDimension.EYE, {"sclera_color": "苍白"})
    assert inds3["sclera_color"] == 5


def test_skin_normal_is_zero():
    # 皮肤各项正常 → 不应误命中
    assert score(VisionDimension.SKIN, "肤色正常 无甲错 无黄汗 无水肿 无干燥") == 0


def test_score_bounded_zero_to_ten():
    for dim in VisionDimension:
        s = score(dim, "目赤充血 巩膜黄染明显 全身浮肿 龟裂 焦黑 厥冷")
        assert 0.0 <= s <= 10.0


def test_score_with_structured_dict_input():
    # Record.get_observation 返回的 {指标: 文本} 结构可被直接打分
    obs = {
        "body_color": "淡红为底，花剥区偏红",
        "coating_thickness": "白厚",
        "coating_moisture": "润",
        "tooth_marks": "无",
        "petechiae": "无",
        "sublingual_varicosity": "无",
        "fissure": "无",
        "body_size": "偏胖大",
    }
    inds = score_indicators(VisionDimension.TONGUE, obs)
    assert inds["body_color"] == 0         # 淡红 = 正常基线
    assert inds["coating_moisture"] == 0   # 润 = 正常基线
    assert inds["coating_thickness"] == 7  # 白厚 命中
    assert inds["body_size"] == 7          # 胖大 命中
    # 整体舌诊偏离度 > 0（白厚 7 + 胖大 7 → 均值 7.0，正常项不抬分）
    assert score(VisionDimension.TONGUE, obs) == 7.0


def test_structured_input_avoids_cross_field_false_match():
    # ecchymosis 字段为「无」，即便别处字段出现「散在」也不应误命中瘀斑
    obs = {
        "petechiae": "无",
        "coating_thickness": "白厚",
        "body_color": "淡红",
        "coating_moisture": "润",
        "tooth_marks": "无",
        "sublingual_varicosity": "无",
        "fissure": "无",
        "body_size": "适中",
    }
    inds = score_indicators(VisionDimension.TONGUE, obs)
    assert inds["petechiae"] == 0
