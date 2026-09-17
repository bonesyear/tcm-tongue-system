"""形状 C（自由格式，顶层规范英文维度键）测试。

fixture tests/fixtures/shape_c_sample.json 为纯合成示例（字段与值风格仿形状 C
记录，全部内容为构造数据，不对应任何真实个人）。
"""
import json
import os

import pytest

from src.record import DailyRecord
from src.dimensions import VisionDimension
from src import scoring

FIXTURE_PATH = os.path.join(
    os.path.dirname(__file__), "fixtures", "shape_c_sample.json"
)


@pytest.fixture
def shape_c_record():
    with open(FIXTURE_PATH, encoding="utf-8") as f:
        return DailyRecord(json.load(f))


# ---- 形状检测优先级 ----

def test_pure_shape_c_detected(shape_c_record):
    assert shape_c_record.shape == "C"


def test_observations_takes_priority_over_c_keys():
    raw = {"observations": {}, "tongue": {"body_color": "淡红"}}
    assert DailyRecord(raw).shape == "B"


def test_empty_dict_defaults_to_b():
    assert DailyRecord({}).shape == "B"


# ---- 维度键别名 face/palm ----

def test_face_alias_maps_to_head_face():
    record = DailyRecord({"face": {"face_color": "萎黄"}})
    assert record.shape == "C"
    assert record.get_observation(VisionDimension.HEAD_FACE)["face_color"] == "萎黄"


def test_palm_alias_maps_to_hand():
    record = DailyRecord({"palm": {"palm_color": "淡白"}})
    assert record.shape == "C"
    assert record.get_observation(VisionDimension.HAND)["palm_color"] == "淡白"


def test_canonical_key_wins_over_alias():
    record = DailyRecord({
        "head_face": {"face_color": "晦暗"},
        "face": {"face_color": "萎黄"},
    })
    assert record.get_observation(VisionDimension.HEAD_FACE)["face_color"] == "晦暗"


# ---- 评分（真实风格值，经 Record → Scoring 链路） ----

def _tongue_scores(record):
    return scoring.score_indicators(
        VisionDimension.TONGUE, record.get_observation(VisionDimension.TONGUE)
    )


def test_tooth_marks_mild_beats_negated_none(shape_c_record):
    # "轻度" 为最长命中（len 2 > "无" len 1），不得被 "无明显" 中的 "无" 误杀
    assert _tongue_scores(shape_c_record)["tooth_marks"] == 4


def test_body_color_pale_red_is_normal(shape_c_record):
    # "淡红"（0 分基线）优先于 "红"（7 分）
    assert _tongue_scores(shape_c_record)["body_color"] == 0


def test_long_peeling_text_does_not_leak_into_other_indicators(shape_c_record):
    obs = shape_c_record.get_observation(VisionDimension.TONGUE)
    assert "剥落" in obs["coating_peeling"]  # 长描述确实被读到本指标
    without_peeling = {k: v for k, v in obs.items() if k != "coating_peeling"}
    assert (_tongue_scores(shape_c_record)
            == scoring.score_indicators(VisionDimension.TONGUE, without_peeling))


# ---- 问诊扁平字典 / pattern_update ----

def test_inquiry_flat_dict_counts_nonempty_strings(shape_c_record):
    # 4 个问题中 "小便" 为空串 → 3/4
    assert shape_c_record.get_inquiry_coverage() == (3, 4)


def test_pattern_update_read(shape_c_record):
    pd = shape_c_record.get_pattern_differentiation()
    assert "示例辨证" in pd["pattern"]


# ---- 缺失容错 ----

def test_missing_fields_return_empty_strings_without_raising():
    record = DailyRecord({"tongue": {"body_color": "淡红"}})
    skin = record.get_observation(VisionDimension.SKIN)
    assert skin, "返回结构应稳定（含全部规范指标键）"
    assert all(v == "" for v in skin.values())
    tongue = record.get_observation(VisionDimension.TONGUE)
    assert tongue["body_color"] == "淡红"
    assert tongue["coating_greasy"] == ""  # 缺失指标空串占位，不抛异常
