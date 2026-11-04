"""B16：恢复、图片与数据生命周期；仅使用合成图片和临时目录。"""
import io
import json

import pytest
from PIL import Image

import llm_client
import records_store
import trends_store
import wizard_store
from src.record import DailyRecord
from test_web_wizard import client, data_root as base_data_root, _mock_observe


@pytest.fixture
def data_root(base_data_root):
    from pathlib import Path
    return Path(base_data_root)


def _jpeg(metadata=True):
    image = Image.new("RGB", (8, 2))
    for x in range(8):
        for y in range(2):
            image.putpixel((x, y), (255, 0, 0) if x < 4 else (0, 0, 255))
    exif = Image.Exif()
    if metadata:
        exif[0x0110] = "SyntheticPhone"
        exif[0x0112] = 6
        exif.get_ifd(0x8825).update({
            1: "N", 2: (1.0, 0.0, 0.0), 3: "E", 4: (2.0, 0.0, 0.0)})
    output = io.BytesIO()
    image.save(output, format="JPEG", exif=exif)
    return output.getvalue()


def _upload(client, content=None, name="photo.png", part="舌面"):
    return client.post("/wizard/photo", data={
        "part": part, "file": (io.BytesIO(content or _jpeg()), name),
    }, content_type="multipart/form-data")


def _today():
    return wizard_store.datetime.date.today().isoformat()


def _manual_record(client, color):
    for part in wizard_store.PARTS:
        client.post("/wizard/skip", json={"part": part["part"], "mode": "normal"})
    assert client.post("/wizard/manual", json={
        "part": "舌面", "indicator": "body_color", "value": color}
    ).status_code == 200
    resp = client.post("/wizard/submit", json={"mode": "new"})
    assert resp.status_code == 200, resp.get_json()
    return resp.get_json()["date"]


def _raw(data_root, date):
    return json.loads((data_root / "records" / "daily" / f"{date}_analysis.json")
                      .read_text(encoding="utf-8"))


def test_upload_strips_metadata_bakes_orientation_and_stages(client, data_root, monkeypatch):
    _mock_observe(monkeypatch)
    resp = _upload(client)
    assert resp.status_code == 200, resp.get_json()
    staging = data_root / "records" / "photos" / _today() / ".staging"
    files = list(staging.glob("*.jpg"))
    assert len(files) == 1
    assert not (data_root / "records" / "photos" / _today() / "舌面.jpg").exists()
    with Image.open(files[0]) as image:
        assert image.size == (2, 8)
        assert image.getpixel((0, 0))[0] > image.getpixel((0, 0))[2]
        assert image.getpixel((0, 7))[2] > image.getpixel((0, 7))[0]
        assert not image.getexif()
        assert "SyntheticPhone" not in str(image.info)


def test_failed_vision_preserves_committed_photo(client, data_root, monkeypatch):
    photo = data_root / "records" / "photos" / _today() / "舌面.jpg"
    photo.parent.mkdir(parents=True, exist_ok=True)
    photo.write_bytes(b"original-committed")
    monkeypatch.setattr("vision_client.call",
                        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("synthetic failure")))
    resp = _upload(client)
    assert resp.status_code == 502
    assert resp.get_json()["photo_saved"] is True
    assert resp.get_json()["staged"] is True
    assert photo.read_bytes() == b"original-committed"
    assert list((photo.parent / ".staging").glob("*.jpg"))


def test_upload_rejects_fake_image_and_oversize(client, data_root):
    resp = _upload(client, b"<html>not-an-image</html>", "fake.jpg")
    assert resp.status_code == 400
    client.application.config["MAX_CONTENT_LENGTH"] = 1024
    resp = _upload(client, b"x" * 2048, "large.jpg")
    assert resp.status_code == 413
    assert resp.get_json()["ok"] is False
    assert not list((data_root / "records" / "photos" / _today() / ".staging").glob("*"))


def test_submit_binds_photo_and_backs_up_old_file(client, data_root, monkeypatch):
    _mock_observe(monkeypatch)
    photo = data_root / "records" / "photos" / _today() / "舌面.jpg"
    photo.parent.mkdir(parents=True, exist_ok=True)
    photo.write_bytes(b"old-committed")
    legacy_png = photo.with_suffix(".png")
    legacy_png.write_bytes(b"old-png")
    assert _upload(client).status_code == 200
    for part in wizard_store.PARTS[1:]:
        client.post("/wizard/skip", json={"part": part["part"], "mode": "normal"})
    resp = client.post("/wizard/submit", json={"mode": "new"})
    assert resp.status_code == 200, resp.get_json()
    raw = _raw(data_root, _today())
    assert raw["photos"] == {"舌面": "舌面.jpg"}
    assert photo.read_bytes() != b"old-committed"
    backups = list((data_root / "records" / "_backup" / "photos" / _today()).rglob("舌面.jpg"))
    assert backups and backups[0].read_bytes() == b"old-committed"
    legacy_backups = list((data_root / "records" / "_backup" / "photos" / _today()).rglob("舌面.png"))
    assert legacy_backups and legacy_backups[0].read_bytes() == b"old-png"
    assert not legacy_png.exists()
    assert not list((photo.parent / ".staging").glob("*.jpg"))
    assert records_store.list_photos(str(photo.parent.parent), _today(), DailyRecord(raw)) == ["舌面.jpg"]


