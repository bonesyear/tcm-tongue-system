"""B19：生产部署、报告去重与许可边界；全部为合成数据和 mock。"""
import ast
import json
import threading

import pytest

import envfile
import trends_store
from app import create_app


@pytest.fixture
def client(tmp_path):
    app = create_app(env_file=str(tmp_path / ".env"), data_root=str(tmp_path / "data"))
    app.config["TESTING"] = True
    client = app.test_client()
    client.post("/welcome", headers={"Origin": "http://localhost"})
    return client


def _contract():
    return json.dumps({"structured": {}, "markdown": "# 合成报告"}, ensure_ascii=False)


def _daily_record(tmp_path):
    daily = tmp_path / "records" / "daily"
    daily.mkdir(parents=True)
    raw = {"date": "2026-11-03", "observations": {
        "tongue": {"body": {"color": "淡红"}}}, "inquiry": {}}
    (daily / "2026-11-03_analysis.json").write_text(
        json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    return daily


def test_license_is_complete_and_welcome_separates_kb(client):
    text = client.get("/license").get_data(as_text=True)
    assert "END OF TERMS AND CONDITIONS" in text
    assert "17. Interpretation of Sections 15 and 16" in text
    welcome = client.get("/welcome").get_data(as_text=True)
    assert "代码及项目自有模板" in welcome
    assert "公开包不附带原知识库" in welcome
    assert "默认不读取外部旧库" in welcome
    assert "程序管理副本会自动启用" in welcome


def test_welcome_covers_legal_boundaries_without_absolute_disclaimer(client):
    welcome = client.get("/welcome").get_data(as_text=True)
    assert welcome.count('class="ack"') == 3
    for text in (
        "不作为医疗器械、互联网医院或诊疗服务提供",
        "不是处方",
        "不等于匿名化",
        "不替代被拍摄人的单独同意",
        "不满十四周岁未成年人",
        "向第三方或境外提供信息",
        "对外发布 AI 生成内容",
        "不排除或限制依法不得排除或限制的责任",
        "每次分析后",
    ):
        assert text in welcome
    assert "不对因使用本系统" not in welcome
    assert "公开历史仍按既有决定" not in welcome


def test_report_and_guide_keep_ai_and_non_prescription_labels(client):
    client.post("/demo")
    detail = client.get("/record/2026-06-25").get_data(as_text=True)
    assert "AI 生成 · 非诊断" in detail
    from pathlib import Path
    for name in ("docs/user-guide.md", "docs/user-guide.html"):
        text = Path(name).read_text(encoding="utf-8")
        assert "剂量候选文本（非处方）" in text
        assert "不得据此自行配药" in text
        assert "不替代被拍摄人的单独同意" in text


def test_production_server_has_bounded_pool_and_timeouts(monkeypatch):
    import waitress
    calls = []
    monkeypatch.setattr(waitress, "serve", lambda *args, **kwargs: calls.append(kwargs))
    from photo_store import MAX_PHOTO_BYTES
    from server import serve_http
    serve_http(object(), "127.0.0.1", 8600)
    assert calls == [{
        "host": "127.0.0.1", "port": 8600, "threads": 8,
        "connection_limit": 64, "channel_timeout": 300,
        "max_request_body_size": MAX_PHOTO_BYTES + 1024 * 1024,
        "backlog": 32,
    }]


def test_report_generation_is_deduplicated_per_date(tmp_path, monkeypatch):
    import llm_client
    daily = _daily_record(tmp_path)
    started = threading.Event()
    release = threading.Event()
    calls = []

    def fake_chat(*args, **kwargs):
        calls.append(args)
        started.set()
        assert release.wait(timeout=10)
        return _contract()

    monkeypatch.setattr(llm_client, "chat", fake_chat)
    args = (str(daily), str(tmp_path / "records" / "_backup"), "2026-11-03",
            lambda: ("m", "u", "k"))
    first = threading.Thread(target=lambda: trends_store.generate_and_store_report(*args))
    first.start()
    assert started.wait(timeout=5)
    second = trends_store.generate_and_store_report(*args)
    assert second["ok"] is False and second["in_progress"] is True
    assert len(calls) == 1
    release.set()
    first.join(timeout=10)
    assert not first.is_alive()
    assert len(calls) == 1


def test_report_lock_releases_after_failure(tmp_path, monkeypatch):
    import llm_client
    daily = _daily_record(tmp_path)
    args = (str(daily), str(tmp_path / "records" / "_backup"), "2026-11-03",
            lambda: ("m", "u", "k"))
    monkeypatch.setattr(llm_client, "chat", lambda *args, **kwargs: (_ for _ in ()).throw(
        RuntimeError("合成失败")))
    assert trends_store.generate_and_store_report(*args)["ok"] is False
    monkeypatch.setattr(llm_client, "chat", lambda *args, **kwargs: _contract())
    assert trends_store.generate_and_store_report(*args)["ok"] is True


def test_report_in_progress_maps_to_409(client, monkeypatch):
    client.post("/demo")
    monkeypatch.setattr(trends_store, "generate_and_store_report",
                        lambda *args, **kwargs: {"ok": False, "in_progress": True,
                                                 "error": "生成中"})
    response = client.post("/record/2026-06-25/report")
    assert response.status_code == 409


def test_example_images_are_schematic_not_medical_evidence():
    from pathlib import Path
    for name in ("docs/user-guide.md", "docs/user-guide.html"):
        text = Path(name).read_text(encoding="utf-8")
        assert "例图仅用于取景示意" in text
        assert "医学判读依据" in text


def test_python_files_use_single_top_level_web_import_style():
    from pathlib import Path
    root = Path(__file__).parent.parent
    for directory in (root / "web", root / "scripts", root / "tests"):
        for path in directory.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module \
                        and (node.module == "web" or node.module.startswith("web.")):
                    raise AssertionError(f"包式导入会造成双模块实例: {path}:{node.lineno}")
                if isinstance(node, ast.Import) and any(
                        alias.name == "web" or alias.name.startswith("web.")
                        for alias in node.names):
                    raise AssertionError(f"包式导入会造成双模块实例: {path}:{node.lineno}")
