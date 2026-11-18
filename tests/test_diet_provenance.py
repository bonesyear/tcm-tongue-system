"""食疗出处、数量与本地速览边界的回归测试。"""
import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "web"))

import report_store  # noqa: E402


def _ref(excerpt, category="diet"):
    return {"file": "diet-lifestyle/example.md", "line": 1,
            "excerpt": excerpt, "category": category}


ORANGE = _ref(
    "食疗资料｜痰湿内阻证：橘皮饭｜出处：附录 4，正文第 51 页｜"
    "主要材料：橘皮 10g，粳米 100g。｜"
    "制作方法：橘皮洗干净表面的灰尘，剪成小条，同粳米煮饭，佐餐食用。")
PORRIDGE = _ref(
    "食疗资料｜气滞血瘀型：山楂粥｜出处：附录 4，正文第 51 页｜"
    "主要材料：山楂 20g，粳米 100g。｜"
    "制作方法：山楂冲洗干净，煮水取汁与粳米一起熬制成粥，佐餐食用。")


def _diet(name, amount):
    return {"diet_advice": {"daily_foods": [{
        "name": name, "nature": "资料未载明", "purpose": "资料未载明",
        "amount": amount, "note": "合成测试"}], "med_foods": [], "avoid": []}}


@pytest.mark.parametrize("name,amount", [
    ("橘皮饭", "橘皮 10g，粳米 100g"),
    ("痰湿内阻证：橘皮饭", "橘皮10g、粳米100g"),
    ("橘皮饭", "橘皮 １０ｇ，粳米 １００ｇ"),
])
def test_diet_amount_accepts_same_complete_candidate(name, amount):
    assert report_store._diet_output_error(_diet(name, amount), [ORANGE]) is None


@pytest.mark.parametrize("name,amount,refs", [
    ("橘皮饭", "橘皮 15g，粳米 100g", [ORANGE]),
    ("橘皮饭", "山楂 20g，粳米 100g", [ORANGE, PORRIDGE]),
    ("粳米", "粳米 100g", [ORANGE]),
    ("橘皮饭", "橘皮 10g，粳米 100g", []),
])
def test_diet_amount_rejects_unsourced_or_mixed_values(name, amount, refs):
    error = report_store._diet_output_error(_diet(name, amount), refs)
    assert error and "报告未保存" in error


def test_diet_amount_allows_explicit_unknown_without_inventing_number():
    assert report_store._diet_output_error(_diet("一般饮食原则", "未提供"), []) is None


def test_diet_amount_rejects_empty_amount_and_malformed_list():
    assert "缺少数量" in report_store._diet_output_error(_diet("橘皮饭", ""), [ORANGE])
    structured = {"diet_advice": {"daily_foods": "橘皮饭"}}
    assert "不是列表" in report_store._diet_output_error(structured, [ORANGE])


def test_prompt_requires_source_bound_amount_and_condition():
    path = os.path.join(_ROOT, "templates", "adaptive_analysis_prompt.md")
    with open(path, encoding="utf-8") as handle:
        prompt = handle.read()
    assert "无法完整照引时填「未提供」" in prompt
    assert "不得仅凭照片、四证或九种体质推定疾病或指南证型" in prompt
    assert "库内推荐方有具体分量" not in prompt
    assert "山药 50–100g/日" not in prompt


