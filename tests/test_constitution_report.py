import json
from pathlib import Path
import shutil

import llm_client
from constitution_store import build_assessment
from report_store import generate_and_store_report
from src.constitution_assessment import CONSTITUTIONS, RULE_ENTRIES


def _corpus(tmp_path):
    composite = tmp_path / "composite"
    standard = composite / "diagnostics" / "gbt46939-2025.md"
    standard.parent.mkdir(parents=True)
    standard.write_text(
        "# GB/T 46939—2025 合成标准\n标准 ID：GB/T 46939—2025\n", encoding="utf-8")
    diet = composite / "diet-lifestyle" / "constitution-diet.md"
    diet.parent.mkdir(parents=True)
    entries = []
    for constitution in CONSTITUTIONS:
        entries.append(
            f"食疗资料｜{constitution}：{constitution}合成食养｜出处：合成资料｜"
            f"主要材料：{constitution}食材 10 克｜制作方法：合成制法｜"
            "项目边界：合成特殊人群、过敏及用药提示。")
    diet.write_text("\n".join(entries) + "\n", encoding="utf-8")
    formula = composite / "formulas" / "formula-system.md"
    formula.parent.mkdir(parents=True)
    formula.write_text("方证合成资料\n", encoding="utf-8")
    roots = {}
    for category, directory in (("constitution", "diagnostics"),
                                ("diet", "diet-lifestyle"), ("formula", "formulas")):
        target = tmp_path / category
        target.mkdir()
        shutil.copytree(composite / directory, target / directory)
        roots[category] = str(target)
    return roots


def _assessment(constitution=None, unknown=False, skipped=False):
    if skipped:
        return build_assessment({}, None, skipped=True, final=True)
    answers = {entry.entry_id: "1" for entry in RULE_ENTRIES}
    targets = {constitution} if isinstance(constitution, str) else set(constitution or ())
    targets.discard("平和质")
    for entry in RULE_ENTRIES:
        if entry.constitution in targets:
            answers[entry.entry_id] = "5"
    unanswered = []
    if unknown and constitution:
        entry = next(entry for entry in RULE_ENTRIES if entry.constitution == constitution)
        del answers[entry.entry_id]
        unanswered = [entry.entry_id]
    return build_assessment(answers, "female", unanswered=unanswered, final=True)


def _run_report(tmp_path, assessment, diet_advice=None, six_diseases="太阴病",
                configure_kb=None, danger_flags=None, existing_report=False, before=None):
    roots = _corpus(tmp_path)
    if configure_kb:
        configure_kb(roots)
    daily = tmp_path / "records" / "daily"
    daily.mkdir(parents=True)
    raw = {
        "date": "2026-11-18",
        "observations": {},
        "inquiry": {},
        "danger_flags": danger_flags or {"triggered": [], "not_triggered": []},
    }
    if assessment is not None:
        raw["constitution_assessment"] = assessment
    if existing_report:
        raw["diagnosis"] = {"report": {"markdown": "OLD-REPORT",
                                       "generated_at": "2026-01-01T00:00:00+00:00"}}
    path = daily / "2026-11-18_analysis.json"
    path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    if before is not None:
        before.append(path.read_bytes())
    prompts = []

    def fake_chat(user_input, *args, **kwargs):
        prompts.append(user_input)
        return json.dumps({
            "structured": {
                "three_views": {}, "four_patterns": {}, "six_diseases": six_diseases,
                "core_pathomechanism": "",
                "diet_advice": ({"daily_foods": [], "med_foods": [], "avoid": []}
                                if diet_advice is None else diet_advice),
                "lifestyle": {},
            },
            "markdown": "# 合成报告",
        }, ensure_ascii=False)

    original_chat = llm_client.chat
    llm_client.chat = fake_chat
    try:
        result = generate_and_store_report(
            str(daily), str(tmp_path / "records" / "_backup"), "2026-11-18",
            lambda: {"model": "synthetic", "base_url": "http://127.0.0.1/unused",
                     "api_key": "synthetic", "kb_roots": roots,
                     "kb_cache_root": str(tmp_path / "cache")})
    finally:
        llm_client.chat = original_chat
    saved = json.loads(path.read_text(encoding="utf-8"))
    return result, saved, prompts


