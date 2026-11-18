import copy
import json
import os
from pathlib import Path
import shutil

import pytest

from constitution_store import build_assessment
from kb_evidence import _kb_references, _kb_references_unified
from kb_view import category_for_shared_file
from report_store import build_report_input, generate_and_store_report, report_state
from src.constitution_assessment import RULE_ENTRIES, STANDARD_ID
from src.derived import observation_input_hash
from src.record import DailyRecord
from src.retrieval import inspect_kb

_ANCHORS = ["GB/T 46939—2025", "适宜", "疾病指南", "方证"]
_DIRECTORIES = {"constitution": "diagnostics", "diet": "diet-lifestyle",
                "formula": "formulas"}


def _corpus(tmp_path):
    composite = tmp_path / "composite"
    files = {
        "diagnostics/gbt46939-2025.md":
            "# GB/T 46939—2025 合成标准\n问卷版本：synthetic-v1\n"
            "合成发病倾向甲：高血压。\n合成发病倾向乙：高血压。\n",
        "diagnostics/diagnostic-framework.md": "独立六经与四证合成资料\n",
        "diet-lifestyle/constitution-diet.md": "体质食养合成资料，适宜边界。\n",
        "diet-lifestyle/nhc-synthetic-2023.md": "高血压疾病指南合成证型与食养边界。\n",
        "formulas/formula-system.md": "方证合成资料，不由体质选方。\n",
        "synonym_map.yaml": "过敏体质:\n  - 特禀质\n",
    }
    for relative, text in files.items():
        path = composite / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    roots = {}
    for category, directory in _DIRECTORIES.items():
        target = tmp_path / category
        target.mkdir()
        shutil.copytree(composite / directory, target / directory)
        shutil.copyfile(composite / "synonym_map.yaml", target / "synonym_map.yaml")
        roots[category] = str(target)
    return composite, roots


def _record(assessment=False):
    raw = {
        "date": "2026-06-25",
        "observations": {"tongue": {"body": {"color": "淡红"}}},
        "inquiry": {},
        "danger_flags": {"triggered": [], "not_triggered": []},
    }
    if assessment:
        raw["constitution_assessment"] = build_assessment(
            {entry.entry_id: "3" for entry in RULE_ENTRIES}, "female", final=True)
    return DailyRecord(raw)


def _signature(refs):
    return [(ref["file"], ref["line"], ref["excerpt"], ref["term"],
             ref.get("domain")) for ref in refs]


def _categories(roots):
    return {category: inspect_kb(root) for category, root in roots.items()}


def test_domain_versions_use_content_and_ignore_timestamp(tmp_path):
    composite, roots = _corpus(tmp_path)
    expected = {
        "diagnostics/gbt46939-2025.md": "constitution_standard",
        "diet-lifestyle/constitution-diet.md": "diet",
        "diet-lifestyle/nhc-synthetic-2023.md": "disease_guideline",
        "formulas/formula-system.md": "formula_pattern",
    }
    first = inspect_kb(str(composite))
    assert set(first["domain_revisions"]) == set(expected.values())
    category_domains = {
        "constitution": {"constitution_standard"},
        "diet": {"diet", "disease_guideline"},
        "formula": {"formula_pattern"},
    }
    for category, root in roots.items():
        assert inspect_kb(root)["domain_revisions"] == {
            domain: first["domain_revisions"][domain]
            for domain in category_domains[category]}
    timestamp_only = composite / "diagnostics" / "gbt46939-2025.md"
    stat = timestamp_only.stat()
    os.utime(timestamp_only, ns=(stat.st_atime_ns + 1, stat.st_mtime_ns + 1))
    assert inspect_kb(str(composite))["revision"] == first["revision"]

    for relative, domain in expected.items():
        path = composite / relative
        stat = path.stat()
        path.write_text(path.read_text(encoding="utf-8") + "内容甲\n", encoding="utf-8")
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        changed = inspect_kb(str(composite))
        assert changed["revision"] != first["revision"]
        assert changed["domain_revisions"][domain] != first["domain_revisions"][domain]
        path.write_text(path.read_text(encoding="utf-8").removesuffix("内容甲\n"),
                        encoding="utf-8")
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        restored = inspect_kb(str(composite))
        assert restored["revision"] == first["revision"]
        assert restored["domain_revisions"] == first["domain_revisions"]


def test_standard_and_other_domains_share_budget_without_losing_provenance(tmp_path):
    _, roots = _corpus(tmp_path)
    refs = _kb_references_unified(_record(), roots, _ANCHORS,
                                  cache_root=str(tmp_path / "cache"))
    assert refs[0]["domain"] == "constitution_standard"
    domains = {ref["file"]: ref["domain"] for ref in refs}
    assert domains["diet-lifestyle/constitution-diet.md"] == "diet"
    assert domains["diet-lifestyle/nhc-synthetic-2023.md"] == "disease_guideline"
    assert domains["formulas/formula-system.md"] == "formula_pattern"
    text = build_report_input(_record(), refs, kb_status={
        category: "retrieved" for category in _DIRECTORIES})
    for label in ("国标体质标准", "体质食养", "疾病或特定人群指南", "方证资料"):
        assert f"资料领域：{label}" in text


