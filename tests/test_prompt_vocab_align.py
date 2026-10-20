"""识图 prompt 枚举词与评分词表对齐回归（2026-10-20 静默 0 分专项）。

背景：prompt 枚举的措辞与评分词表曾是两套话（目赤「轻/重」、巩膜黄染
「轻/重」、舌底「边缘/异常」、面色「红赤」），模型照答即静默 0 分。
本测试钉住：每个字段的枚举词要么命中评分词表，要么落在正常语义白名单
（0 分 = 正常，方向正确）。
"""
import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "scripts"))

from src.dimensions import VisionDimension as V  # noqa: E402
from src.scoring import DIMENSION_RULES, match_keyword  # noqa: E402
from vision_client import PROMPTS  # noqa: E402

R = DIMENSION_RULES

# 正常/非评分语义（命中不了关键词 → 0 分，方向正确，validator 有豁免）
NORMAL_OK = {"正常", "无", "不明显", "润泽", "润", "淡红", "红润", "淡紫",
             "薄", "薄白", "适中", "光滑", "淡粉红", "无苔"}

# (prompt_key, 字段提示子串, 枚举词, 评分表)
CASES = [
    # 舌色并五档（2026-10-20 主人定：九档超模型色分辨力，细分词已删除）
    ("舌面", "舌质颜色", ["淡红", "淡白", "红", "红绛", "紫暗"],
     R[V.TONGUE]["body_color"]),
    ("舌面", "舌苔颜色", ["白", "黄", "灰", "灰黑", "黑"],
     R[V.TONGUE]["coating_color"]),
    ("舌面", "舌苔厚薄", ["薄", "薄白", "薄黄", "略厚", "稍厚", "偏厚", "白厚",
                       "黄厚", "厚腻", "焦黑", "无苔"],
     R[V.TONGUE]["coating_thickness"]),
    ("舌面", "舌苔剥落", ["无", "剥落", "花剥", "地图舌", "镜面", "剥脱"],
     R[V.TONGUE]["coating_peeling"]),
    ("舌面", "舌体裂纹", ["无", "浅裂", "深裂"], R[V.TONGUE]["fissure"]),
    ("舌面", "舌苔腻腐", ["无", "微腻", "稍腻", "偏腻", "腻", "厚腻", "腐苔"],
     R[V.TONGUE]["coating_greasy"]),
    ("舌面", "舌体胖瘦", ["正常", "适中", "偏胖", "胖大", "偏瘦", "瘦小", "肿胀"],
     R[V.TONGUE]["body_size"]),
    ("舌面", "齿痕", ["无", "轻度", "中度", "重度"], R[V.TONGUE]["tooth_marks"]),
    ("舌底", "颜色", ["淡紫", "紫暗", "青紫"], R[V.TONGUE]["sublingual_color"]),
    ("舌底", "粗细", ["正常", "增粗", "怒张"],
     R[V.TONGUE]["sublingual_thickness"]),
    ("舌底", "走行判断", ["无", "轻度", "中度", "重度"],
     R[V.TONGUE]["sublingual_varicosity"]),
    ("头面部", "面色", ["淡白", "苍白", "㿠白", "萎黄", "红赤", "红如妆", "晦暗",
                     "黧黑", "青灰"], R[V.HEAD_FACE]["face_color"]),
    ("头面部", "唇色", ["淡红", "红润", "淡白", "暗黄", "红", "紫暗", "青紫"],
     R[V.HEAD_FACE]["lip_color"]),
    ("头面部", "唇润燥", ["润", "稍干", "偏干", "干燥", "燥裂", "干枯"],
     R[V.HEAD_FACE]["lip_moisture"]),
    ("头面部", "面部浮肿", ["无", "轻度浮肿", "明显浮肿", "面目鲜泽", "卧蚕"],
     R[V.HEAD_FACE]["face_edema"]),
    ("眼部", "白睛颜色", ["正常", "黄染", "蓝巩膜", "苍白"],
     R[V.EYE]["sclera_color"]),
    ("眼部", "目赤", ["无", "血丝", "赤丝", "红血丝", "红赤", "充血"],
     R[V.EYE]["redness"]),
    ("眼部", "巩膜黄染", ["无", "黄染轻度", "黄染明显"], R[V.EYE]["jaundice"]),
    ("眼部", "眼睑浮肿", ["无", "微肿", "浮肿", "浮肿明显", "卧蚕"],
     R[V.EYE]["edema"]),
    ("眼部", "下睑结膜颜色", ["淡红", "淡白", "淡黄", "苍白"],
     R[V.EYE]["lower_lid"]),
    ("耳部", "耳色", ["正常", "红赤", "青黑", "淡白"], R[V.EAR]["color"]),
    ("耳部", "润枯", ["润泽", "略枯", "干枯"], R[V.EAR]["helix"]),
    ("手掌", "掌色", ["淡红", "红润", "淡白", "红", "暗红", "紫暗"],
     R[V.HAND]["palm_color"]),
    ("手掌", "甲床颜色", ["淡白", "红润", "紫暗", "暗紫"],
     R[V.HAND]["nail_color"]),
    ("皮肤", "肤色", ["正常", "萎黄", "黄如橘皮", "黄如烟熏"],
     R[V.SKIN]["color"]),
    ("皮肤", "甲错", ["无", "局部", "广泛", "甲错"], R[V.SKIN]["cuo"]),
    ("皮肤", "水肿", ["无", "凹陷", "全身浮肿"], R[V.SKIN]["edema"]),
    ("皮肤", "皮肤干燥程度", ["正常", "粗糙", "龟裂"], R[V.SKIN]["dryness"]),
]


@pytest.mark.parametrize("pkey, field, words, rules", CASES,
                         ids=[f"{c[0]}·{c[1]}" for c in CASES])
def test_prompt_enum_hits_vocab(pkey, field, words, rules):
    prompt = PROMPTS[pkey]
    misses_vocab, missing_prompt = [], []
    for w in words:
        if w not in prompt:
            missing_prompt.append(w)
        if match_keyword(rules, w) is None and w not in NORMAL_OK:
            misses_vocab.append(w)
    assert not missing_prompt, f"{pkey}·{field} prompt 缺枚举词: {missing_prompt}"
    assert not misses_vocab, \
        f"{pkey}·{field} 枚举词不命中词表且非正常语义（会静默 0 分）: {misses_vocab}"


def test_face_color_hongchi_scored():
    """面色「红赤」入词表（太阳面赤=3，分值待主人签认）——prompt 枚举词不再静默 0。"""
    assert R[V.HEAD_FACE]["face_color"]["红赤"] == 3
    assert match_keyword(R[V.HEAD_FACE]["face_color"], "红赤") == "红赤"