def test_report_input_has_independent_assessment_without_replacing_six_diseases(tmp_path):
    result, saved, prompts = _run_report(tmp_path, _assessment())

    assert result["ok"], result
    assert "国标体质评估（独立视图，不是六经／四证结果）" in prompts[0]
    assert "GB/T 46939—2025" in prompts[0]
    assert "平和质" in prompts[0] and "75.00" in prompts[0]
    assert "不得把本区结果写入 six_diseases" in prompts[0]
    assert saved["constitution_assessment"]["evaluation"]["results"]["平和质"]["result"] == "是"
    assert saved["pattern_differentiation"]["six_diseases"] == "太阴病"


def test_only_eligible_constitution_diet_candidates_are_sent(tmp_path):
    result, saved, prompts = _run_report(tmp_path, _assessment("阳虚质"))

    assert result["ok"], result
    refs = saved["diagnosis"]["report"]["kb_refs"]
    candidates = [ref for ref in refs if ref["excerpt"].startswith("食疗资料｜")]
    assert candidates
    assert all(ref["excerpt"].startswith("食疗资料｜阳虚质：") for ref in candidates)
    assert any(ref["term"] == "食疗资料｜阳虚质：" and ref["domain"] == "diet"
               for ref in candidates)
    assert "食疗资料｜阳虚质：" in prompts[0]


def test_unknown_skipped_or_unassessed_constitution_has_no_diet_candidates(tmp_path):
    cases = (
        ("unknown", _assessment("气虚质", unknown=True), "未知类别："),
        ("skipped", _assessment(skipped=True), "用户整体跳过"),
        ("unassessed", None, "未评估；不得从观察"),
    )
    for name, assessment, message in cases:
        result, saved, prompts = _run_report(tmp_path / name, assessment)
        assert result["ok"], result
        assert message in prompts[0]
        refs = saved["diagnosis"]["report"].get("kb_refs", [])
        assert not [ref for ref in refs if ref["excerpt"].startswith("食疗资料｜")]
        assert "食疗资料｜" not in prompts[0]


def _diet_item(**changes):
    item = {
        "name": "气虚质：气虚质合成食养",
        "nature": "资料未载明",
        "purpose": "资料未载明",
        "amount": "气虚质食材 10 克",
        "note": "合成特殊人群、过敏及用药提示。",
        "constitution": "气虚质",
        "source": "diet-lifestyle/constitution-diet.md:2",
    }
    item.update(changes)
    return item


def test_wrong_constitution_or_source_is_rejected_without_changing_record(tmp_path):
    for name, field, value in (
        ("constitution", "constitution", "阳虚质"),
        ("source", "source", "diet-lifestyle/constitution-diet.md:3"),
    ):
        assessment = _assessment("气虚质")
        result, saved, _ = _run_report(
            tmp_path / name, assessment,
            diet_advice={"daily_foods": [_diet_item(**{field: value})],
                         "med_foods": [], "avoid": []})
        assert result["ok"] is False
        assert "体质食养" in result["error"]
        assert saved == {
            "date": "2026-11-18", "observations": {}, "inquiry": {},
            "danger_flags": {"triggered": [], "not_triggered": []},
            "constitution_assessment": assessment,
        }


def test_unsourced_amount_cross_candidate_frequency_and_missing_safety_are_rejected(tmp_path):
    cases = (
        ("invented", {"amount": "气虚质食材 20 克"}),
        ("cross", {"amount": "阳虚质食材 10 克"}),
        ("frequency", {"amount": "气虚质食材 10 克，每日 1 次"}),
        ("safety", {"note": "无特殊提示。"}),
    )
    for name, changes in cases:
        assessment = _assessment("气虚质")
        result, saved, _ = _run_report(
            tmp_path / name, assessment,
            diet_advice={"daily_foods": [_diet_item(**changes)],
                         "med_foods": [], "avoid": []})
        assert result["ok"] is False, name
        assert "报告未保存" in result["error"]
        assert "diagnosis" not in saved

    result, saved, _ = _run_report(
        tmp_path / "valid", _assessment("气虚质"),
        diet_advice={"daily_foods": [_diet_item()], "med_foods": [], "avoid": []})
    assert result["ok"], result
    item = saved["diagnosis"]["report"]["diet_advice"]["daily_foods"][0]
    assert item["constitution"] == "气虚质"
    assert item["source"] == "diet-lifestyle/constitution-diet.md:2"


