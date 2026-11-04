"""B17：趋势、检索、选档与缓存性能；全部为临时合成数据。"""
import json
import os
import threading

import pytest

import generate_weekly_report as g
import records_store
from src.retrieval import retrieve_and
from src.retrieval.grep_search import search
from src.retrieval.rag_search import RagSearch, _chunk_file
from src.retrieval.synonym_loader import expand_many, load_map, _load_map_cached


def _normal_record():
    return {"date": "2026-06-25", "observations": {
        "tongue": {"body": {"color": "淡红"}},
        "head_face": {"face": {"luster": "荣润"}},
        "eye": {"redness": "无"}, "ear": {"color": "正常"},
        "hand": {"palm_color": "淡红"}, "skin": {"color": "正常"},
    }}


def test_all_normal_is_observed_not_missing():
    detail = g.compute_dimension_deviation_detail(_normal_record())
    assert all(item["observed"] for item in detail.values())
    text = g.describe_trend("舌诊", 0, 0, first_n=0, last_n=0,
                            first_observed=True, last_observed=True)
    assert "整体稳定" in text and "无有效观测" not in text
    data = g.generate_weekly_report_data([_normal_record()])
    assert "无有效观测" not in data["summary"]
    assert "重传照片" not in data["next_week_suggestion"]


def test_sum_improvement_does_not_require_max_drop():
    text = g.describe_trend("手诊偏离度", 9, 4, first_max=4, last_max=4,
                            first_n=3, last_n=1, metric_name="累计分")
    assert "异常程度减轻" in text


def test_week_id_uses_actual_rolling_window():
    records = [dict(_normal_record(), date=date) for date in (
        "2026-10-19", "2026-10-20", "2026-10-21", "2026-10-22",
        "2026-10-26", "2026-10-27")]
    data = g.generate_weekly_report_data(records)
    assert data["week_id"] == "2026-10-19_2026-10-27"


def test_rag_filters_noise_empty_chunks_and_finds_hit_line(tmp_path):
    kb = tmp_path / "kb"
    kb.mkdir()
    (kb / "a.md").write_text("# 标题\n---\n无关行\n目标术语所在行\n", encoding="utf-8")
    (kb / "b.md").write_text("完全无关的内容\n", encoding="utf-8")
    engine = RagSearch(str(kb))
    assert engine.search("查无") == []
    result = engine.search("目标术语")
    assert result and result[0]["content"] == "目标术语所在行"
    assert result[0]["line"] == 4
    assert all(chunk.text != "---" for chunk in engine._chunks)


def test_long_lines_are_split_without_content_loss():
    chunks = _chunk_file(["# H", "甲" * 1200], "a.md")
    assert all(len(chunk.text) <= 500 for chunk in chunks)
    assert "甲" * 1200 in "".join(chunk.text for chunk in chunks)


def test_and_rag_results_are_filtered_by_actual_files(tmp_path):
    kb = tmp_path / "kb"
    kb.mkdir()
    (kb / "a.md").write_text("苓桂 五苓\n", encoding="utf-8")
    (kb / "b.md").write_text("只有苓桂\n", encoding="utf-8")

    class FakeRag:
        def is_available(self):
            return True

        def search(self, query, k=5):
            return [{"file": "a.md", "line": 1, "end_line": 1,
                     "content": "苓桂 五苓", "score": 0.9},
                    {"file": "b.md", "line": 1, "end_line": 1,
                     "content": "只有苓桂", "score": 0.9}]

    result = retrieve_and(["苓桂", "五苓"], kb_root=str(kb), rag=FakeRag())
    assert {item["file"] for item in result["results"]} == {"a.md"}
    assert all(item["term"] for item in result["results"])


def test_bad_md_is_skipped_with_warning(tmp_path, capsys):
    kb = tmp_path / "kb"
    kb.mkdir()
    (kb / "bad.md").write_bytes(b"\xff\xfe")
    (kb / "folder.md").mkdir()
    (kb / "good.md").write_text("可用文本\n", encoding="utf-8")
    result = search("可用", kb_root=str(kb))
    assert [item["file"] for item in result] == ["good.md"]
    assert "警告" in capsys.readouterr().err


def test_bom_synonyms_and_independent_dedup(tmp_path):
    path = tmp_path / "synonym_map.yaml"
    path.write_text("便软:\n  - 下利\n  - 便溏\n", encoding="utf-8-sig")
    mapping = load_map(str(path))
    assert mapping["便软"] == ["下利", "便溏"]
    result = expand_many(["便软", "下利"], mapping)
    assert result.synonyms_used == ["便溏"]


