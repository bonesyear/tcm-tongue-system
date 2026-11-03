"""观察、声明与采集能力（纯核心，不依赖 Flask）。"""
import pytest

from src.dimensions import VisionDimension as V
from src.observations import (
    Declaration, Observation, capture_observation, split_coating_text,
)


def test_sublingual_absolute_measurement_requires_scale():
    unknown = capture_observation(
        V.TONGUE, "sublingual_thickness", "3mm",
        source="vision", method="photo", evidence={"has_scale": False})
    assert isinstance(unknown, Observation)
    assert unknown.certainty == "unknown"
    assert unknown.normalized == ""
    assert unknown.raw == "3mm"
    assert unknown.to_meta()["method"] == "photo"

    measured = capture_observation(
        V.TONGUE, "sublingual_thickness", "3mm",
        source="manual", method="measurement", evidence={"has_scale": True})
    assert measured.certainty == "user_confirmed"
    assert measured.normalized == "3mm"
    assert measured.to_meta()["raw"] == "3mm"


def test_static_photo_cannot_produce_dynamic_or_palpation_facts():
    with pytest.raises(ValueError, match="动态|视频"):
        capture_observation(V.TONGUE, "body_dynamics", "强硬",
                            source="vision", method="photo")
    with pytest.raises(ValueError, match="触诊|自陈"):
        capture_observation(V.SKIN, "edema", "凹陷",
                            source="vision", method="photo")
    with pytest.raises(ValueError, match="触诊|自陈"):
        capture_observation(V.HAND, "palm_temp", "厥冷",
                            source="vision", method="photo")


def test_lower_lid_requires_exposure_and_manual_legal_source():
    unknown = capture_observation(V.EYE, "lower_lid", "淡白",
                                  source="vision", method="photo",
                                  evidence={"exposed": False})
    assert unknown.certainty == "unknown"
    assert unknown.normalized == ""
    legal = capture_observation(V.EYE, "lower_lid", "淡白",
                                source="manual", method="manual",
                                evidence={"exposed": True})
    assert legal.normalized == "淡白"


def test_composite_coating_split_preserves_scoring_aliases_and_raw():
    fields = split_coating_text("白厚腻苔，偏干，苔少，偏布一侧")
    assert fields == {
        "color": "白", "thickness": "厚腻", "moisture": "偏干",
        "greasy": "厚腻", "amount": "苔少", "distribution": "偏布一侧",
    }
    assert split_coating_text("薄黄润苔") == {
        "color": "黄", "thickness": "薄黄", "moisture": "润",
    }
    assert split_coating_text("镜面") == {"peeling": "镜面"}


def test_declaration_is_not_an_observation():
    declaration = Declaration("declared_normal", "skin", "皮肤", "用户确认")
    assert declaration.to_dict() == {
        "kind": "declared_normal", "dimension": "skin",
        "part": "皮肤", "reason": "用户确认",
    }
    with pytest.raises(ValueError):
        Declaration("unknown-kind", "skin")


def test_mapping_splits_composite_and_keeps_source_raw():
    import os
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "web"))
    from wizard_store import map_observation_with_metadata
    node, unmapped, observations = map_observation_with_metadata(
        "舌面", {"复合舌苔": "白厚腻苔，偏干", "舌质颜色": "淡红"},
        source="vision", method="photo")
    assert unmapped == []
    assert node["coating"]["color"] == "白"
    assert node["coating"]["thickness"] == "厚腻"
    assert node["coating"]["moisture"] == "偏干"
    assert node["body"]["color"] == "淡红"
    meta = {item.path: item.to_meta() for item in observations}
    assert meta["tongue.coating.thickness"]["raw"] == "白厚腻苔，偏干"
    assert meta["tongue.coating.thickness"]["value"] == "厚腻"
    assert meta["tongue.coating.thickness"]["method"] == "photo"


def test_photo_dynamic_and_skin_evidence_rules_are_enforced():
    import os
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "web"))
    from wizard_store import map_observation_with_metadata
    with pytest.raises(ValueError, match="动态|视频"):
        map_observation_with_metadata("舌面", {"舌体动态": "强硬"})
    with pytest.raises(ValueError, match="动态|视频"):
        map_observation_with_metadata("头面", {"鼻翼煽动": "明显"})
    with pytest.raises(ValueError, match="动态|视频|问诊"):
        map_observation_with_metadata("舌面", {"危重舌象": "舌强语謇"})
    with pytest.raises(ValueError, match="触诊|自陈"):
        map_observation_with_metadata("皮肤", {"水肿": "凹陷"})
    node, _, observations = map_observation_with_metadata(
        "皮肤", {"水肿": "凹陷", "黄汗": "色正黄"},
        source="self_report", method="inquiry")
    assert node["edema"] == "凹陷"
    assert node["yellow_sweat"] == "色正黄"
    assert {item.method for item in observations} == {"inquiry"}


def test_capture_part_aliases_keep_normal_fields_mapped():
    import os
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "web"))
    from wizard_store import map_observation_with_metadata
    face, unmapped_face, _ = map_observation_with_metadata("头面", {"面色": "淡白"})
    assert face["face"]["color"] == "淡白" and not unmapped_face
    eye, unmapped_eye, _ = map_observation_with_metadata(
        "目", {"下睑结膜颜色": "淡白"}, evidence={"exposed": True})
    assert eye["lower_lid_color"] == "淡白" and not unmapped_eye


def test_v2_unknown_is_visible_but_does_not_count_as_coverage():
    from src.record import DailyRecord
    from src.scoring import assess
    from src.observations import UNKNOWN_OBSERVATION_MARK
    unknown = capture_observation(V.EYE, "lower_lid", "淡白",
                                  source="vision", method="photo",
                                  evidence={"exposed": False})
    declaration = Declaration("declared_normal", "skin", "皮肤", "用户确认")
    record = DailyRecord({
        "schema_version": 2,
        "observations": {"eye": {"lower_lid_color": ""}},
        "observation_meta": {unknown.path: unknown.to_meta()},
        "declarations": [declaration.to_dict()],
    })
    obs = record.get_observation(V.EYE)
    assert obs["lower_lid"] == UNKNOWN_OBSERVATION_MARK
    assert record.get_dimension_coverage()[V.EYE] is False
    assert assess(V.EYE, record.get_scoring_observation(V.EYE)).state == "unknown"
    assert record.get_declarations()[0] == declaration.to_dict()
    assert UNKNOWN_OBSERVATION_MARK not in record.raw["observations"]["eye"].values()


def test_new_declarations_do_not_pollute_observations():
    import os
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "web"))
    import wizard_store
    draft = {"date": "2026-10-27", "inquiry": {}, "parts": {
        part["part"]: {"status": "skip_normal"} for part in wizard_store.PARTS
    }}
    raw = wizard_store.assemble_record(draft, "test")
    assert raw["schema_version"] == 2
    assert len(raw["declarations"]) == len(wizard_store.PARTS)
    assert all("未拍摄（用户声明正常）" not in str(value)
               for value in raw["observations"].values())
    assert raw["observation_meta"] == {}


def test_legacy_dynamic_critical_sign_cannot_be_assembled_from_photo():
    import os
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "web"))
    import wizard_store
    draft = {"date": "2026-10-27", "inquiry": {}, "parts": {
        part["part"]: {"status": "skip_normal"} for part in wizard_store.PARTS
    }}
    draft["parts"]["舌面"] = {
        "status": "observed", "method": "photo",
        "observation": {"critical_signs": "舌强语謇"},
    }
    with pytest.raises(ValueError, match="动态|问诊"):
        wizard_store.assemble_record(draft, "test")