def test_detail_shows_constitution_diet_provenance_and_respects_diet_switch(tmp_path):
    import envfile
    from app import create_app

    result, _, _ = _run_report(
        tmp_path, _assessment("气虚质"),
        diet_advice={"daily_foods": [_diet_item()], "med_foods": [], "avoid": []})
    assert result["ok"], result
    env = tmp_path / "web.env"
    env.write_text("VISION_DISABLED=1\n", encoding="utf-8")
    envfile.write_env(str(env), {
        "TCM_KB_ALLOW_EXTERNAL_KB": "1",
        "LLM_API_KEY": "sk-synthetic", "LLM_MODEL": "synthetic",
        "LLM_BASE_URL": "https://example.invalid/v1/chat/completions",
        **{f"TCM_KB_{category.upper()}_ROOT": str(tmp_path / category)
           for category in ("constitution", "diet", "formula")},
    })
    app = create_app(env_file=str(env), data_root=str(tmp_path))
    app.config["TESTING"] = True
    client = app.test_client()
    client.post("/welcome", headers={"Origin": "http://localhost"})

    html = client.get("/record/2026-11-18").get_data(as_text=True)
    assert 'id="constitution-assessment"' in html
    assert ('class="diet-provenance">气虚质 · '
            'diet-lifestyle/constitution-diet.md:2</div>') in html

    envfile.write_env(str(env), {"TCM_KB_DIET_DISABLED": "1"})
    html = client.get("/record/2026-11-18").get_data(as_text=True)
    assert 'id="constitution-assessment"' in html
    assert "气虚质：气虚质合成食养" not in html
    assert "diet-provenance" not in html

    envfile.write_env(str(env), {"TCM_KB_DIET_DISABLED": ""})
    html = client.get("/record/2026-11-18").get_data(as_text=True)
    assert 'class="diet-provenance">气虚质 · ' in html


def test_all_nine_constitutions_retrieve_only_their_own_diet_candidate(tmp_path):
    for constitution in CONSTITUTIONS:
        result, saved, _ = _run_report(tmp_path / constitution, _assessment(constitution))
        assert result["ok"], (constitution, result)
        refs = saved["diagnosis"]["report"]["kb_refs"]
        candidates = [ref for ref in refs if ref["excerpt"].startswith("食疗资料｜")]
        assert candidates, constitution
        assert all(ref["excerpt"].startswith(f"食疗资料｜{constitution}：")
                   for ref in candidates)


def test_combined_constitutions_keep_both_results_and_diet_candidates(tmp_path):
    result, saved, prompts = _run_report(tmp_path, _assessment(("气虚质", "阳虚质")))

    assert result["ok"], result
    assessment = saved["constitution_assessment"]["evaluation"]
    assert [item["constitution"] for item in assessment["combined_results"]] == [
        "气虚质", "阳虚质"]
    refs = saved["diagnosis"]["report"]["kb_refs"]
    candidates = [ref for ref in refs if ref["excerpt"].startswith("食疗资料｜")]
    assert {_constitution for _constitution in CONSTITUTIONS
            if any(ref["excerpt"].startswith(f"食疗资料｜{_constitution}：")
                   for ref in candidates)} == {"气虚质", "阳虚质"}
    assert "兼夹结果：气虚质（是，100.00）、阳虚质（是，100.00）" in prompts[0]


def test_peaceful_assessment_does_not_hide_danger_input(tmp_path):
    result, saved, prompts = _run_report(
        tmp_path, _assessment(),
        danger_flags={"triggered": ["daiyang"], "not_triggered": []})

    assert result["ok"], result
    assert saved["constitution_assessment"]["evaluation"]["results"]["平和质"]["result"] == "是"
    assert "危险信号：daiyang" in prompts[0]
    assert "平和质：75.00（是）" in prompts[0]
    assert "平和或其他体质结果均不覆盖危险信号" in prompts[0]


def test_no_diet_hit_is_disclosed_without_inventing_candidate(tmp_path):
    def no_hits(roots):
        path = Path(roots["diet"]) / "diet-lifestyle" / "constitution-diet.md"
        path.write_text("本次合成资料不含任何食养候选。\n", encoding="utf-8")

    result, saved, prompts = _run_report(
        tmp_path, _assessment("气虚质"), configure_kb=no_hits)

    assert result["ok"], result
    report = saved["diagnosis"]["report"]
    assert report["kb_categories"]["diet"]["status"] == "no_hits"
    assert "食疗知识库状态：已配置但本次未命中相关条文" in prompts[0]
    assert "食疗资料｜" not in prompts[0]