def test_photo_commit_restores_current_part_when_promotion_fails(data_root, monkeypatch):
    """暂存图转正失败时，当前部位已备份的旧图也必须回滚。"""
    import photo_store
    today = _today()
    day_dir = data_root / "records" / "photos" / today
    staging_dir = day_dir / ".staging"
    staging_dir.mkdir(parents=True)
    photo = day_dir / "舌面.jpg"
    legacy_png = day_dir / "舌面.png"
    staging = staging_dir / "舌面-staged.jpg"
    photo.write_bytes(b"old-committed")
    legacy_png.write_bytes(b"old-png")
    staging.write_bytes(b"new-staged")
    draft = {"parts": {"舌面": {"photo_staging": staging.name}}}
    original_replace = photo_store.os.replace

    def fail_promotion(source, destination):
        if source == str(staging) and destination == str(photo):
            raise OSError("synthetic promotion failure")
        return original_replace(source, destination)

    monkeypatch.setattr(photo_store.os, "replace", fail_promotion)
    with pytest.raises(OSError, match="synthetic promotion failure"):
        photo_store.commit_photos(
            draft, str(day_dir.parent), today, ["舌面"],
            str(data_root / "records" / "_backup"))

    assert photo.read_bytes() == b"old-committed"
    assert legacy_png.read_bytes() == b"old-png"
    assert staging.read_bytes() == b"new-staged"


