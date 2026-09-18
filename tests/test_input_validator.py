"""input_validator 注记词表测试（批次 5）：

评分类指标的值若含判读注记特征（括号内出现模型名/判读词）应触发
warning（纯告警，不判失败）。词表补全 DeepSeek/Kimi/GPT/Claude/Gemini
后，「淡红（DeepSeek 误判）」式写法必须被识别；正常括号描述不误报。
"""
import json
import os
import tempfile

import pytest


def _validate_raw(raw):
    """把 raw dict 写入临时文件并跑 validator，返回 (record, errors, warnings)。"""
    import input_validator as v
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                     encoding="utf-8") as f:
        json.dump(raw, f, ensure_ascii=False)
        path = f.name
    try:
        return v.validate_record(path)
    finally:
        os.remove(path)


def _record_with_body_color(value):
    return {
        "date": "2026-01-01",
        "confidence": "LOW",
        "observations": {"tongue": {"body": {"color": value}}},
        "danger_flags": {"triggered": [], "not_triggered": []},
    }


@pytest.mark.parametrize("model_name",
                         ["DeepSeek", "豆包", "Qwen", "K3", "Kimi",
                          "GPT", "Claude", "Gemini"])
def test_model_name_annotation_triggers_warning(model_name):
    """模型名出现在注记里（如「DeepSeek 误判」）必须触发判读注记 warning。"""
    _, _, warnings = _validate_raw(
        _record_with_body_color(f"淡红（{model_name} 误判）"))
    assert any("判读注记" in w for w in warnings), \
        f"含 {model_name} 注记的值应触发判读注记 warning: {warnings}"


def test_plain_bracket_description_no_false_positive():
    """正常括号描述（无模型名/判读词）不应误报注记 warning。"""
    _, _, warnings = _validate_raw(
        _record_with_body_color("淡红（晨起自然光下拍摄）"))
    assert not any("判读注记" in w for w in warnings)


# ============================================================
# 词表覆盖检查（v1.4.11）：封闭词表指标的值未命中词表任何词条 →
# warning（纯告警，不判失败）。把「词表外措辞 → 静默读作 0 分」暴露出来。
# ============================================================

def _record_with_obs(tongue_body=None, head_face=None, eye=None):
    obs = {"tongue": {}, "head_face": {}, "eye": {}}
    if tongue_body:
        obs["tongue"]["body"] = tongue_body
    if head_face:
        obs["head_face"].update(head_face)
    if eye:
        obs["eye"].update(eye)
    return {
        "date": "2026-01-01",
        "confidence": "LOW",
        "observations": obs,
        "danger_flags": {"triggered": [], "not_triggered": []},
    }


def test_out_of_vocab_wording_triggers_warning():
    """「舌缘可见」（prompt 明确禁止的描述性短语）必须触发词表外措辞 warning。"""
    _, errors, warnings = _validate_raw(
        _record_with_obs(tongue_body={"tooth_marks": "舌缘可见"}))
    assert not errors
    hits = [w for w in warnings if "词表外措辞" in w]
    assert len(hits) == 1
    assert "tooth_marks" in hits[0] and "舌缘可见" in hits[0]
    assert "无/轻度/中度/重度" in hits[0]  # 给出可行动的规范词清单
    assert "模型措辞问题而非数据错误" in hits[0]
    # 两分支处置指引（v1.4.12）：静默 0 分事实原样保留，正常描述分支
    # 明确告知可忽略、异常分支明确告知漏判后果——不按情形分级措辞
    assert "静默按 0 分" in hits[0]
    assert "可忽略本告警" in hits[0]
    assert "静默漏判" in hits[0]


def test_out_of_vocab_synonym_example_warns():
    """动机示例：把「偏胖」写成「较丰满」→ 告警（否则静默 0 分）。"""
    _, _, warnings = _validate_raw(
        _record_with_obs(tongue_body={"shape": "较丰满"}))
    assert any("词表外措辞" in w and "body_size" in w for w in warnings)


def test_in_vocab_value_no_vocab_warning():
    """词表内措辞（含最长匹配「淡红为底」）不告警。"""
    _, _, warnings = _validate_raw(
        _record_with_obs(tongue_body={"color": "淡红为底，舌面润泽",
                                      "shape": "偏胖"}))
    assert not any("词表外措辞" in w for w in warnings)


@pytest.mark.parametrize("value", [
    "无明显浮肿",            # 否定陈述（关键词被否定守卫拦截，不算词表外）
    "未见",                  # 纯否定占位
    "未拍摄（用户声明正常）",  # 未拍摄占位（形状 C 高频写法）
    "正常",                  # 显式正常
    "不明显",                # 存疑/正常占位
])
def test_normal_or_negated_value_no_vocab_warning(value):
    """正常/否定语义值豁免：词表只收异常词与显式基线词，0 分是正确结果。"""
    _, _, warnings = _validate_raw(
        _record_with_obs(tongue_body={"tooth_marks": value}))
    assert not any("词表外措辞" in w for w in warnings), \
        f"{value!r} 不应触发词表外措辞 warning: {warnings}"


def test_annotation_value_not_double_warned():
    """已被判读注记检查告警的值不重复告警（同一值两条 warning 是噪声）。"""
    _, _, warnings = _validate_raw(
        _record_with_obs(tongue_body={"shape": "丰满（K3 判读）"}))
    assert any("判读注记" in w for w in warnings)      # hygiene 检查照常告警
    assert not any("词表外措辞" in w for w in warnings)  # 词表检查豁免


def test_free_text_indicator_not_checked():
    """无词表的自由文本指标（body_luster 等）不适用词表覆盖检查。"""
    _, _, warnings = _validate_raw(
        _record_with_obs(tongue_body={"luster": "神采奕奕，有光泽"}))
    assert not any("词表外措辞" in w for w in warnings)