def test_missing_categories_hide_assessment_or_diet_without_cross_leak(tmp_path):
    for category in ("constitution", "diet", "formula"):
        def remove(roots, category=category):
            roots[category] = None

        result, saved, prompts = _run_report(
            tmp_path / category, _assessment("气虚质"), six_diseases="",
            configure_kb=remove)
        assert result["ok"], (category, result)
        report = saved["diagnosis"]["report"]
        assert report["kb_categories"][category]["status"] == "unconfigured"
        if category == "constitution":
            assert "体质知识库不可用，本次不向模型提供既有评估结果" in prompts[0]
            assert "气虚质：100.00" not in prompts[0]
        if category == "diet":
            assert "气虚质：100.00" in prompts[0]
            assert "食疗资料｜" not in prompts[0]
        if category == "formula":
            assert "方剂知识库状态：未配置" in prompts[0]


def test_constitution_entry_anchor_ignores_title_and_explanation_noise(tmp_path):
    def add_noise(roots):
        path = Path(roots["diet"]) / "diet-lifestyle" / "constitution-diet-examples.md"
        path.write_text("阳虚质资料标题\n阳虚质说明文字\n", encoding="utf-8")

    result, saved, _ = _run_report(
        tmp_path, _assessment("阳虚质"), configure_kb=add_noise)

    assert result["ok"], result
    refs = saved["diagnosis"]["report"]["kb_refs"]
    candidates = [ref for ref in refs if ref["excerpt"].startswith("食疗资料｜")]
    assert candidates
    assert all(ref["excerpt"].startswith("食疗资料｜阳虚质：") for ref in candidates)


def _assert_rejected_unchanged(tmp_path, assessment, diet_advice, configure_kb=None):
    before = []
    result, _, _ = _run_report(
        tmp_path, assessment, diet_advice=diet_advice, configure_kb=configure_kb,
        existing_report=True, before=before)
    assert result["ok"] is False, result
    path = tmp_path / "records" / "daily" / "2026-11-18_analysis.json"
    assert path.read_bytes() == before[0]
    assert b"OLD-REPORT" in before[0]


def test_unsourced_general_food_amount_is_rejected_and_preserves_old_report(tmp_path):
    item = {"name": "普通合成食品", "nature": "", "purpose": "",
            "amount": "普通合成食品 999 克", "note": "", "constitution": "", "source": ""}
    _assert_rejected_unchanged(
        tmp_path, _assessment("气虚质"),
        {"daily_foods": [item], "med_foods": [], "avoid": []})


def test_preparation_text_cannot_be_used_as_constitution_diet_amount(tmp_path):
    _assert_rejected_unchanged(
        tmp_path, _assessment("气虚质"),
        {"daily_foods": [_diet_item(amount="合成制法")], "med_foods": [], "avoid": []})


def test_missing_source_boundary_is_not_a_valid_constitution_candidate(tmp_path):
    def remove_boundary(roots):
        path = Path(roots["diet"]) / "diet-lifestyle" / "constitution-diet.md"
        lines = path.read_text(encoding="utf-8").splitlines()
        lines[1] = "｜".join(part for part in lines[1].split("｜")
                            if not part.startswith("项目边界："))
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    _assert_rejected_unchanged(
        tmp_path, _assessment("气虚质"),
        {"daily_foods": [_diet_item(note="")], "med_foods": [], "avoid": []},
        configure_kb=remove_boundary)


def test_blank_provenance_cannot_bypass_unknown_skipped_or_unassessed(tmp_path):
    for name, assessment in (
        ("unknown", _assessment("气虚质", unknown=True)),
        ("skipped", _assessment(skipped=True)),
        ("unassessed", None),
    ):
        item = _diet_item(amount="未提供", constitution="", source="")
        _assert_rejected_unchanged(
            tmp_path / name, assessment,
            {"daily_foods": [item], "med_foods": [], "avoid": []})