@pytest.mark.parametrize("active", [
    ("constitution", "diet", "formula"),
    ("constitution", "diet"),
    ("constitution", "formula"),
])
def test_split_and_composite_keep_standard_candidates_and_missing_category_boundaries(
        tmp_path, active):
    composite, roots = _corpus(tmp_path)
    scoped = tmp_path / ("scoped-" + "-".join(active))
    shutil.copytree(composite, scoped)
    for category, directory in _DIRECTORIES.items():
        if category not in active:
            shutil.rmtree(scoped / directory)
    anchors = [term for term in _ANCHORS if term != "适宜" or "diet" in active]
    anchors = [term for term in anchors if term != "疾病指南" or "diet" in active]
    anchors = [term for term in anchors if term != "方证" or "formula" in active]
    expected = _kb_references(_record(), kb_root=str(scoped), anchor_terms=anchors)
    for ref in expected:
        ref["category"] = category_for_shared_file(ref["file"], dict.fromkeys(active))
    actual = _kb_references_unified(
        _record(), {category: roots[category] for category in active}, anchors,
        cache_root=str(tmp_path / "cache"))
    assert _signature(actual) == _signature(expected)
    assert [ref["category"] for ref in actual] == [ref["category"] for ref in expected]
    statuses = {category: "retrieved" if category in active else "unconfigured"
                for category in _DIRECTORIES}
    assert build_report_input(_record(), actual, kb_status=statuses) == \
        build_report_input(_record(), expected, kb_status=statuses)
    assert all(ref["category"] in active for ref in actual)