def _report_client(tmp_path, monkeypatch, amount):
    pytest.importorskip("flask")
    import json
    import shutil
    import llm_client
    from app import create_app

    data = tmp_path / "data"
    daily = data / "records" / "daily"
    daily.mkdir(parents=True)
    record_path = daily / "2026-06-25_analysis.json"
    shutil.copyfile(os.path.join(_ROOT, "tests", "fixtures",
                                 "2026-06-25_analysis.json"), record_path)
    kb = tmp_path / "kb"
    for category in ("constitution", "formula"):
        root = kb / category
        root.mkdir(parents=True)
        (root / "content.md").write_text("合成非食疗资料", encoding="utf-8")
    diet = kb / "diet" / "diet-lifestyle"
    diet.mkdir(parents=True)
    (diet / "example.md").write_text(
        "# 合成资料\n\n食疗资料｜痰湿内阻证：橘皮饭｜出处：合成指南第 1 页｜"
        "主要材料：橘皮 10g，粳米 100g。｜制作方法：同粳米煮饭，佐餐食用。\n",
        encoding="utf-8")
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    monkeypatch.setenv("LLM_MODEL", "test-model")
    monkeypatch.setenv("LLM_BASE_URL", "https://example.invalid/v1/chat/completions")
    monkeypatch.setenv("TCM_KB_ALLOW_EXTERNAL_KB", "1")
    monkeypatch.setenv("TCM_KB_STRICT_CATEGORIES", "1")
    monkeypatch.setenv("TCM_KB_CONSTITUTION_ROOT", str(kb / "constitution"))
    monkeypatch.setenv("TCM_KB_FORMULA_ROOT", str(kb / "formula"))
    monkeypatch.setenv("TCM_KB_DIET_ROOT", str(kb / "diet"))
    structured = {
        "three_views": {}, "four_patterns": {}, "six_diseases": "",
        "core_pathomechanism": "", "lifestyle": {},
        "diet_advice": {"daily_foods": [{
            "name": "橘皮饭", "nature": "资料未载明", "purpose": "资料未载明",
            "amount": amount, "note": "仅合成路由测试"}], "med_foods": [], "avoid": []},
    }
    monkeypatch.setattr(llm_client, "chat", lambda *a, **k: json.dumps({
        "structured": structured, "markdown": "# 合成报告\n\n饮食资料。"}))
    app = create_app(env_file=str(tmp_path / ".env"), data_root=str(data))
    app.config["TESTING"] = True
    client = app.test_client()
    client.post("/welcome", headers={"Origin": "http://localhost"})
    return client, record_path


def test_report_route_accepts_amount_from_actual_candidate(tmp_path, monkeypatch):
    client, record_path = _report_client(tmp_path, monkeypatch, "橘皮10g、粳米100g")
    response = client.post("/record/2026-06-25/report")
    assert response.status_code == 200, response.get_json()
    import json
    saved = json.loads(record_path.read_text(encoding="utf-8"))
    assert saved["diagnosis"]["report"]["diet_advice"]["daily_foods"][0]["amount"] \
        == "橘皮10g、粳米100g"


def test_report_route_rejects_changed_amount_without_touching_record(tmp_path, monkeypatch):
    client, record_path = _report_client(tmp_path, monkeypatch, "橘皮15g、粳米100g")
    before = record_path.read_bytes()
    response = client.post("/record/2026-06-25/report")
    assert response.status_code == 400
    assert "原始数量对应" in response.get_json()["error"]
    assert record_path.read_bytes() == before


def test_constitution_recipe_name_and_amount_share_one_candidate():
    ref = _ref(
        "食疗资料｜气虚质：参芪鹌鹑汤｜出处：卫健委体质药膳示例｜"
        "主要材料：党参 15 克，黄芪 15 克，鹌鹑 1 只，食盐适量｜"
        "制作方法：隔水炖 2 小时，除去党参、黄芪，吃肉喝汤。")
    for name in ("气虚质：参芪鹌鹑汤", "参芪鹌鹑汤"):
        structured = _diet(name, "党参15克、黄芪15克、鹌鹑1只、食盐适量")
        assert report_store._diet_output_error(structured, [ref]) is None
    structured = _diet("参芪鹌鹑汤", "党参15克、黄芪15克、鹌鹑1只、食盐适量")
    other = _ref(
        "食疗资料｜特禀质：乌梅粥｜出处：卫健委体质药膳示例｜"
        "主要材料：乌梅 15 克，黄芪 20 克，当归 12 克，粳米 100 克｜"
        "制作方法：熬成粥即可食用。")
    assert report_store._diet_output_error(structured, [other])


def test_diet_amount_rejects_preparation_only_text():
    error = report_store._diet_output_error(
        _diet("橘皮饭", "同粳米煮饭，佐餐食用"), [ORANGE])
    assert error and "报告未保存" in error


def test_unknown_amount_does_not_exempt_recipe_candidate():
    assert report_store._diet_output_error(_diet("橘皮饭", "未提供"), [ORANGE]) is None
    error = report_store._diet_output_error(_diet("橘皮饭", "未提供"), [])
    assert error and "未提供" in error and "候选" in error
    assert report_store._diet_output_error(_diet("一般饮食原则", "未提供"), []) is None
