"""识图 prompt 枚举词与评分词表对齐回归（2026-10-20 静默 0 分专项）。

背景：prompt 枚举的措辞与评分词表曾是两套话（目赤「轻/重」、巩膜黄染
「轻/重」、舌底「边缘/异常」、面色「红赤」），模型照答即静默 0 分。
本测试钉住：每个字段的枚举词要么命中评分词表，要么落在正常语义白名单
（0 分 = 正常，方向正确）。
"""
import os
import re
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "scripts"))

from src.dimensions import VisionDimension as V  # noqa: E402
from src.indicators import INDICATOR_REGISTRY  # noqa: E402
from src.scoring import DIMENSION_RULES, match_keyword  # noqa: E402
from vision_client import PROMPTS  # noqa: E402

R = DIMENSION_RULES

# 正常/非评分语义（命中不了关键词 → 0 分，方向正确，validator 有豁免）
NORMAL_OK = {"正常", "无", "不明显", "润泽", "润", "淡红", "红润", "淡紫",
             "薄", "薄白", "适中", "光滑", "淡粉红", "无苔"}

# (prompt_key, 字段提示子串, 枚举词, 评分表；None 为参考项)
CASES = [
    ("舌面", "舌质颜色", ["淡红", "淡白", "红", "红绛", "紫暗"],
     R[V.TONGUE]["body_color"]),
    ("舌面", "舌质润燥", ["润泽", "偏干", "干燥", "干裂"], None),
    ("舌面", "舌体胖瘦", ["正常", "适中", "稍胖", "略瘦", "偏胖", "偏瘦", "胖大", "瘦小", "肿胀"],
     R[V.TONGUE]["body_size"]),
    ("舌面", "瘀斑瘀点", ["无", "散在", "密集"], R[V.TONGUE]["petechiae"]),
    ("舌面", "齿痕", ["无", "轻度", "中度", "重度"], R[V.TONGUE]["tooth_marks"]),
    ("舌面", "舌体裂纹", ["无", "浅裂", "深裂"], R[V.TONGUE]["fissure"]),
    ("舌面", "舌体点刺", ["无", "点刺", "芒刺", "不明显"], None),
    ("舌面", "舌苔颜色", ["白", "黄", "灰", "灰黑", "黑"],
     R[V.TONGUE]["coating_color"]),
    ("舌面", "舌苔厚薄", ["薄", "薄白", "薄黄", "略厚", "稍厚", "偏厚", "白厚",
                       "黄厚", "厚腻", "焦黑", "无苔"],
     R[V.TONGUE]["coating_thickness"]),
    ("舌面", "舌苔润燥", ["润", "滑", "燥", "干裂"],
     R[V.TONGUE]["coating_moisture"]),
    ("舌面", "舌苔腻腐", ["无", "微腻", "稍腻", "偏腻", "腻", "厚腻", "腐苔"],
     R[V.TONGUE]["coating_greasy"]),
    ("舌面", "舌苔剥落", ["无", "剥落", "花剥", "地图舌", "镜面", "剥脱"],
     R[V.TONGUE]["coating_peeling"]),
    ("舌面", "舌苔.苔量", ["无苔", "苔少", "适中", "苔多"], None),
    ("舌面", "舌苔.分布", ["满布", "偏布一侧"], None),
    ("舌底", "颜色", ["淡紫", "紫暗", "青紫"], R[V.TONGUE]["sublingual_color"]),
    ("舌底", "粗细", ["正常", "增粗", "怒张"],
     R[V.TONGUE]["sublingual_thickness"]),
    ("舌底", "走行判断", ["无", "轻度", "中度", "重度"],
     R[V.TONGUE]["sublingual_varicosity"]),
    ("舌底", "瘀点", ["无", "散在", "密集"], R[V.TONGUE]["sublingual_petechiae"]),
    ("头面部", "面色", ["淡白", "苍白", "㿠白", "萎黄", "红赤", "红如妆", "晦暗",
                     "黧黑", "青灰"], R[V.HEAD_FACE]["face_color"]),
    ("头面部", "面部浮肿", ["无", "轻度浮肿", "明显浮肿", "面目鲜泽"],
     R[V.HEAD_FACE]["face_edema"]),
    ("头面部", "唇色", ["淡红", "红润", "淡粉红", "淡白", "暗黄", "红", "紫暗", "青紫"],
     R[V.HEAD_FACE]["lip_color"]),
    ("头面部", "唇润燥", ["润", "稍干", "偏干", "干燥", "燥裂", "干枯"],
     R[V.HEAD_FACE]["lip_moisture"]),
    ("眼部", "目赤", ["无", "血丝", "赤丝", "红血丝", "红赤", "充血"],
     R[V.EYE]["redness"]),
    ("眼部", "巩膜黄染", ["无", "黄染轻度", "黄染明显"], R[V.EYE]["jaundice"]),
    ("眼部", "眼睑浮肿", ["无", "微肿", "浮肿", "浮肿明显", "卧蚕"],
     R[V.EYE]["edema"]),
    ("眼部", "白睛颜色", ["正常", "蓝巩膜", "苍白"], R[V.EYE]["sclera_color"]),
    ("眼部", "下睑结膜颜色", ["淡红", "淡白", "淡黄", "苍白"],
     R[V.EYE]["lower_lid"]),
    ("耳部", "耳色", ["正常", "红赤", "青黑", "淡红", "淡白"], R[V.EAR]["color"]),
    ("耳部", "润枯", ["润泽", "略枯", "干枯"], R[V.EAR]["helix"]),
    ("手掌", "掌色", ["淡红", "红润", "淡白", "红", "暗红", "紫暗"],
     R[V.HAND]["palm_color"]),
    ("手掌", "甲床颜色", ["淡白", "红润", "紫暗", "暗紫"],
     R[V.HAND]["nail_color"]),
    ("手掌", "甲床形态", ["光滑", "粗糙", "甲错"], R[V.HAND]["nail_shape"]),
    ("皮肤", "肤色", ["正常", "萎黄", "黄如橘皮", "烟熏"], R[V.SKIN]["color"]),
    ("皮肤", "甲错", ["无", "局部", "广泛", "甲错"], R[V.SKIN]["cuo"]),
    ("皮肤", "水肿", ["无", "全身浮肿"], R[V.SKIN]["edema"]),
    ("皮肤", "皮肤干燥程度", ["正常", "粗糙", "龟裂"], R[V.SKIN]["dryness"]),
]


