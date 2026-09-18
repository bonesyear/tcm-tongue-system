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
