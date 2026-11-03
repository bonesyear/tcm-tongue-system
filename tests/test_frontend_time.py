"""B18：前端交互、日期、时区与 Markdown 边界；仅合成数据和 mock。"""
import datetime
import io
import json
import os

import pytest

import envfile
import mdmini
import records_store
import time_utils
import wizard_store
from app import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("VISION_API_KEY", "sk-test")
    root = tmp_path / "data"
    (root / "records" / "daily").mkdir(parents=True)
    (root / "records" / "photos").mkdir(parents=True)
    app = create_app(env_file=str(tmp_path / ".env"), data_root=str(root))
    app.config["TESTING"] = True
    client = app.test_client()
    client.post("/welcome", headers={"Origin": "http://localhost"})
    return client


def test_settings_toggle_writes_only_its_own_field(client, tmp_path):
    path = tmp_path / ".env"
    envfile.write_env(str(path), {"VISION_MODEL": "saved-model", "LLM_MODEL": "keep-model"})
    response = client.post("/settings/toggle", json={"target": "vision", "enabled": False})
    assert response.status_code == 200 and response.get_json()["ok"] is True
    env = envfile.read_env(str(path))
    assert env["VISION_DISABLED"] == "1"
    assert env["VISION_MODEL"] == "saved-model"
    assert env["LLM_MODEL"] == "keep-model"
    assert "LLM_DISABLED" not in env


def test_settings_toggle_rejects_invalid_input_without_writes(client, tmp_path):
    response = client.post("/settings/toggle", json={"target": "vision", "enabled": "no"})
    assert response.status_code == 400
    assert not (tmp_path / ".env").exists()


def test_welcome_ack_honours_disabled_vision(client, tmp_path):
    envfile.write_env(str(tmp_path / ".env"), {"VISION_DISABLED": "1"})
    response = client.post("/welcome", headers={"Origin": "http://localhost"})
    assert response.headers["Location"] == "/"


def test_mdmini_preserves_loose_ordered_list_and_start():
    html = mdmini.render("3. 第三步\n\n4. 第四步")
    assert html.count("<ol") == 1
    assert '<ol start="3"><li>第三步</li><li>第四步</li></ol>' in html


def test_mdmini_only_discards_real_table_separator():
    html = mdmini.render("| 项 | 值 |\n|---|---|\n| - | - |\n| 尿 | 正常 |")
    assert "<td>-</td><td>-</td>" in html
    assert "<td>尿</td><td>正常</td>" in html


def test_week_stats_ignores_future_and_counts_from_today():
    summaries = [{"date": f"2026-10-{day:02d}", "total": 7}
                 for day in range(20, 27)]
    summaries += [{"date": "2026-10-28", "total": 60},
                  {"date": "2026-10-29", "total": 60}]
    result = records_store.week_stats(summaries, "2026-10-26")
    assert result == {"week_days": 1, "streak": 7, "week_avg": 7}


def test_week_stats_allows_today_not_recorded_yet():
    summaries = [{"date": "2026-06-23", "total": 1},
                 {"date": "2026-06-24", "total": 1}]
    assert records_store.week_stats(summaries, "2026-06-25")["streak"] == 2
    assert records_store.week_stats(summaries, "2026-10-26")["streak"] == 0


def test_timezone_now_and_timestamp_have_explicit_offset(monkeypatch):
    real_datetime = datetime.datetime

    class FakeDateTime(real_datetime):
        @classmethod
        def now(cls, tz=None):
            instant = real_datetime(2026, 10, 26, 19, 11, 46,
                                    tzinfo=datetime.timezone.utc)
            return instant.astimezone(tz)

    monkeypatch.setattr(time_utils.datetime, "datetime", FakeDateTime)
    assert time_utils.today("Asia/Shanghai").isoformat() == "2026-10-27"
    assert time_utils.iso_now("Asia/Shanghai") == "2026-10-27T03:11:46+08:00"


def test_record_timestamp_uses_configured_timezone():
    draft = {"date": "2026-10-27", "parts": {
        part["part"]: {"status": "skip_uncovered"} for part in wizard_store.PARTS}}
    raw = wizard_store.assemble_record(draft, "test", timezone_name="Asia/Shanghai")
    assert raw["timestamp"].endswith("+08:00")
    assert raw["date"] == "2026-10-27"


def test_wizard_keeps_session_date_across_midnight(client, tmp_path, monkeypatch):
    import vision_client
    monkeypatch.setattr(vision_client, "call", lambda *args, **kwargs: (
        0, json.dumps({"舌质颜色": "淡红"}, ensure_ascii=False)))
    current = {"date": datetime.date(2026, 10, 25)}
    monkeypatch.setattr(time_utils, "today", lambda name=None: current["date"])
    from PIL import Image
    image = io.BytesIO()
    Image.new("RGB", (2, 2), (128, 128, 128)).save(image, format="PNG")
    image.seek(0)
    response = client.post("/wizard/photo", data={
        "part": "舌面", "date": "2026-10-25",
        "file": (image, "photo.jpg")}, content_type="multipart/form-data")
    assert response.status_code == 200
    current["date"] = datetime.date(2026, 10, 26)
    for part in wizard_store.PARTS[1:]:
        response = client.post("/wizard/skip", json={
            "part": part["part"], "mode": "normal", "date": "2026-10-25"})
        assert response.status_code == 200
    response = client.post("/wizard/submit", json={"mode": "new", "date": "2026-10-25"})
    assert response.status_code == 200, response.get_json()
    assert response.get_json()["date"] == "2026-10-25"
    daily = tmp_path / "data" / "records" / "daily"
    assert (daily / "2026-10-25_analysis.json").exists()
    assert not (daily / ".wizard-2026-10-26.json").exists()


def test_frontend_accessibility_and_resize_contracts(client):
    wizard = client.get("/wizard").get_data(as_text=True)
    assert 'id="file-input" accept="image/*" capture="environment" style="display:none;"' not in wizard
    assert "PARTS[idx]" in wizard and "PARTS[cur].status = \"observed\"" not in wizard
    assert "pendingSubmit" in wizard and "submitting" in wizard
    assert "showError" in wizard and "redirect: \"manual\"" in wizard
    settings = client.get("/settings").get_data(as_text=True)
    assert ":focus-visible + .slider" in settings
    assert "var payload = new FormData(form);" in settings
    assert settings.index("var payload = new FormData(form);") \
        < settings.index("input.disabled = true;")
    assert "body: payload" in settings
    with open(os.path.join(os.path.dirname(records_store.__file__), "static", "css", "base.css"),
              encoding="utf-8") as handle:
        assert ".grid.cols-2, .grid.cols-3 { grid-template-columns: minmax(0, 1fr); }" in handle.read()


def test_wizard_offers_recent_draft_continuation(client, tmp_path, monkeypatch):
    daily = tmp_path / "data" / "records" / "daily"
    wizard_store.save_draft(str(daily), {
        "date": "2026-11-02", "parts": {"舌面": {"status": "skip_uncovered"}},
    })
    monkeypatch.setattr(time_utils, "today", lambda name=None: datetime.date(2026, 11, 3))
    response = client.get("/wizard")
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "已恢复 2026-11-02 的未完成草稿" in html
    assert 'name="date" value="2026-11-02"' in html


def test_invalid_timezone_warns_and_falls_back(capsys):
    assert time_utils.timezone("Invalid/B18_Test_Zone") is not None
    assert "无效 TCM_TIMEZONE" in capsys.readouterr().err