def test_eight_combined_constitutions_keep_formula_candidate_within_budget(tmp_path):
    def add_second_candidate_per_constitution(roots):
        path = Path(roots["diet"]) / "diet-lifestyle" / "constitution-diet-principles.md"
        path.write_text("\n".join(
            f"食疗资料｜{name}：{name}合成原则｜出处：合成资料｜"
            "项目边界：合成特殊人群、过敏及用药提示。"
            for name in CONSTITUTIONS[1:]) + "\n", encoding="utf-8")

    result, saved, _ = _run_report(
        tmp_path, _assessment(CONSTITUTIONS[1:]),
        configure_kb=add_second_candidate_per_constitution)

    assert result["ok"], result
    refs = saved["diagnosis"]["report"]["kb_refs"]
    assert any(ref.get("domain") == "formula_pattern" for ref in refs)
    candidates = [ref for ref in refs if ref["excerpt"].startswith("食疗资料｜")]
    assert {ref["excerpt"].split("｜", 2)[1].split("：", 1)[0]
            for ref in candidates} == set(CONSTITUTIONS[1:])
    assert len(refs) <= 10
    assert sum(len(ref["excerpt"]) for ref in refs) <= 12000


def test_short_recipe_name_cannot_bypass_unknown_or_missing_candidate(tmp_path):
    def no_candidate(roots):
        path = Path(roots["diet"]) / "diet-lifestyle" / "constitution-diet.md"
        path.write_text("没有候选的合成资料\n", encoding="utf-8")

    cases = (
        ("unknown", _assessment("气虚质", unknown=True), None),
        ("skipped", _assessment(skipped=True), None),
        ("unassessed", None, None),
        ("no-candidate", _assessment("气虚质"), no_candidate),
    )
    for name, assessment, configure in cases:
        item = _diet_item(name="参芪鹌鹑汤", amount="未提供",
                          constitution="", source="")
        _assert_rejected_unchanged(
            tmp_path / name, assessment,
            {"daily_foods": [item], "med_foods": [], "avoid": []},
            configure_kb=configure)


def test_legal_short_recipe_name_uses_current_candidate_and_provenance(tmp_path):
    def add_short_candidate(roots):
        path = Path(roots["diet"]) / "diet-lifestyle" / "constitution-diet.md"
        with path.open("a", encoding="utf-8") as handle:
            handle.write("食疗资料｜气虚质：参芪鹌鹑汤｜出处：合成资料｜"
                         "主要材料：党参 15 克｜项目边界：合成特殊人群、过敏及用药提示。\n")

    item = _diet_item(name="参芪鹌鹑汤", amount="未提供",
                      source="diet-lifestyle/constitution-diet.md:10")
    result, saved, _ = _run_report(
        tmp_path, _assessment("气虚质"),
        diet_advice={"daily_foods": [item], "med_foods": [], "avoid": []},
        configure_kb=add_short_candidate)
    assert result["ok"], result
    assert saved["diagnosis"]["report"]["diet_advice"]["daily_foods"][0] == item


_SHORT_RECIPE_NAMES = {
    "气虚质": "参芪鹌鹑汤", "阳虚质": "枸杞炖羊肉", "阴虚质": "乌鸡汤",
    "痰湿质": "荷叶粥", "湿热质": "薏米绿豆汤", "血瘀质": "山楂红糖水",
    "气郁质": "杞瑰茶", "特禀质": "乌梅粥",
}


def test_all_recipe_short_names_require_candidate_in_every_empty_state(tmp_path):
    def no_candidate(roots):
        path = Path(roots["diet"]) / "diet-lifestyle" / "constitution-diet.md"
        path.write_text("没有候选的合成资料\n", encoding="utf-8")

    for constitution, short_name in _SHORT_RECIPE_NAMES.items():
        cases = (
            ("unknown", _assessment(constitution, unknown=True), None),
            ("skipped", _assessment(skipped=True), None),
            ("unassessed", None, None),
            ("no-candidate", _assessment(constitution), no_candidate),
            ("missing-diet", _assessment(constitution),
             lambda roots: roots.__setitem__("diet", None)),
        )
        for state, assessment, configure in cases:
            item = _diet_item(name=short_name, amount="未提供",
                              constitution="", source="")
            _assert_rejected_unchanged(
                tmp_path / constitution / state, assessment,
                {"daily_foods": [item], "med_foods": [], "avoid": []},
                configure_kb=configure)


def test_general_diet_principle_remains_valid_without_candidate(tmp_path):
    item = {"name": "一般饮食原则", "nature": "资料未载明",
            "purpose": "资料未载明", "amount": "未提供",
            "note": "均衡、规律饮食；具体条目仍需候选。", "constitution": "", "source": ""}
    result, saved, _ = _run_report(
        tmp_path, None,
        diet_advice={"daily_foods": [item], "med_foods": [], "avoid": []})
    assert result["ok"], result
    assert saved["diagnosis"]["report"]["diet_advice"]["daily_foods"] == [item]