def test_merge_does_not_replace_covered_photo(client, data_root, monkeypatch):
    today = _today()
    photo = data_root / "records" / "photos" / today / "舌面.jpg"
    photo.parent.mkdir(parents=True, exist_ok=True)
    photo.write_bytes(b"original-committed")
    raw = {"date": today, "confidence": "LOW",
           "observations": {"tongue": {"body": {"color": "淡红"}}},
           "photos": {"舌面": "舌面.jpg"},
           "danger_flags": {"triggered": [], "not_triggered": [], "unknown": []}}
    (data_root / "records" / "daily" / f"{today}_analysis.json").write_text(
        json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    _mock_observe(monkeypatch)
    assert _upload(client).status_code == 200
    for part in wizard_store.PARTS[1:]:
        client.post("/wizard/skip", json={"part": part["part"], "mode": "normal"})
    resp = client.post("/wizard/submit", json={"mode": "merge"})
    assert resp.status_code == 200, resp.get_json()
    assert photo.read_bytes() == b"original-committed"
    assert list((photo.parent / ".staging").glob("*.jpg"))


def test_restore_uses_current_pristine_preserves_report_and_undoes(client, data_root, monkeypatch):
    today = _manual_record(client, "红")
    monkeypatch.setattr(llm_client, "chat", lambda *args, **kwargs: json.dumps(
        {"structured": {}, "markdown": "# 合成报告"}, ensure_ascii=False))
    result = trends_store.generate_and_store_report(
        str(data_root / "records" / "daily"), str(data_root / "records" / "_backup"),
        today, lambda: ("m", "u", "k"))
    assert result["ok"] is True
    today = _manual_record(client, "红绛")
    resp = client.post(f"/record/{today}/field", json={
        "dim": "tongue", "indicator": "body_color", "value": "紫暗"})
    assert resp.status_code == 200
    assert client.post(f"/record/{today}/restore").status_code == 200
    raw = _raw(data_root, today)
    assert raw["observations"]["tongue"]["body"]["color"] == "红绛"
    assert raw["diagnosis"]["report"]["markdown"] == "# 合成报告"
    assert raw["manually_corrected"] is True
    assert client.post(f"/record/{today}/restore").status_code == 200
    raw = _raw(data_root, today)
    assert raw["observations"]["tongue"]["body"]["color"] == "紫暗"
    assert raw["diagnosis"]["report"]["markdown"] == "# 合成报告"


def test_backup_sequence_and_retention_preserve_pristine(data_root):
    source = data_root / "records" / "daily" / "2026-06-25_analysis.json"
    from test_record_integrity import _fixture_raw
    source_raw = _fixture_raw()
    source.write_text(json.dumps(source_raw), encoding="utf-8")
    backup = data_root / "records" / "_backup"
    pristine = records_store.create_pristine_snapshot(source_raw, str(backup))
    for _ in range(22):
        records_store.backup_file(str(source), str(backup), purpose="correction")
    index = json.loads((backup / ".index.json").read_text(encoding="utf-8"))
    sequences = [item["sequence"] for item in index]
    assert sequences == sorted(sequences) and len(set(sequences)) == len(sequences)
    assert (backup / pristine["id"]).exists()
    generic = [item for item in index if item["purpose"] != "pristine"]
    assert len(generic) <= 20


def test_corrupt_draft_backups_do_not_overwrite(data_root):
    today = _today()
    path = data_root / "records" / "daily" / f".wizard-{today}.json"
    for payload in (b"first-bad", b"second-bad"):
        path.write_bytes(payload)
        wizard_store.load_draft(str(path.parent), today)
    assert len(list(path.parent.glob(f".wizard-{today}.json.*.corrupt"))) == 2


def test_delete_day_removes_related_data_without_resurrection(client, data_root):
    today = _manual_record(client, "红")
    daily = data_root / "records" / "daily"
    backup = data_root / "records" / "_backup"
    records_store.backup_file(str(daily / f"{today}_analysis.json"), str(backup))
    photo = data_root / "records" / "photos" / today / ".staging" / "synthetic.jpg"
    photo.parent.mkdir(parents=True, exist_ok=True)
    photo.write_bytes(_jpeg())
    draft = daily / f".wizard-{today}.json"
    draft.write_text("{}", encoding="utf-8")
    resp = client.post(f"/record/{today}/delete", json={"confirm": "yes"})
    assert resp.status_code == 400
    assert (daily / f"{today}_analysis.json").exists()
    resp = client.post(f"/record/{today}/delete", json={"confirm": "DELETE"})
    assert resp.status_code == 200, resp.get_json()
    assert not (daily / f"{today}_analysis.json").exists()
    assert not (data_root / "records" / "photos" / today).exists()
    assert not draft.exists()
    assert not list(backup.glob(f"{today}_analysis.json.*.bak"))
    assert client.post(f"/record/{today}/restore").status_code == 400
    assert not (daily / f"{today}_analysis.json").exists()


def test_cli_vision_payload_is_also_sanitized(data_root, monkeypatch):
    import base64
    import vision_client
    from test_vision_client import _fake_response
    path = data_root / "synthetic.jpg"
    path.write_bytes(_jpeg())
    seen = {}

    def capture(req, timeout=None):
        seen["body"] = json.loads(req.data.decode())
        return _fake_response({"choices": [{"message": {"content": "ok"}}]})

    import safe_fetch
    monkeypatch.setattr(safe_fetch, "urlopen", capture)
    vision_client.call(str(path), "synthetic", model="synthetic",
                       url="https://example.invalid", key="synthetic")
    url = seen["body"]["messages"][0]["content"][0]["image_url"]["url"]
    assert url.startswith("data:image/jpeg;base64,")
    data = base64.b64decode(url.split(",", 1)[1])
    with Image.open(io.BytesIO(data)) as image:
        assert not image.getexif()
    assert b"SyntheticPhone" not in data


def test_pixel_limit_is_rejected_before_decode(monkeypatch):
    import photo_store
    monkeypatch.setattr(photo_store, "MAX_IMAGE_PIXELS", 15)
    with pytest.warns(Image.DecompressionBombWarning):
        with pytest.raises(ValueError, match="像素"):
            photo_store.clean_image_bytes(_jpeg())


def test_submit_conflict_rolls_back_committed_photo(client, data_root, monkeypatch):
    today = _manual_record(client, "红")
    photo = data_root / "records" / "photos" / today / "舌面.jpg"
    photo.parent.mkdir(parents=True, exist_ok=True)
    photo.write_bytes(b"original-committed")
    _mock_observe(monkeypatch)
    assert _upload(client).status_code == 200
    for part in wizard_store.PARTS[1:]:
        client.post("/wizard/skip", json={"part": part["part"], "mode": "normal"})
    import io_utils
    target = data_root / "records" / "daily" / f"{today}_analysis.json"
    original_validate = records_store.validate_candidate

    def competing_validate(raw, workdir, **kwargs):
        current = json.loads(target.read_text(encoding="utf-8"))
        current["external_marker"] = "other-window"
        io_utils.atomic_write_json(str(target), current)
        return original_validate(raw, workdir, **kwargs)

    monkeypatch.setattr(records_store, "validate_candidate", competing_validate)
    resp = client.post("/wizard/submit", json={"mode": "new"})
    assert resp.status_code == 409, resp.get_json()
    assert photo.read_bytes() == b"original-committed"
    assert len(list((photo.parent / ".staging").glob("*.jpg"))) == 1


def test_delete_form_has_post_and_explicit_confirmation(client, data_root):
    today = _manual_record(client, "红")
    html = client.get(f"/record/{today}").get_data(as_text=True)
    assert 'id="delete-form" method="post"' in html
    assert 'name="confirm" value="DELETE"' in html
    assert "确认永久删除" in html
