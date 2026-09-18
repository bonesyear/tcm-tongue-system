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
    # "淡红为底" 应命中「淡红」（示例文本）(正常基线 0)，而非裸「红」(7)——
    # 若最长匹配失效，裸「红」会把正常舌色误判为 7 分
    inds = score_indicators(VisionDimension.TONGUE, "淡红为底，局部偏红")
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
    # 否定词集扩充：未/没（历史 Bug 5——真实 LLM 产出常用"未见/没有"）
    assert score_indicators(VisionDimension.HEAD_FACE,
                            {"face_edema": "未见明显浮肿"})["face_edema"] == 0
    assert score_indicators(VisionDimension.EYE,
                            {"jaundice": "没有黄染"})["jaundice"] == 0
    # 窗口放宽：否定词距关键词 4 字（"无明显的浮肿"）也应被拦截
    assert score_indicators(VisionDimension.EYE,
                            {"edema": "无明显的浮肿"})["edema"] == 0


def test_fei_is_not_negation_for_abnormal_prefix():
    """"非" 不是否定词："非正常/非典型" 修饰的是"正常/典型"，
    误判为否定会把真异常漏报成正常（历史 Bug——"非正常红润" 被误否定）。
    轮次 3 起 "红润":0 入表，最长匹配会压过 "红"，故本用例改用
    "非正常偏红"（不含"红润"）继续钉住"非不否定"的意图。"""
    assert score_indicators(VisionDimension.TONGUE,
                            {"body_color": "非正常偏红"})["body_color"] == 7
    assert score_indicators(VisionDimension.EYE,
                            {"jaundice": "非典型黄染"})["jaundice"] == 4


def test_bingfei_juefei_are_true_negations():
    """"并非/绝非" 是双字真否定短语——移除裸"非"时曾把它们连带弄丢，
    导致"苔并非黄厚"被判 7 分（轮次 2 自引入的 fail-open）。"""
    assert score_indicators(VisionDimension.TONGUE,
                            {"coating_thickness": "苔并非黄厚"})["coating_thickness"] == 0
    assert score_indicators(VisionDimension.EYE,
                            {"jaundice": "巩膜绝非黄染"})["jaundice"] == 0
    assert score_indicators(VisionDimension.EYE,
                            {"jaundice": "巩膜并非黄染"})["jaundice"] == 0
    # 对照：无否定的真阳性仍计分
    assert score_indicators(VisionDimension.TONGUE,
                            {"coating_thickness": "苔黄厚"})["coating_thickness"] == 7


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
        # 轮次 3 新增指标的正常值——把"正常舌象全 0"钉在新规则上
        "coating_peeling": "无剥落",
        "coating_greasy": "不腻",
        "coating_color": "白",
        "prickles": "无点刺",
        "sublingual_color": "淡紫",
        "sublingual_thickness": "正常",
        "sublingual_petechiae": "无",
    }
    assert score(VisionDimension.TONGUE, normal) == 0.0
    inds = score_indicators(VisionDimension.TONGUE, normal)
    assert all(v == 0 for v in inds.values()), f"正常舌象各指标应全 0: {inds}"


def test_tongue_score_sparse_not_diluted():
    # 单条「青紫」只覆盖舌质颜色一项，不应被固定 8 项均值稀释为 1.2。
    # 轮次 3 起用结构化 dict 表达：sublingual_color 也收「青紫」(8)，
    # 纯文本输入会双命中变均值 9.0——"稀疏不稀释"的意图用结构化
    # 入参（Record.get_observation 产出，推荐的精确路径）表达更准确，
    # 断言强度不变（仍 == 10）
    assert score(VisionDimension.TONGUE, {"body_color": "青紫"}) == 10


def test_body_luster_not_scored():
    """方案 A：body_luster（舌质润燥，原"舌质荣枯"）已从 DIMENSION_RULES
    移除——光泽受照片光线干扰、静态照片不可判神气/荣枯，降级到辨证层，
    不再参与 score()。"""
    inds = score_indicators(VisionDimension.TONGUE, {"body_luster": "枯槁"})
    assert "body_luster" not in inds