def test_missing_synonym_is_quiet_but_bad_synonym_warns(tmp_path, capsys):
    missing = tmp_path / "missing.yaml"
    assert _load_map_cached(str(missing)) == {}
    assert capsys.readouterr().err == ""
    bad = tmp_path / "bad.yaml"
    bad.write_text("- 顶层不是映射\n", encoding="utf-8")
    assert _load_map_cached(str(bad)) == {}
    assert "警告" in capsys.readouterr().err


def test_synonym_resource_limits(tmp_path):
    path = tmp_path / 'synonym_map.yaml'
    path.write_text('key:\n' + '  - 别名\n' * 65, encoding='utf-8')
    with pytest.raises(ValueError, match='别名数量'):
        load_map(str(path))
    path.write_text('key:\n  - ' + '长' * 129 + '\n', encoding='utf-8')
    with pytest.raises(ValueError, match='过长词条'):
        load_map(str(path))
    path.write_text(''.join(f'key{index}:\n  - 别名\n' for index in range(513)),
                    encoding='utf-8')
    with pytest.raises(ValueError, match='键数量'):
        load_map(str(path))


def test_rag_cache_is_normalized_and_thread_safe(tmp_path, monkeypatch):
    from importlib import import_module
    from src.retrieval import dispatcher
    rag_search = import_module("src.retrieval.rag_search")
    dispatcher._RAG_CACHE.clear()
    calls = []
    original_build = rag_search.TfidfBackend.build

    def counting_build(self):
        calls.append(threading.current_thread().name)
        return original_build(self)

    monkeypatch.setattr(rag_search.TfidfBackend, "build", counting_build)
    (tmp_path / "kb").mkdir()
    (tmp_path / "kb" / "a.md").write_text("甲\n", encoding="utf-8")
    root = str(tmp_path / "kb")
    threads = [threading.Thread(
        target=lambda: dispatcher._default_rag(root).search("甲")) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(dispatcher._RAG_CACHE) == 1
    assert len(calls) == 1


def test_special_paths_and_archive_names(tmp_path):
    daily = tmp_path / "weird[1]" / "daily"
    daily.mkdir(parents=True)
    (daily / "2026-06-25_Analysis.JSON").write_text(
        json.dumps({"date": "2026-06-25", "observations": {}}), encoding="utf-8")
    (daily / "2026-06-25_analysis_副本.json").write_text("{}", encoding="utf-8")
    (daily / "2026-06-25_analysis (1).json").write_text("{}", encoding="utf-8")
    selected = records_store.select_daily_file(str(daily), "2026-06-25")
    assert selected.endswith("2026-06-25_Analysis.JSON")
    assert records_store.list_dates(str(daily)) == ["2026-06-25"]


def test_relative_daily_dir_still_prefers_canonical_record(tmp_path, monkeypatch):
    daily = tmp_path / "daily"
    daily.mkdir()
    canonical = daily / "2026-06-25_analysis.json"
    alternate = daily / "2026-06-25_alternate_analysis.json"
    canonical.write_text('{"date":"2026-06-25","tag":"canonical"}', encoding="utf-8")
    alternate.write_text('{"date":"2026-06-25","tag":"alternate"}', encoding="utf-8")
    os.utime(canonical, (1_000_000_000, 1_000_000_000))
    os.utime(alternate, (1_000_000_100, 1_000_000_100))
    monkeypatch.chdir(tmp_path)

    selected = records_store.select_daily_file("daily", "2026-06-25")

    assert os.path.basename(selected) == canonical.name


def test_latest_record_skips_unreadable_candidate(tmp_path):
    daily = tmp_path / "daily"
    daily.mkdir()
    (daily / "2026-06-26_analysis.json").write_text("not-json", encoding="utf-8")
    (daily / "2026-06-25_Analysis.JSON").write_text(
        json.dumps({"date": "2026-06-25", "observations": {}}), encoding="utf-8")
    assert records_store.latest_record_date(str(daily)) == "2026-06-25"


def test_noncanonical_scans_and_summaries_are_cached(tmp_path, monkeypatch):
    daily = tmp_path / "daily"
    daily.mkdir()
    for day in range(1, 9):
        (daily / f"2026-06-{day:02d}_alternate_analysis.json").write_text(json.dumps(
            _normal_record() | {"date": f"2026-06-{day:02d}"}), encoding="utf-8")
    from src import daily_files
    calls = []
    original = daily_files._scan_daily_dir

    def counting(path):
        calls.append(path)
        return original(path)

    summary_calls = []
    original_summary = records_store.record_summary

    def counting_summary(rec):
        summary_calls.append(rec.date)
        return original_summary(rec)

    monkeypatch.setattr(daily_files, "_scan_daily_dir", counting)
    monkeypatch.setattr(records_store, "record_summary", counting_summary)
    assert len(records_store.list_summaries(str(daily), limit=2)) == 2
    records_store.list_summaries(str(daily), limit=2)
    records_store.calendar_month(str(daily), "2026-06", "2026-06-25")
    records_store.calendar_month(str(daily), "2026-06", "2026-06-25")
    assert calls == [str(daily)]
    assert len(summary_calls) == 8


@pytest.mark.parametrize("suffix", [
    ".bak.json", "_copy.json", "_tmp.json", "_旧格式.json", "_副本.json",
    "_备份.json", "_快照.json", "_backup.json", " (1).json",
])
def test_all_archive_suffixes_are_excluded(tmp_path, suffix):
    daily = tmp_path / "daily"
    daily.mkdir()
    path = daily / f"2026-06-25_analysis{suffix}"
    path.write_text("{}", encoding="utf-8")
    assert records_store.select_daily_file(str(daily), "2026-06-25") is None
    assert records_store.list_dates(str(daily)) == []


def test_summary_cache_invalidates_after_file_change(tmp_path):
    daily = tmp_path / "daily"
    daily.mkdir()
    path = daily / "2026-06-25_analysis.json"
    raw = _normal_record()
    path.write_text(json.dumps(raw), encoding="utf-8")
    before = records_store.list_summaries(str(daily))[0]
    raw["observations"]["tongue"]["body"]["color"] = "红"
    path.write_text(json.dumps(raw), encoding="utf-8")
    stat = path.stat()
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))
    after = records_store.list_summaries(str(daily))[0]
    assert after["dims"]["舌诊"] > before["dims"]["舌诊"]


