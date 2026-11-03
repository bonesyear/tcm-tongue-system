"""预警三态与组合证据（纯核心，不依赖 Flask）。"""
from src.alerts import danger_flags_for, evaluate_alert


def test_daiyang_screening_vs_critical_rule():
    screening = evaluate_alert("daiyang", {
        "head_face": {"face": {"color": "红如妆"}},
    })
    assert screening.state == "triggered"
    assert screening.kind == "screening"
    assert screening.matched_clauses == ("面红如妆",)
    assert screening.missing_clauses == ("手足厥逆",)

    critical = evaluate_alert("daiyang", {
        "head_face": {"face": {"color": "红如妆"}},
        "inquiry": {"手足温凉": {"asked": True, "answer": "厥冷（冰冷）"}},
    })
    assert critical.state == "triggered"
    assert critical.kind == "critical_rule"
    assert critical.matched_clauses == ("面红如妆", "手足厥逆")
    assert critical.missing_clauses == ()


def test_daiyang_unknown_is_not_not_triggered():
    unknown = evaluate_alert("daiyang", {})
    assert unknown.state == "unknown"
    assert unknown.kind == "critical_rule"
    negative = evaluate_alert("daiyang", {
        "head_face": {"face": {"color": "无红如妆"}},
    })
    assert negative.state == "not_triggered"
    assert negative.missing_clauses == ()
    cold_only = evaluate_alert("daiyang", {
        "inquiry": {"手足温凉": {"asked": True, "answer": "厥冷（冰冷）"}},
    })
    assert cold_only.state == "unknown"
    assert cold_only.kind == "critical_rule"
    assert cold_only.matched_clauses == ("手足厥逆",)


def test_danger_flags_keep_unknown_separate():
    result = danger_flags_for({})
    assert "daiyang" in result["unknown"]
    assert "daiyang" not in result["not_triggered"]
    evaluation = next(e for e in result["evaluations"] if e["rule_id"] == "daiyang")
    assert evaluation["state"] == "unknown"
    assert evaluation["kind"] == "critical_rule"


def test_acute_jaundice_requires_eye_plus_skin_or_context():
    eye_only = evaluate_alert("acute_jaundice", {
        "eye": {"scleral_jaundice": "黄染轻度"},
    })
    assert eye_only.state == "triggered"
    assert eye_only.kind == "screening"
    assert "巩膜黄染" in eye_only.matched_clauses
    assert "皮肤黄如橘皮" in eye_only.missing_clauses

    skin_only = evaluate_alert("acute_jaundice", {
        "skin": {"color": "黄如橘皮"},
    })
    assert skin_only.kind == "screening"
    assert "巩膜黄染" in skin_only.missing_clauses

    both = evaluate_alert("acute_jaundice", {"observations": {
        "eye": {"scleral_jaundice": "黄染明显"},
        "skin": {"color": "黄如橘皮，善色"},
    }})
    assert both.kind == "critical_rule"
    assert both.missing_clauses == ()

    context = evaluate_alert("acute_jaundice", {
        "eye": {"jaundice": "黄染"},
        "context": {"主诉": "黄疸"},
    })
    assert context.kind == "critical_rule"


def test_mirror_tongue_prefers_structured_evidence():
    structured = evaluate_alert("mirror_tongue", {"observations": {
        "tongue": {"coating": {"peeling": "镜面"}},
    }})
    assert structured.state == "triggered"
    assert structured.kind == "critical_rule"
    assert structured.matched_clauses == ("镜面舌形态",)
    assert structured.evidence[0].source == "tongue.coating_peeling"

    fallback = evaluate_alert("mirror_tongue", {
        "tongue": {"note": "舌面光亮如镜"},
    })
    assert fallback.state == "triggered"
    assert fallback.kind == "screening"
    assert fallback.missing_clauses


def test_mirror_tongue_explicit_critical_sign():
    result = evaluate_alert("mirror_tongue", {
        "tongue": {"critical_signs": "镜面舌"},
    })
    assert result.state == "triggered"
    assert result.kind == "critical_rule"
    assert result.evidence[0].source == "tongue.critical_signs"


def test_tongue_critical_uses_textbook_clauses_not_purple_required():
    from src.alerts import DANGER_FLAGS
    assert "紫暗" not in DANGER_FLAGS["tongue_critical"]["sign"]
    partial = evaluate_alert("tongue_critical", {"tongue": {
        "body": {"color": "紫暗"}, "coating": {"thickness": "焦黑"},
    }})
    assert partial.kind == "screening"
    assert "舌质干裂起刺" in partial.missing_clauses
    full = evaluate_alert("tongue_critical", {"tongue": {
        "body": {"luster": "干裂起刺"}, "coating": {"thickness": "焦黑"},
    }})
    assert full.kind == "critical_rule"