def test_tie_break_prefers_higher_score():
    """同长度关键词命中时取分值最高者（fail-loud：宁可高估不漏估）。
    端到端实测发现："湿润偏滑" 曾因 "润":0 排在 "滑":7 之前被判 0 分，
    湿盛信号被系统性掩盖。"""
    assert score_indicators(VisionDimension.TONGUE,
                            {"coating_moisture": "湿润偏滑"})["coating_moisture"] == 7
    assert score_indicators(VisionDimension.TONGUE,
                            {"coating_moisture": "湿润"})["coating_moisture"] == 0
    # 两个异常词平局：取更高的 "燥"=8 而非 "滑"=7
    assert score_indicators(VisionDimension.TONGUE,
                            {"coating_moisture": "滑燥并见"})["coating_moisture"] == 8
    # 否定后平局不触发："燥" 被 "不" 否定，只剩 "润"=0
    assert score_indicators(VisionDimension.TONGUE,
                            {"coating_moisture": "苔润不燥"})["coating_moisture"] == 0


def test_face_luster_scoring():
    # 面部光泽：晦暗/枯槁分级
    inds = score_indicators(VisionDimension.HEAD_FACE, {"face_luster": "晦暗"})
    assert inds["face_luster"] == 5
    inds2 = score_indicators(VisionDimension.HEAD_FACE, {"face_luster": "枯槁"})
    assert inds2["face_luster"] == 8
    inds3 = score_indicators(VisionDimension.HEAD_FACE, {"face_luster": "荣润"})
    assert inds3["face_luster"] == 0


# ============================================================
# 轮次 3：评分覆盖扩展（剥落/腻腐/苔色/点刺/舌下，分值用户签认）
# ============================================================

def test_coating_peeling_scoring():
    inds = score_indicators(VisionDimension.TONGUE, {"coating_peeling": "剥落斑"})
    assert inds["coating_peeling"] == 6
    assert score_indicators(VisionDimension.TONGUE,
                            {"coating_peeling": "花剥"})["coating_peeling"] == 6
    assert score_indicators(VisionDimension.TONGUE,
                            {"coating_peeling": "剥脱"})["coating_peeling"] == 6
    assert score_indicators(VisionDimension.TONGUE,
                            {"coating_peeling": "地图舌"})["coating_peeling"] == 7
    assert score_indicators(VisionDimension.TONGUE,
                            {"coating_peeling": "镜面舌"})["coating_peeling"] == 9
    # 否定守卫："无剥落"归零
    assert score_indicators(VisionDimension.TONGUE,
                            {"coating_peeling": "无剥落"})["coating_peeling"] == 0


def test_coating_greasy_scoring():
    assert score_indicators(VisionDimension.TONGUE,
                            {"coating_greasy": "稍腻"})["coating_greasy"] == 3
    assert score_indicators(VisionDimension.TONGUE,
                            {"coating_greasy": "腻"})["coating_greasy"] == 5
    # "厚腻" 最长匹配压过单字 "腻"(5)
    assert score_indicators(VisionDimension.TONGUE,
                            {"coating_greasy": "厚腻"})["coating_greasy"] == 8
    assert score_indicators(VisionDimension.TONGUE,
                            {"coating_greasy": "腐苔"})["coating_greasy"] == 7
    # 否定守卫："不腻" 中 "腻" 被前置 "不" 拦截
    assert score_indicators(VisionDimension.TONGUE,
                            {"coating_greasy": "不腻"})["coating_greasy"] == 0


def test_coating_color_scoring():
    assert score_indicators(VisionDimension.TONGUE,
                            {"coating_color": "白"})["coating_color"] == 0
    assert score_indicators(VisionDimension.TONGUE,
                            {"coating_color": "黄"})["coating_color"] == 3
    assert score_indicators(VisionDimension.TONGUE,
                            {"coating_color": "灰"})["coating_color"] == 6
    assert score_indicators(VisionDimension.TONGUE,
                            {"coating_color": "黑"})["coating_color"] == 7
    # "灰黑" 最长匹配压过 "灰"(6)/"黑"(7)，不降级
    assert score_indicators(VisionDimension.TONGUE,
                            {"coating_color": "灰黑"})["coating_color"] == 8


def test_prickles_scoring():
    assert score_indicators(VisionDimension.TONGUE,
                            {"prickles": "点刺"})["prickles"] == 5
    assert score_indicators(VisionDimension.TONGUE,
                            {"prickles": "芒刺"})["prickles"] == 6
    assert score_indicators(VisionDimension.TONGUE,
                            {"prickles": "无点刺"})["prickles"] == 0


