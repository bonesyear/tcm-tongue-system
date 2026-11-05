"""B11：同源、局域网鉴权、监听地址与前端注入边界。"""
from http.cookies import SimpleCookie
import os
import sys

import pytest

pytest.importorskip("flask")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "web"))

import app as web_app  # noqa: E402
import envfile  # noqa: E402

TOKEN = "synthetic-admin-token"
ORIGIN = {"Origin": "http://localhost"}
REMOTE = {"REMOTE_ADDR": "192.168.1.20"}


@pytest.fixture
def env_path(tmp_path):
    return str(tmp_path / ".env")


@pytest.fixture
def app(env_path, tmp_path, monkeypatch):
    for key in ("VISION_API_KEY", "VISION_DISABLED", "LLM_API_KEY", "LLM_DISABLED",
                "WEB_ADMIN_TOKEN", "WEB_HOST"):
        monkeypatch.delenv(key, raising=False)
    application = web_app.create_app(
        env_file=env_path, data_root=str(tmp_path / "data"))
    application.config["TESTING"] = True
    return application


@pytest.fixture
def client(app):
    return app.test_client()


def _ack(client, origin="http://localhost", headers=None):
    return client.post("/welcome", headers={"Origin": origin, **(headers or {})})


def _cookie(resp, name):
    cookies = SimpleCookie()
    for value in resp.headers.getlist("Set-Cookie"):
        cookies.load(value)
    assert name in cookies
    return cookies[name]


def test_welcome_requires_same_origin_and_sets_safe_cookie(client):
    assert client.post("/welcome").status_code == 403
    assert _ack(client, "https://evil.example").status_code == 403
    assert _ack(client, "http://localhost:8600").status_code == 403
    assert _ack(client, "https://localhost").status_code == 403

    resp = _ack(client)
    assert resp.status_code == 302
    cookie = _cookie(resp, "boot_ack")
    assert cookie["httponly"]
    assert cookie["samesite"] == "Strict"
    assert cookie["path"] == "/"
    assert not cookie["secure"]


@pytest.mark.parametrize("fetch_site", [None, "cross-site", "same-site"])
def test_opaque_origin_requires_same_origin_fetch_metadata(client, fetch_site):
    headers = {"Origin": "null"}
    if fetch_site:
        headers["Sec-Fetch-Site"] = fetch_site
    assert client.post("/welcome", headers=headers).status_code == 403


def test_opaque_origin_with_same_origin_fetch_metadata_is_accepted(client):
    resp = client.post("/welcome", headers={
        "Origin": "null", "Sec-Fetch-Site": "same-origin"})
    assert resp.status_code == 302
    assert _cookie(resp, "boot_ack")["httponly"]


def test_origin_must_match_host_scheme_and_port(client):
    assert _ack(client, headers={"Host": "localhost:8600"}).status_code == 403
    resp = _ack(client, "http://localhost:8600",
                headers={"Host": "localhost:8600"})
    assert resp.status_code == 302


def test_settings_requires_welcome_for_local_and_remote(client):
    for remote in ({}, REMOTE):
        resp = client.get("/settings", environ_overrides=remote)
        assert resp.status_code == 302
        assert resp.headers["Location"] == "/welcome"

    _ack(client)
    assert client.get("/settings").status_code == 200
    remote_settings = client.get("/settings", environ_overrides=REMOTE)
    assert remote_settings.status_code == 200
    assert "只读" in remote_settings.get_data(as_text=True)


def test_settings_write_requires_welcome_without_mutation(client, env_path):
    resp = client.post("/settings", data={"VISION_MODEL": "blocked"}, headers=ORIGIN)
    assert resp.status_code == 302
    assert resp.headers["Location"] == "/welcome"
    assert "VISION_MODEL" not in envfile.read_env(env_path)


@pytest.mark.parametrize("host", ["evil.example", "localhost:bad", "localhost@evil.example"])
def test_untrusted_host_rejected_before_route(client, host):
    resp = client.get("/settings", headers={"Host": host})
    assert resp.status_code == 403


def test_lan_ip_detection_failure_does_not_open_host_gate(app, client, monkeypatch):
    app.config["BOUND_HOST"] = "0.0.0.0"
    monkeypatch.setattr(web_app, "_lan_ip", lambda: "")
    resp = client.get("/settings", headers={"Host": "localhost:bad"})
    assert resp.status_code == 403


def test_cross_site_write_is_rejected_without_mutation(client, env_path):
    envfile.write_env(env_path, {"VISION_MODEL": "before"})
    _ack(client)
    resp = client.post("/settings", data={"VISION_MODEL": "after"},
                       headers={"Origin": "https://evil.example"})
    assert resp.status_code == 403
    resp = client.post("/settings", data={"VISION_MODEL": "after"},
                       headers={"Sec-Fetch-Site": "cross-site"})
    assert resp.status_code == 403
    assert envfile.read_env(env_path)["VISION_MODEL"] == "before"

    resp = client.post("/settings", data={"VISION_MODEL": "from-referer"},
                       headers={"Referer": "http://localhost/settings"})
    assert resp.status_code == 302
    assert envfile.read_env(env_path)["VISION_MODEL"] == "from-referer"