def test_all_remaining_critical_rules_have_working_evidence_paths():
    cases = {
        "skin_cold": {"inquiry": {"手足温凉": "触之冰冷"}, "context": {"脉诊": "脉微"}},
        "flesh_wasted": {"skin": {"appearance": "大肉已脱，大骨陷下"}},
        "tongue_rigid": {"tongue": {"critical_signs": "舌强语謇"}},
        "wind_stroke": {"inquiry": {"语言": "口不能言", "运动": "身体不收"}},
        "throat_erosion": {"inquiry": {"主诉": "默默欲眠，恶闻食臭，面目乍赤、乍黑、乍白，蚀喉声嗄"}},
        "yangming_critical": {"inquiry": {"主诉": "神昏谵语，循衣摸床，微喘直视"}},
        "collapse_yang": {"inquiry": {"主诉": "神识昏昧", "汗出时间特征？": "绝汗(大汗淋漓如油)"}},
    }
    for rule_id, raw in cases.items():
        result = evaluate_alert(rule_id, raw)
        assert (result.state, result.kind) == ("triggered", "critical_rule"), rule_id
    for rule_id, name in [
        ("pigkidney_tongue", "猪腰舌"), ("sandy_tongue", "砂皮舌"),
        ("litchi_tongue", "干荔舌"), ("persimmon_tongue", "火柿舌"),
        ("ochre_tongue", "赭黑舌"), ("thin_coatless", "瘦薄无苔舌"),
        ("retracted_tongue", "囊缩卷舌"), ("blue_tongue", "蓝舌"),
    ]:
        result = evaluate_alert(rule_id, {"tongue": {"critical_signs": name}})
        assert (result.state, result.kind) == ("triggered", "critical_rule"), rule_id


def test_flag_pattern_and_provenance_contract():
    from src.alerts import ALERT_RULES, DANGER_FLAGS, DANGER_PATTERNS, DANGER_PROVENANCE
    from src.indicators import JINGFANG_SHA256, TEXTBOOK_SHA256
    assert set(DANGER_FLAGS) == set(DANGER_PATTERNS) == set(ALERT_RULES)
    assert set(DANGER_PROVENANCE) == set(DANGER_FLAGS)
    for rule_id, refs in DANGER_PROVENANCE.items():
        assert refs, rule_id
        for ref in refs:
            assert set(ref) == {"source_id", "source_sha256", "keyword", "locator", "quote"}
            assert ref["keyword"] and ref["locator"] and ref["quote"]
            if ref["source_id"] == "jingfang":
                assert ref["source_sha256"] == JINGFANG_SHA256
            elif ref["source_id"] == "tcm-textbook":
                assert ref["source_sha256"] == TEXTBOOK_SHA256
            else:
                raise AssertionError(f"未声明出处类型: {rule_id}/{ref['source_id']}")


def test_every_legacy_pattern_still_recalls_screening():
    from src.alerts import DANGER_PATTERNS
    for rule_id, patterns in DANGER_PATTERNS.items():
        for pattern in (patterns if isinstance(patterns, tuple) else (patterns,)):
            result = evaluate_alert(rule_id, {"tongue": {"note": pattern}})
            assert result.state == "triggered", (rule_id, pattern)
            assert result.kind in ("screening", "critical_rule")


def test_mirror_tongue_pattern_no_false_positive():
    from src.danger import detect_danger
    assert detect_danger({"tongue": {"coating": {"peeling": "局部剥落"}}}) == []
    assert detect_danger({"tongue": {"coating": {"peeling": "光剥无苔"}}}) == ["mirror_tongue"]


def test_new_danger_patterns_detected():
    from src.danger import detect_danger
    assert detect_danger({"skin": {"note": "微喘直视"}}) == ["yangming_critical"]
    assert detect_danger({"skin": {"sweat": "冷汗如油"}}) == ["collapse_yang"]


def test_detect_danger_negation_guard():
    from src.danger import detect_danger
    assert detect_danger({"tongue": {"coating": {"peeling": "局部无苔"}}}) == []
    assert detect_danger({"skin": {"sweat": "无冷汗"}}) == []
    assert detect_danger({"tongue": {"coating": {"peeling": "光剥无苔"}}}) == ["mirror_tongue"]


def test_critical_tongue_flags_detected():
    from src.danger import detect_danger
    assert detect_danger({"tongue": {"body": {"texture": "砂皮"}}}) == ["sandy_tongue"]
    assert detect_danger({"tongue": {"note": "未见砂皮样改变"}}) == []
    assert detect_danger({"tongue": {"body": {"color": "赭黑"}}}) == ["ochre_tongue"]


def test_collapse_yang_detects_juehan_tuple_pattern():
    from src.danger import detect_danger
    assert detect_danger({"skin": {"sweat": "冷汗如油"}}) == ["collapse_yang"]
    assert detect_danger({"inquiry": {"汗出时间特征？": "绝汗(大汗淋漓如油)"}}) == ["collapse_yang"]


def test_detect_danger_no_cross_field_negation_bleed():
    from src.danger import detect_danger
    assert detect_danger({"inquiry": {
        "有汗or无汗？": "无汗", "汗出时间特征？": "绝汗(大汗淋漓如油)",
    }}) == ["collapse_yang"]
    assert "tongue_rigid" in detect_danger({"tongue": {"prickles": "无", "dynamics": "强硬"}})
    assert detect_danger({"skin": {"sweat": "无冷汗"}}) == []


def test_mirror_tongue_detectable_via_closed_vocab():
    from src.danger import detect_danger
    assert detect_danger({"tongue": {"coating": {"peeling": "镜面"}}}) == ["mirror_tongue"]
    assert detect_danger({"tongue": {"coating": {"peeling": "局部剥落"}}}) == []
    assert detect_danger({"tongue": {"coating": {"peeling": "局部无苔"}}}) == []


def test_sign_texts_match_textbook():
    from src.danger import DANGER_FLAGS
    assert DANGER_FLAGS["tongue_rigid"]["sign"] == "舌体强直，转动不灵，且语言謇涩"
    assert "深绛无苔而光亮如镜" in DANGER_FLAGS["mirror_tongue"]["sign"]
