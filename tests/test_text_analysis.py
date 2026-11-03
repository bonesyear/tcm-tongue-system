"""共享文本分析：否定、转折与非患者阳性语境（不依赖 Flask）。"""
import pytest

from src.dimensions import VisionDimension as V
from src.scoring import assess, match_keyword, score_indicators
from src.danger import detect_danger
from src.text_analysis import find_term


@pytest.mark.parametrize("text,term,state", [
    ("无黄染", "黄染", "negated"),
    ("并非口不能言", "口不能言", "negated"),
    ("绝非口不能言", "口不能言", "negated"),
    ("排除口不能言", "口不能言", "negated"),
    ("口不能言未见", "口不能言", "negated"),
    ("冷汗不明显", "冷汗", "negated"),
    ("需与狐惑鉴别", "狐惑", "excluded"),
    ("镜面反光", "镜面", "excluded"),
    ("无冷汗；冷汗如油", "冷汗", "matched"),
    ("无冷汗，冷汗如油", "冷汗", "matched"),
    ("无冷汗但冷汗如油", "冷汗", "matched"),
    ("非典型黄染", "黄染", "matched"),
    ("没有黄染", "黄染", "negated"),
    ("", "黄染", "missing"),
])
def test_find_term_states(text, term, state):
    assert find_term(text, term).state == state


def test_scoring_and_danger_share_contrast_and_post_negation():
    assert match_keyword({"红": 7}, "舌不红但舌边红") == "红"
    assert score_indicators(V.TONGUE, {"body_color": "舌不红但舌边红"})["body_color"] == 7
    assert assess(V.EYE, {"jaundice": "无黄染但巩膜黄染"}).value == 4
    assert detect_danger({"skin": {"sweat": "无冷汗；冷汗如油"}}) == ["collapse_yang"]
    assert detect_danger({"skin": {"sweat": "冷汗不明显"}}) == []
    assert detect_danger({"skin": {"sweat": "排除冷汗"}}) == []


def test_non_patient_context_does_not_trigger_legacy_detector():
    assert detect_danger({"tongue": {"note": "需与狐惑鉴别"}}) == []
    assert detect_danger({"tongue": {"coating": {"peeling": "镜面反光"}}}) == []


def test_red_makeup_closed_option_recalls_daiyang():
    assert detect_danger({"head_face": {"face": {"color": "红如妆"}}}) == ["daiyang"]


def test_old_report_and_existing_flags_cannot_self_prove_alert():
    assert detect_danger({
        "danger_flags": {"triggered": ["daiyang"]},
        "diagnosis": {"summary": "面红如妆，黄如橘皮"},
    }) == []