def test_lan_login_uses_post_session_not_url(client, env_path):
    envfile.write_env(env_path, {"WEB_ADMIN_TOKEN": TOKEN, "VISION_API_KEY": "sk-test"})
    resp = client.get("/settings?token=" + TOKEN, environ_overrides=REMOTE)
    assert resp.status_code == 302 and resp.headers["Location"] == "/welcome"
    assert TOKEN not in resp.get_data(as_text=True)
    assert "admin_session" not in resp.headers.get("Set-Cookie", "")
    assert client.get("/", environ_overrides=REMOTE).status_code == 302

    _ack(client)
    resp = client.get("/settings?token=" + TOKEN, environ_overrides=REMOTE)
    assert "只读" in resp.get_data(as_text=True)
    assert TOKEN not in resp.get_data(as_text=True)
    assert client.get("/", environ_overrides=REMOTE).status_code == 302

    resp = client.post("/settings/login", data={"admin_token": TOKEN},
                       headers=ORIGIN, environ_overrides=REMOTE)
    assert resp.status_code == 302
    assert resp.headers["Location"] == "/"
    cookie = _cookie(resp, "admin_session")
    assert cookie["httponly"] and cookie["samesite"] == "Strict"
    assert cookie["path"] == "/" and not cookie["secure"]

    assert client.get("/", environ_overrides=REMOTE).status_code == 200
    resp = client.post("/settings", data={"VISION_MODEL": "after-login"},
                       headers=ORIGIN, environ_overrides=REMOTE)
    assert resp.status_code == 302
    assert resp.headers["Location"] == "/settings?saved=1"
    assert TOKEN not in resp.headers["Location"]
    assert envfile.read_env(env_path)["VISION_MODEL"] == "after-login"


def test_lan_wrong_password_and_forged_session_rejected(client, env_path):
    envfile.write_env(env_path, {"WEB_ADMIN_TOKEN": TOKEN})
    resp = client.post("/settings/login", data={"admin_token": "wrong"},
                       headers=ORIGIN, environ_overrides=REMOTE)
    assert resp.status_code == 403
    assert "管理口令不正确" in resp.get_data(as_text=True)
    assert "admin_session" not in resp.headers.get("Set-Cookie", "")

    client.set_cookie("admin_session", "forged")
    resp = client.get("/record/2026-06-25", environ_overrides=REMOTE)
    assert resp.status_code == 302 and resp.headers["Location"] == "/welcome"


def test_lan_reads_and_photo_bytes_require_login(client, env_path, tmp_path):
    _ack(client)
    assert client.post("/demo").status_code == 302
    photo = tmp_path / "data" / "records" / "photos" / "2026-06-25" / "舌面.jpg"
    photo.parent.mkdir(parents=True)
    photo.write_bytes(b"synthetic-photo-bytes")
    envfile.write_env(env_path, {"WEB_ADMIN_TOKEN": TOKEN})

    for path in ("/", "/record/2026-06-25", "/trends", "/photos/2026-06-25/舌面.jpg"):
        resp = client.get(path, environ_overrides=REMOTE)
        assert resp.status_code == 302, path
        assert "/settings" in resp.headers["Location"], path
        assert b"synthetic-photo-bytes" not in resp.data

    client.post("/settings/login", data={"admin_token": TOKEN},
                headers=ORIGIN, environ_overrides=REMOTE)
    _ack(client)
    for path in ("/", "/record/2026-06-25", "/trends", "/photos/2026-06-25/舌面.jpg"):
        assert client.get(path, environ_overrides=REMOTE).status_code == 200, path
    resp = client.get("/photos/2026-06-25/舌面.jpg", environ_overrides=REMOTE)
    assert resp.data == b"synthetic-photo-bytes"


@pytest.mark.parametrize("path", [
    "/record/2026-06-25/field", "/wizard/field", "/wizard/manual",
    "/wizard/inquiry", "/wizard/skip", "/wizard/submit",
    "/settings/models", "/settings/test",
])
def test_non_object_json_returns_400(client, path):
    _ack(client)
    resp = client.post(path, json=[1, 2, 3])
    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False
    assert "对象" in resp.get_json()["error"]


@pytest.mark.parametrize("body", ["null", "true", '"text"', "{broken"])
def test_null_non_object_and_malformed_json_return_400(client, body):
    _ack(client)
    resp = client.post("/settings/models", data=body,
                       content_type="application/json")
    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False
    assert "对象" in resp.get_json()["error"]