@pytest.mark.parametrize("pkey, field, words, rules", CASES,
                         ids=[f"{c[0]}·{c[1]}" for c in CASES])
def test_prompt_enum_hits_vocab(pkey, field, words, rules):
    prompt = PROMPTS[pkey]
    spec = INDICATOR_REGISTRY.for_prompt(pkey, field)
    field_pattern = re.escape(field)
    if field.startswith("舌体"):
        field_pattern = "(?:舌体)?" + re.escape(field[2:])
    field_pattern += '"?'
    match = re.search(
        rf"{field_pattern}(?:\([^)]*\))?\s*只填(?:规范词|一个词)：([^。；]+)",
        prompt,
    )
    assert match, f"{pkey}·{field} 缺封闭枚举"
    actual = match.group(1).split("（", 1)[0].split("/")
    assert actual == words
    assert tuple(words) == spec.prompt_options
    misses_vocab = []
    for word in words:
        if not rules or match_keyword(rules, word) is not None or word in NORMAL_OK:
            continue
        if (pkey, field, word) == ("手掌", "甲床形态", "粗糙"):
            from src.scoring import assess_indicators
            result = assess_indicators(spec.dimension, {spec.key: word})[spec.key]
            assert result.state == "unknown" and result.value is None
        else:
            misses_vocab.append(word)
    assert not misses_vocab, \
        f"{pkey}·{field} 枚举词不命中词表且非正常/已登记 unknown: {misses_vocab}"


def test_every_prompt_field_has_independent_contract_case():
    cases = {
        INDICATOR_REGISTRY.for_prompt(part, field).id
        for part, field, _, _ in CASES
    }
    prompted = {spec.id for spec in INDICATOR_REGISTRY if spec.prompt_part}
    assert prompted == cases


def test_face_color_hongchi_scored():
    """面色「红赤」入词表（太阳面赤=3，分值待主人签认）——prompt 枚举词不再静默 0。"""
    assert R[V.HEAD_FACE]["face_color"]["红赤"] == 3
    assert match_keyword(R[V.HEAD_FACE]["face_color"], "红赤") == "红赤"
