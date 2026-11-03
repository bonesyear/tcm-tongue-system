"""派生输入指纹与规则版本测试。"""
from src.derived import observation_input_hash
from src.record import DailyRecord


def test_input_hash_is_stable_normalized_and_changes_with_observation():
    raw = {
        "date": "2026-06-25",
        "observations": {"tongue": {"body": {"color": "淡红"}}},
        "inquiry": {},
    }
    rec = DailyRecord(raw)

    assert observation_input_hash(rec) == observation_input_hash(rec)
    changed = DailyRecord({
        "date": "2026-06-25",
        "observations": {"tongue": {"body": {"color": "红"}}},
        "inquiry": {},
    })
    assert observation_input_hash(rec) != observation_input_hash(changed)


def test_input_hash_uses_normalized_observations_not_shape_names():
    shape_b = DailyRecord({
        "date": "2026-06-25",
        "observations": {"tongue": {"body": {"color": "淡红"}}},
        "inquiry": {},
    })
    shape_a = DailyRecord({
        "date": "2026-06-25",
        "vision_analysis": {"舌诊": {"舌质颜色": "淡红"}},
        "inquiry": {},
    })

    assert observation_input_hash(shape_b) == observation_input_hash(shape_a)


def test_input_hash_unifies_legacy_aliases():
    legacy_jaundice = DailyRecord({"eye": {"sclera_color": "黄染轻度"}})
    canonical_jaundice = DailyRecord({"observations": {
        "eye": {"scleral_jaundice": "黄染轻度"},
    }})
    assert observation_input_hash(legacy_jaundice) == observation_input_hash(canonical_jaundice)

    legacy_wocan = DailyRecord({"observations": {
        "head_face": {"face": {"edema": "卧蚕"}}, "eye": {},
    }})
    canonical_wocan = DailyRecord({"observations": {
        "head_face": {"face": {}}, "eye": {"eyelid_edema": "卧蚕"},
    }})
    assert observation_input_hash(legacy_wocan) == observation_input_hash(canonical_wocan)


def test_input_hash_changes_with_observation_metadata_and_declarations():
    base = DailyRecord({"observations": {}})
    with_meta = DailyRecord({
        "observations": {},
        "observation_meta": {"tongue.body.color": {
            "source": "manual", "method": "manual", "raw": "淡红",
            "certainty": "user_confirmed", "evidence": {}, "value": "淡红",
        }},
    })
    with_declaration = DailyRecord({
        "observations": {},
        "declarations": [{"kind": "declared_normal", "dimension": "tongue",
                          "part": "舌面", "reason": "用户确认"}],
    })
    assert observation_input_hash(base) != observation_input_hash(with_meta)
    assert observation_input_hash(base) != observation_input_hash(with_declaration)
