"""B14-A：坏档、报告 schema 与日期边界的真实调用回归。"""
import datetime
import json
import os
import shutil
import sys

import pytest

pytest.importorskip("flask")

from app import create_app
import input_validator
import llm_client
import records_store
import trends_store
import wizard_store

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "2026-06-25_analysis.json")


@pytest.fixture
def data_root(tmp_path):
    root = tmp_path / "data"
    daily = root / "records" / "daily"
    daily.mkdir(parents=True)
    shutil.copyfile(FIXTURE, daily / "2026-06-25_analysis.json")
    return root


@pytest.fixture
def client(data_root, tmp_path, monkeypatch):
    for key in ("VISION_API_KEY", "WEB_ADMIN_TOKEN", "WEB_HOST"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("LLM_API_KEY", "synthetic-key")
    monkeypatch.setenv("LLM_MODEL", "synthetic-model")
    monkeypatch.setenv("LLM_BASE_URL", "https://example.invalid/v1/chat/completions")
    app = create_app(env_file=str(tmp_path / ".env"), data_root=str(data_root))
    app.config["TESTING"] = True
    client = app.test_client()
    client.post("/welcome", headers={"Origin": "http://localhost"})
    return client


def _write(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(raw, bytes):
        path.write_bytes(raw)
    else:
        path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")


def _fixture_raw():
    with open(FIXTURE, encoding="utf-8") as file:
        return json.load(file)


@pytest.mark.parametrize("structured", [[], "bad", {"three_views": []}])
def test_report_schema_is_rejected_without_mutation(client, data_root, monkeypatch,
                                                     structured):
    monkeypatch.setattr(llm_client, "chat", lambda *args, **kwargs: json.dumps(
        {"structured": structured, "markdown": "# 合成报告"}, ensure_ascii=False))
    path = data_root / "records" / "daily" / "2026-06-25_analysis.json"
    before = path.read_bytes()
    resp = client.post("/record/2026-06-25/report")
    assert resp.status_code == 400
    assert "契约" in resp.get_json()["error"]
    assert path.read_bytes() == before


def test_detail_bad_schema_degrades_with_warning(client, data_root, capsys):
    raw = _fixture_raw()
    raw["pattern_differentiation"] = {"three_views": ["表", "寒"]}
    raw["diagnosis"] = {"report": {"markdown": ["坏", "类型"]}}
    _write(data_root / "records" / "daily" / "2026-06-25_analysis.json", raw)
    resp = client.get("/record/2026-06-25")
    assert resp.status_code == 200
    assert "警告" in capsys.readouterr().err


def test_non_utf8_record_and_draft_do_not_break_pages(client, data_root, capsys):
    bad = {"date": "2026-06-24", "observations": {}, "note": "中文"}
    _write(data_root / "records" / "daily" / "2026-06-24_analysis.json",
           json.dumps(bad, ensure_ascii=False).encode("gbk"))
    assert client.get("/").status_code == 200
    assert client.get("/trends?week=2026-06-25").status_code == 200

    today = wizard_store.datetime.date.today().isoformat()
    draft = data_root / "records" / "daily" / f".wizard-{today}.json"
    _write(draft, b"\xff\xfe\x00")
    assert client.get("/wizard").status_code == 200
    assert list((data_root / "records" / "daily").glob(f".wizard-{today}.json.*.corrupt"))
    assert "警告" in capsys.readouterr().err


def test_filename_is_record_identity_everywhere(client, data_root):
    wrong = _fixture_raw()
    _write(data_root / "records" / "daily" / "2026-06-24_analysis.json", wrong)
    _write(data_root / "records" / "daily" / "2026-06-25_analysis.json", wrong)
    photo = data_root / "records" / "photos" / "2026-06-25" / "舌面.jpg"
    _write(photo, b"synthetic-photo")

    index = client.get("/").get_data(as_text=True)
    assert "/record/2026-06-25" in index
    html = client.get("/record/2026-06-25").get_data(as_text=True)
    assert 'var RECORD_DATE = "2026-06-25";' in html
    assert "/photos/2026-06-25/舌面.jpg" in html
    assert client.get("/trends?week=2026-06-25").status_code == 200


def test_bad_internal_date_and_triggered_element_are_safe(client, data_root):
    raw = _fixture_raw()
    raw["date"] = "2026/06/25"
    raw["danger_flags"] = {"triggered": [{"bad": "dict"}], "not_triggered": []}
    path = data_root / "records" / "daily" / "2026-06-25_analysis.json"
    _write(path, raw)
    assert client.get("/").status_code == 200
    assert client.get("/record/2026-06-25").status_code == 200
    assert client.get("/trends?week=2026-06-25").status_code == 200
    errors = input_validator.validate_record(str(path))[1]
    assert any("date" in error for error in errors)
    assert any("triggered[0]" in error for error in errors)


@pytest.mark.parametrize("path", [
    "/?m=2026-02-30", "/?m=2026-13", "/?m=0000-01",
    "/trends?week=2026-02-30", "/trends?week=2026-13-45",
])
def test_invalid_date_parameters_fall_back(client, path):
    assert client.get(path).status_code == 200


def test_record_rejects_impossible_date(client):
    assert client.get("/record/2026-02-30").status_code == 404


@pytest.mark.parametrize("month,boundary", [("9999-12", "next"), ("0001-01", "prev")])
def test_calendar_boundaries_do_not_overflow(month, boundary):
    result = records_store.calendar_month("unused", month, "2026-06-25")
    assert result[boundary] is None


@pytest.mark.parametrize("week,link_text", [
    ("9999-12-31", "下一周 ›</a>"), ("0001-01-01", "‹ 上一周</a>"),
])
def test_trends_boundaries_hide_navigation(client, week, link_text):
    resp = client.get(f"/trends?week={week}")
    assert resp.status_code == 200
    assert link_text not in resp.get_data(as_text=True)


def test_weekly_main_handles_numeric_date_and_min_date(tmp_path, monkeypatch):
    import generate_weekly_report as gwr
    daily = tmp_path / "daily"
    daily.mkdir()
    raw = _fixture_raw()
    raw["date"] = 20260625
    _write(daily / "2026-06-25_analysis.json", raw)
    monkeypatch.setattr(gwr, "RECORDS_DIR", str(daily))
    monkeypatch.setattr(gwr, "WEEKLY_DIR", str(tmp_path / "weekly"))
    monkeypatch.setattr(gwr, "CHARTS_DIR", str(tmp_path / "charts"))
    monkeypatch.setattr(gwr, "generate_radar_chart", lambda *args, **kwargs: None)
    monkeypatch.setattr(gwr, "generate_trend_chart", lambda *args, **kwargs: None)
    monkeypatch.setattr(sys, "argv", ["generate_weekly_report.py", "2026-06-25"])
    gwr.main()
    assert (tmp_path / "weekly" / "YYYY-W00_20260625_report.json").exists()
    assert gwr.load_week_records(datetime.datetime(1, 1, 3)) == []
    monkeypatch.setattr(sys, "argv", ["generate_weekly_report.py", "0001-01-03"])
    gwr.main()


def test_validator_checks_date_and_filename(tmp_path):
    raw = _fixture_raw()
    path = tmp_path / "2026-06-25_analysis.json"
    raw["date"] = "2026-06-24"
    _write(path, raw)
    errors = input_validator.validate_record(str(path))[1]
    assert any("文件名" in error for error in errors)
    raw["date"] = 20260625
    _write(path, raw)
    errors = input_validator.validate_record(str(path))[1]
    assert any("date" in error for error in errors)