def test_report_state_distinguishes_assessment_version_and_same_stat_content(tmp_path):
    _, roots = _corpus(tmp_path)
    rec = _record(assessment=True)
    assessment = rec.raw["constitution_assessment"]
    categories = _categories(roots)
    rec.raw["diagnosis"] = {"report": {
        "input_hash": observation_input_hash(rec),
        "constitution_assessment": {
            key: assessment[key] for key in
            ("standard_id", "questionnaire_version", "input_hash")},
        "kb_categories": categories,
    }}
    assert report_state(rec, kb_categories=categories)["stale"] is False

    for field, value in (("standard_id", "SYNTHETIC/OLD"),
                         ("questionnaire_version", "synthetic-old")):
        changed = copy.deepcopy(rec.raw)
        changed["constitution_assessment"][field] = value
        state = report_state(DailyRecord(changed), kb_categories=categories)
        assert "体质评估标准或问卷版本已变化" in state["reasons"]
        assert report_state(rec, kb_categories=categories)["stale"] is False
    changed = copy.deepcopy(rec.raw)
    answers = dict(assessment["answers"], **{"GB46939-A2-01": "4"})
    changed["constitution_assessment"] = build_assessment(answers, "female", final=True)
    state = report_state(DailyRecord(changed), kb_categories=categories)
    assert "体质评估输入已变化" in state["reasons"]
    assert report_state(rec, kb_categories=categories)["stale"] is False

    standard = Path(roots["constitution"]) / "diagnostics" / "gbt46939-2025.md"
    stat = standard.stat()
    original = standard.read_text(encoding="utf-8")
    standard.write_text(original.replace("synthetic-v1", "synthetic-v2"),
                        encoding="utf-8")
    os.utime(standard, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    changed_categories = _categories(roots)
    state = report_state(rec, kb_categories=changed_categories)
    assert "知识库目录或内容已变化" in state["reasons"]
    standard.write_text(original, encoding="utf-8")
    os.utime(standard, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    assert report_state(rec, kb_categories=categories)["stale"] is False


def test_report_generation_stores_domain_and_assessment_fingerprints(
        tmp_path, monkeypatch):
    import llm_client

    _, roots = _corpus(tmp_path)
    daily = tmp_path / "records" / "daily"
    daily.mkdir(parents=True)
    raw = _record(assessment=True).raw
    (daily / "2026-06-25_analysis.json").write_text(
        json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    prompts = []

    def fake_chat(user_input, *args, **kwargs):
        prompts.append(user_input)
        return json.dumps({
            "structured": {"three_views": {}, "four_patterns": {}, "six_diseases": "",
                           "core_pathomechanism": "", "diet_advice": {}, "lifestyle": {}},
            "markdown": "# 合成报告\n不输出体质、食养或方药结论。",
        }, ensure_ascii=False)

    monkeypatch.setattr(llm_client, "chat", fake_chat)
    result = generate_and_store_report(
        str(daily), str(tmp_path / "records" / "_backup"), "2026-06-25",
        lambda: {"model": "synthetic", "base_url": "http://127.0.0.1/unused",
                 "api_key": "synthetic", "kb_roots": roots,
                 "kb_cache_root": str(tmp_path / "cache")})
    assert result["ok"], result
    saved = json.loads((daily / "2026-06-25_analysis.json").read_text(encoding="utf-8"))
    report = saved["diagnosis"]["report"]
    assessment = saved["constitution_assessment"]
    assert report["constitution_assessment"] == {
        key: assessment[key] for key in
        ("standard_id", "questionnaire_version", "input_hash")}
    assert report["kb_categories"]["constitution"]["domain_revisions"][
        "constitution_standard"]
    assert report["kb_categories"]["diet"]["domain_revisions"]["disease_guideline"]
    assert any(ref["domain"] == "constitution_standard"
               for ref in report["kb_refs"])
    assert STANDARD_ID.replace(" ", "") in prompts[0]
    assert "资料领域：国标体质标准" in prompts[0], prompts[0]
    assert report_state(DailyRecord(saved), kb_categories=_categories(roots))["stale"] is False


def test_missing_constitution_hides_assessment_card_and_restore(tmp_path):
    import envfile
    from app import create_app

    _, roots = _corpus(tmp_path)
    env = tmp_path / "web.env"
    env.write_text("VISION_DISABLED=1\nLLM_DISABLED=1\n", encoding="utf-8")
    envfile.write_env(str(env), {
        "TCM_KB_ALLOW_EXTERNAL_KB": "1",
        **{f"TCM_KB_{category.upper()}_ROOT": root
           for category, root in roots.items()},
    })
    app = create_app(env_file=str(env), data_root=str(tmp_path / "data"))
    app.config["TESTING"] = True
    client = app.test_client()
    client.post("/welcome", headers={"Origin": "http://localhost"})
    daily = tmp_path / "data" / "records" / "daily"
    daily.mkdir(parents=True, exist_ok=True)
    (daily / "2026-06-25_analysis.json").write_text(
        json.dumps(_record(assessment=True).raw, ensure_ascii=False), encoding="utf-8")

    html = client.get("/record/2026-06-25").get_data(as_text=True)
    assert 'id="constitution-assessment"' in html and "50.00" in html

    envfile.write_env(str(env), {"TCM_KB_CONSTITUTION_DISABLED": "1"})
    html = client.get("/record/2026-06-25").get_data(as_text=True)
    assert 'id="constitution-assessment"' not in html
    assert "缺少中医体质辨证知识库，国标体质评估不可显示" in html
    assert "缺少食疗知识库" not in html and "缺少方剂知识库" not in html

    envfile.write_env(str(env), {"TCM_KB_CONSTITUTION_DISABLED": ""})
    html = client.get("/record/2026-06-25").get_data(as_text=True)
    assert 'id="constitution-assessment"' in html and "50.00" in html


def test_disease_guideline_has_explicit_retrieval_boundary(tmp_path):
    _, roots = _corpus(tmp_path)
    refs = _kb_references_unified(_record(), roots, ["高血压"],
                                  cache_root=str(tmp_path / "cache"),
                                  domain="disease_guideline")
    assert refs and {ref["domain"] for ref in refs} == {"disease_guideline"}
    assert all("疾病指南" in ref["excerpt"] for ref in refs)
    assert build_report_input(_record(), refs, kb_status={
        category: "retrieved" for category in _DIRECTORIES}).count(
            "资料领域：疾病或特定人群指南") == len(refs)


@pytest.mark.parametrize("category,relative,text,domain,query", [
    ("diet", "custom/nhc-synthetic.md", "高血压疾病指南合成内容",
     "disease_guideline", "高血压"),
    ("diet", "custom/food.md", "体质食养合成内容", "diet", "体质食养"),
    ("formula", "custom/formula.md", "方证资料合成内容", "formula_pattern", "方证资料"),
])
def test_custom_dedicated_root_domain_filter_and_content_revision(
        tmp_path, category, relative, text, domain, query):
    from src.retrieval import inspect_kb_categories

    source = tmp_path / category
    target = source / relative
    target.parent.mkdir(parents=True)
    target.write_text(text, encoding="utf-8")
    rec = _record()
    unfiltered = _kb_references_unified(
        rec, {category: str(source)}, [query], cache_root=str(tmp_path / "cache"))
    filtered = _kb_references_unified(
        rec, {category: str(source)}, [query], cache_root=str(tmp_path / "cache"),
        domain=domain)
    assert unfiltered and _signature(filtered) == _signature(unfiltered)
    assert {(ref["category"], ref["domain"]) for ref in filtered} == {(category, domain)}

    info = inspect_kb(str(source), category=category)
    assert info["domain_revisions"][domain]
    states = inspect_kb_categories({
        "TCM_KB_ALLOW_EXTERNAL_KB": "1",
        f"TCM_KB_{category.upper()}_ROOT": str(source),
    })
    assert states[category]["domain_revisions"] == info["domain_revisions"]
    stat = target.stat()
    target.write_text(text.replace("合成内容", "合成变更"), encoding="utf-8")
    os.utime(target, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    changed = inspect_kb(str(source), category=category)
    assert changed["domain_revisions"][domain] != info["domain_revisions"][domain]
    target.write_text(text, encoding="utf-8")
    os.utime(target, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    restored = inspect_kb(str(source), category=category)
    assert restored["domain_revisions"] == info["domain_revisions"]