def test_lifecycle_paths_with_glob_characters(tmp_path):
    import lifecycle_store
    root = tmp_path / "weird[1]"
    daily = root / "daily"
    backup = root / "backup"
    photos = root / "photos"
    daily.mkdir(parents=True)
    backup.mkdir()
    raw = _normal_record()
    path = daily / "2026-06-25_analysis.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    records_store.backup_file(str(path), str(backup), purpose="pristine")
    assert lifecycle_store.restore_original(
        str(daily), str(backup), "2026-06-25")["ok"] is True
    draft = daily / ".wizard-2026-06-25.json"
    draft.write_text("{}", encoding="utf-8")
    assert lifecycle_store.delete_day(str(daily), str(backup), str(photos),
                                      "2026-06-25", confirmed=True)["ok"] is True
    assert not path.exists() and not draft.exists()
    assert not list(backup.glob("*.bak"))


def test_trends_fallback_links_to_latest_readable_record(tmp_path):
    from app import create_app
    data_root = tmp_path / "data"
    daily = data_root / "records" / "daily"
    daily.mkdir(parents=True)
    (data_root / "records" / "photos").mkdir()
    (daily / "2026-06-26_analysis.json").write_text("not-json", encoding="utf-8")
    (daily / "2026-06-25_Analysis.JSON").write_text(
        json.dumps(_normal_record()), encoding="utf-8")
    app = create_app(env_file=str(tmp_path / ".env"), data_root=str(data_root))
    app.config["TESTING"] = True
    client = app.test_client()
    client.post("/welcome", headers={"Origin": "http://localhost"})
    response = client.get("/trends?week=2026-01-01")
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert 'href="/trends?week=2026-06-25"' in html
    assert 'href="/trends?week=2026-06-26"' not in html


def test_relative_kb_root_shares_grep_rag_and_synonyms(tmp_path, monkeypatch):
    from src.retrieval import retrieve, dispatcher, kb_paths
    kb = tmp_path / "kb"
    kb.mkdir()
    (kb / "a.md").write_text("下利条文\n", encoding="utf-8")
    (kb / "synonym_map.yaml").write_text("便软:\n  - 下利\n", encoding="utf-8")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.setattr(kb_paths, "_REPO_ROOT", str(tmp_path))
    monkeypatch.setenv("TCM_KB_ROOT", "kb")
    monkeypatch.chdir(elsewhere)
    dispatcher._RAG_CACHE.clear()
    result = retrieve("便软")
    assert "下利" in result["synonyms_used"]
    assert result["grep_hits"] == 1
    assert set(dispatcher._RAG_CACHE) == {str(kb)}
    engine = dispatcher._RAG_CACHE[str(kb)]
    assert engine.kb_root == str(kb)
    assert engine.search("下利")[0]["file"] == "a.md"