def test_forwarded_header_does_not_elevate_remote_client(client, env_path):
    envfile.write_env(env_path, {"WEB_ADMIN_TOKEN": TOKEN})
    _ack(client)
    html = client.get("/settings", environ_overrides={
        "REMOTE_ADDR": "::ffff:127.0.0.1"}).get_data(as_text=True)
    assert "只读" not in html
    for remote in ("127.0.0.1", "::ffff:127.0.0.1", "192.168.1.20"):
        html = client.get("/settings", headers={"X-Forwarded-For": "127.0.0.1"},
                          environ_overrides={"REMOTE_ADDR": remote}).get_data(as_text=True)
        assert "只读" in html


def test_referrer_policy_preserves_same_origin_native_forms(client):
    """局域网 Chrome 原生表单需保留同源 Origin；跨站仍不得发送 Referer。"""
    assert client.get("/welcome").headers["Referrer-Policy"] == "same-origin"


def test_security_headers_on_public_and_private_pages(client):
    _ack(client)
    for path in ("/license", "/settings"):
        resp = client.get(path)
        assert resp.headers["X-Frame-Options"] == "DENY"
        assert resp.headers["Content-Security-Policy"] == "frame-ancestors 'none'"
        assert resp.headers["X-Content-Type-Options"] == "nosniff"
        assert resp.headers["Referrer-Policy"] == "same-origin"
        assert "Sec-Fetch-Site" in resp.headers["Vary"]


@pytest.mark.parametrize("host", ["0.0.0.0", "example.com", "127.0.0.1.evil.example"])
def test_invalid_or_unprotected_listen_host_returns_400(client, env_path, host):
    _ack(client)
    resp = client.post("/settings", data={"WEB_HOST": host})
    assert resp.status_code == 400
    assert "WEB_HOST" in resp.get_data(as_text=True) or "非回环" in resp.get_data(as_text=True)
    assert "WEB_HOST" not in envfile.read_env(env_path)


def test_listen_host_and_password_can_be_saved_together(client, env_path):
    _ack(client)
    resp = client.post("/settings", data={"WEB_HOST": "0.0.0.0",
                                          "WEB_ADMIN_TOKEN": TOKEN})
    assert resp.status_code == 302
    assert envfile.read_env(env_path)["WEB_HOST"] == "0.0.0.0"
    assert envfile.read_env(env_path)["WEB_ADMIN_TOKEN"] == TOKEN


def test_settings_uses_actual_bound_host_and_port(app, client, monkeypatch):
    app.config.update(BOUND_HOST="0.0.0.0", BOUND_PORT=8610)
    monkeypatch.setattr(web_app, "_lan_ip", lambda: "192.168.1.8")
    _ack(client)
    html = client.get("/settings").get_data(as_text=True)
    assert "0.0.0.0:8610" in html
    assert "127.0.0.1:8610" in html
    assert "http://192.168.1.8:8610" in html


class _FakeApp:
    def __init__(self):
        self.config = {}
        self.calls = []

    def run(self, **kwargs):
        self.calls.append(kwargs)


def test_main_lan_without_password_refuses_to_start(monkeypatch):
    fake = _FakeApp()
    monkeypatch.setattr(web_app, "create_app", lambda: fake)
    monkeypatch.setattr(envfile, "effective", lambda key, path, default="": default)
    monkeypatch.setattr(sys, "argv", ["app.py", "--lan"])
    with pytest.raises(SystemExit) as exc:
        web_app.main()
    assert exc.value.code == 2
    assert fake.calls == []


def test_main_records_bound_address_and_formats_ipv6(monkeypatch, capsys):
    fake = _FakeApp()
    values = {"WEB_HOST": "::1", "WEB_ADMIN_TOKEN": TOKEN}
    monkeypatch.setattr(web_app, "create_app", lambda: fake)
    monkeypatch.setattr(envfile, "effective",
                        lambda key, path, default="": values.get(key, default))
    monkeypatch.setattr(sys, "argv", ["app.py", "--port", "8610"])
    monkeypatch.setattr(web_app, "serve_http",
                        lambda app, **kwargs: fake.calls.append(kwargs))
    web_app.main()
    assert fake.config == {"BOUND_HOST": "::1", "BOUND_PORT": 8610}
    assert fake.calls == [{"host": "::1", "port": 8610}]
    assert "http://[::1]:8610" in capsys.readouterr().err


def test_templates_do_not_interpolate_secrets_or_response_html():
    with open(os.path.join(_ROOT, "web", "templates", "settings.html"),
              encoding="utf-8") as f:
        settings = f.read()
    with open(os.path.join(_ROOT, "web", "templates", "wizard.html"),
              encoding="utf-8") as f:
        wizard = f.read()
    assert "token_arg" not in settings
    assert "textContent = detail" in settings
    assert "+ data.detail" not in settings
    assert 'document.getElementById("danger-list").innerHTML' not in wizard
    assert 'md.innerHTML = "<strong>⚠' not in wizard
    assert 'box.innerHTML = "<strong>⚠' not in wizard
    assert "strong.textContent = f.name" in wizard
    assert 'for="admin-login-token"' in settings
    assert 'autocomplete="current-password"' in settings
