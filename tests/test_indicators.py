"""指标注册表与垂直切片契约。"""
import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "web"))

from src.dimensions import VisionDimension as V
from src.record import DailyRecord
from src.scoring import assess, DIMENSION_RULES
from src.indicators import INDICATOR_REGISTRY


def test_registry_has_45_indicators_and_body_color_paths():
    assert len(INDICATOR_REGISTRY) == 45
    spec = INDICATOR_REGISTRY["tongue.body.color"]
    assert spec.paths["A"] == ["舌质颜色"]
    assert spec.paths["B"] == ["body", "color"]
    assert spec.paths["C"] == ["body_color"]
    assert INDICATOR_REGISTRY.for_dimension(V.TONGUE)["body_color"] is spec.paths
    assert "tongue.body.color" not in INDICATOR_REGISTRY.for_dimension(V.TONGUE)
    assert spec.source_refs
    assert spec.allowed_methods


def test_eye_jaundice_has_single_canonical_field_and_legacy_alias():
    assert "黄染" not in DIMENSION_RULES[V.EYE]["sclera_color"]
    assert "黄染" in DIMENSION_RULES[V.EYE]["jaundice"]

    alias_only = DailyRecord({"eye": {"sclera_color": "黄染"}})
    obs = alias_only.get_observation(V.EYE)
    assert obs["jaundice"] == "黄染"
    assert obs["sclera_color"] == ""
    assert assess(V.EYE, obs).value == 4

    both = DailyRecord({"observations": {"eye": {
        "scleral_jaundice": "黄染轻度", "sclera_color": "黄染",
    }}})
    obs = both.get_observation(V.EYE)
    assert obs["jaundice"] == "黄染轻度；黄染"
    assert obs["sclera_color"] == ""
    assert assess(V.EYE, obs).value == 4


@pytest.mark.parametrize("raw", [
    {"eye": {"sclera_color": "黄染明显"}},
    {"observations": {"eye": {"sclera_color": "黄染明显"}}},
    {"vision_analysis": {"目诊": {"巩膜颜色": "黄染明显"}}},
])
def test_eye_jaundice_legacy_alias_across_shapes_and_direct_scoring(raw):
    record = DailyRecord(raw)
    assert record.get_observation(V.EYE)["jaundice"] == "黄染明显"
    assert assess(V.EYE, record.get_observation(V.EYE)).value == 8
    assert assess(V.EYE, {"sclera_color": "黄染明显"}).value == 8


def test_eye_jaundice_alias_conflict_does_not_hide_positive_evidence():
    record = DailyRecord({"eye": {
        "jaundice": "无黄染", "sclera_color": "黄染明显",
    }})
    obs = record.get_observation(V.EYE)
    assert "黄染明显" in obs["jaundice"]
    assert assess(V.EYE, obs).value == 8
    generic_alias = DailyRecord({"eye": {
        "jaundice": "无黄染", "sclera_color": "黄染",
    }}).get_observation(V.EYE)
    assert assess(V.EYE, generic_alias).value == 4


def test_wocan_is_canonical_eye_edema_not_duplicate_face_edema():
    record = DailyRecord({"observations": {
        "head_face": {"face": {"edema": "卧蚕"}},
        "eye": {"eyelid_edema": "卧蚕"},
    }})
    face_obs = record.get_observation(V.HEAD_FACE)
    eye_obs = record.get_observation(V.EYE)
    assert face_obs["face_edema"] == ""
    assert eye_obs["edema"] == "卧蚕"
    assert assess(V.HEAD_FACE, face_obs).state == "not_applicable"
    assert assess(V.EYE, eye_obs).value == 6
    assert assess(V.EYE, {"face_edema": "卧蚕"}).value == 6


def test_body_color_prompt_and_correction_options_share_source():
    import records_store
    sys.path.insert(0, os.path.join(_ROOT, "scripts"))
    from vision_client import PROMPTS
    spec = INDICATOR_REGISTRY["tongue.body.color"]
    assert spec.prompt_options == tuple(records_store._field_options(V.TONGUE, "body_color"))
    enum_text = "/".join(spec.prompt_options)
    assert f"舌质颜色只填规范词：{enum_text}" in PROMPTS["舌面"]
    assert "白睛颜色只填规范词：正常/黄染" not in PROMPTS["眼部"]