def test_sublingual_scoring():
    # 舌下络脉颜色
    assert score_indicators(VisionDimension.TONGUE,
                            {"sublingual_color": "淡紫"})["sublingual_color"] == 0
    assert score_indicators(VisionDimension.TONGUE,
                            {"sublingual_color": "紫暗"})["sublingual_color"] == 6
    assert score_indicators(VisionDimension.TONGUE,
                            {"sublingual_color": "青紫"})["sublingual_color"] == 8
    # 舌下络脉粗细
    assert score_indicators(VisionDimension.TONGUE,
                            {"sublingual_thickness": "增粗"})["sublingual_thickness"] == 5
    assert score_indicators(VisionDimension.TONGUE,
                            {"sublingual_thickness": "怒张"})["sublingual_thickness"] == 7
    # 舌下络脉瘀点（复用 PETECHIAE_MAP）
    assert score_indicators(VisionDimension.TONGUE,
                            {"sublingual_petechiae": "散在"})["sublingual_petechiae"] == 5
    assert score_indicators(VisionDimension.TONGUE,
                            {"sublingual_petechiae": "无"})["sublingual_petechiae"] == 0


def test_body_color_hongrun_not_misjudged():
    """轮次 3 词表缺口修补：正常描述「红润」不再靠单字「红」误报 7 分
    （「红润」最长匹配压过「红」）；真正的偏红仍判 7。"""
    assert score_indicators(VisionDimension.TONGUE,
                            {"body_color": "红润"})["body_color"] == 0
    assert score_indicators(VisionDimension.TONGUE,
                            {"body_color": "舌质红润，苔薄白"})["body_color"] == 0
    # 对照：裸「红」仍是 7
    assert score_indicators(VisionDimension.TONGUE,
                            {"body_color": "红"})["body_color"] == 7


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
        "body_color": "淡红为底，局部偏红",
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


def test_non_tongue_score_mean_is_always_float():
    """轮次 5：非舌诊维度 score()（即周报 mean）恒为 float——
    round(int, 1) 在 Python 3 返回 int，曾让周报 JSON 出现
    "mean": 0 与 "max": 0.0 并列。只改类型，数值语义不变（0 == 0.0）。"""
    zero = score(VisionDimension.HEAD_FACE, "面色正常 红润有光泽")
    assert isinstance(zero, float)
    assert zero == 0
    positive = score(VisionDimension.HEAD_FACE, "面色红如妆")
    assert isinstance(positive, float)
    assert positive == 9


# ============================================================
# 轮次 7：舌体胖瘦词表补漏（2026-09-18 实测 "偏胖" 漏判为 0，
# 新增 4 词条，分值经用户签认）
# ============================================================

def test_body_size_new_intermediate_terms():
    """4 个新词各自命中签认分值：偏胖/偏瘦=4（中间态），稍胖/略瘦=3。"""
    assert score_indicators(VisionDimension.TONGUE,
                            {"body_size": "偏胖"})["body_size"] == 4
    assert score_indicators(VisionDimension.TONGUE,
                            {"body_size": "偏瘦"})["body_size"] == 4
    assert score_indicators(VisionDimension.TONGUE,
                            {"body_size": "稍胖"})["body_size"] == 3
    assert score_indicators(VisionDimension.TONGUE,
                            {"body_size": "略瘦"})["body_size"] == 3


def test_body_size_pianpangda_not_downgraded():
    """平局不降级："偏胖大" 中 "胖大"(7) 与 "偏胖"(4) 同长度平局取高者，
    仍为 7——硬约束偏胖 ≤ 7，≥8 会翻转取偏胖（独立复验实测红线）。"""
    assert score_indicators(VisionDimension.TONGUE,
                            {"body_size": "偏胖大"})["body_size"] == 7


def test_body_size_negation_guard():
    """否定守卫：前置 "无明显" 与后置 "不明显" 均归零。"""
    assert score_indicators(VisionDimension.TONGUE,
                            {"body_size": "无明显偏胖"})["body_size"] == 0
    assert score_indicators(VisionDimension.TONGUE,
                            {"body_size": "偏胖不明显"})["body_size"] == 0