def test_glossary_is_scoped_by_indicator_not_global_word():
    import records_store
    nose = INDICATOR_REGISTRY.glossary_for("head_face.nose_flare", "明显")
    face = INDICATOR_REGISTRY.glossary_for("head_face.face_color", "青灰")
    eye = INDICATOR_REGISTRY.glossary_for("eye.redness", "红赤")
    assert "黄汗" not in nose
    assert "心阳" in face or "心脉" in face
    assert "目" in eye and "4 分" in eye
    meta = records_store.correction_meta()
    assert "鼻翼" in meta["head_face"]["nose.flaring"]["gloss"]["明显"]
    assert "面色" in meta["head_face"]["face.color"]["gloss"]["红赤"]
    assert "白睛" in meta["eye"]["redness"]["gloss"]["红赤"]
    assert "汗色" in meta["skin"]["yellow_sweat"]["gloss"]["明显"]


def test_registry_contract_for_sources_alerts_and_prompt_options():
    import records_store
    ids = set()
    for spec in INDICATOR_REGISTRY:
        assert spec.id not in ids
        ids.add(spec.id)
        assert spec.source_refs
        assert spec.allowed_methods
        assert spec.unknown_semantics
        for flag in spec.alert_links:
            assert flag in records_store.DANGER_FLAGS
    assert INDICATOR_REGISTRY["head_face.face_color"].alert_links == ("daiyang",)
    assert INDICATOR_REGISTRY["tongue.coating.peeling"].alert_links == ("mirror_tongue",)
    assert INDICATOR_REGISTRY["eye.jaundice"].alert_links == ("acute_jaundice",)
    assert INDICATOR_REGISTRY["tongue.petechiae"].prompt_options
    assert INDICATOR_REGISTRY["tongue.coating.moisture"].prompt_options


def test_provenance_distinguishes_books_and_legacy_experience():
    lower = INDICATOR_REGISTRY["eye.lower_lid"]
    assert [ref.source_id for ref in lower.source_refs] == ["jingfang"]
    assert lower.source_refs[0].locator == "抽取文本 L7228"
    nail = INDICATOR_REGISTRY["hand.nail_color"]
    assert [ref.source_id for ref in nail.source_refs] == ["tcm-textbook", "jingfang"]
    assert nail.source_refs[1].locator == "抽取文本 L7228"
    nail_shape = INDICATOR_REGISTRY["hand.nail_shape"]
    assert any(ref.source_id == "experience" for ref in nail_shape.source_refs)
    assert "不直接等同指甲" in nail_shape.glossary["甲错"]
    sweat = INDICATOR_REGISTRY["skin.yellow_sweat"]
    assert sweat.allowed_methods == ("inquiry", "self_report")
    assert sweat.source_refs[-1].locator == "抽取文本 L4184"
    for spec in INDICATOR_REGISTRY:
        for ref in spec.source_refs:
            assert ref.keyword and ref.locator
            if ref.source_id != "experience":
                assert len(ref.sha256) == 64


def test_template_inquiry_counts_are_17_not_15_or_16():
    with open(os.path.join(_ROOT, "templates", "adaptive_analysis_prompt.md"),
              encoding="utf-8") as f:
        text = f.read()
    assert "M/17" in text
    assert "M/15" not in text
    assert "0～15" not in text
    assert "十五项问诊" not in text
    import wizard_store
    section = text.split("#### 2.1.2", 1)[1].split("### 2.2", 1)[0]
    rows = [line.split("|") for line in section.splitlines()
            if line.startswith("| ")][1:]
    assert [row[1].strip() for row in rows] == [str(i) for i in range(17)]
    assert [row[2].strip() for row in rows] == [
        wizard_store.INQUIRY_SPEC["key"] + "？",
        *(item["q"] for item in wizard_store.INQUIRY_ITEMS),
    ]
    assert wizard_store.INQUIRY_TOTAL == 17
