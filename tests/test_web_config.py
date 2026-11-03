"""B12：配置文件与 Web 配置边界，全部使用临时配置。"""
import os

import pytest

pytest.importorskip("flask")

import envfile
from app import create_app


@pytest.fixture
def env_path(tmp_path):
    return str(tmp_path / ".env")


@pytest.fixture
def client(env_path, tmp_path, monkeypatch):
    for key in ("VISION_API_KEY", "VISION_MODEL", "VISION_BASE_URL",
                "VISION_DISABLED", "LLM_DISABLED", "WEB_ADMIN_TOKEN", "WEB_HOST"):
        monkeypatch.delenv(key, raising=False)
    app = create_app(env_file=env_path, data_root=str(tmp_path / "data"))
    app.config["TESTING"] = True
    client = app.test_client()
    client.post("/welcome", headers={"Origin": "http://localhost"})
    return client


def test_env_bom_quotes_hash_and_inline_comments(tmp_path):
    path = tmp_path / ".env"
    path.write_text(
        '\ufeffVISION_API_KEY="sk-#值 \\"q\\"" # 注释\n'
        "WEB_ADMIN_TOKEN='a#b'\n"
        "VISION_MODEL=plain#tail\n"
        "LLM_MODEL=old # 注释\n", encoding="utf-8")
    values = envfile.read_env(str(path))
    assert values["VISION_API_KEY"] == 'sk-#值 "q"'
    assert values["WEB_ADMIN_TOKEN"] == "a#b"
    assert values["VISION_MODEL"] == "plain#tail"
    assert values["LLM_MODEL"] == "old"


@pytest.mark.parametrize("value", [
    "abc#def", " leading", "trailing ", "a\\b", 'quote"value',
    "has'single", "a # b", "空格 保留",
])
def test_env_write_read_roundtrip(tmp_path, value):
    path = tmp_path / ".env"
    path.write_text("# 保留注释\n", encoding="utf-8")
    envfile.write_env(str(path), {"VISION_API_KEY": value})
    assert envfile.read_env(str(path))["VISION_API_KEY"] == value
    assert path.read_text(encoding="utf-8").startswith("# 保留注释\n")


@pytest.mark.parametrize("key", ["bad-key", "1BAD", "lower", "A B", ""])
def test_env_rejects_invalid_keys(tmp_path, key):
    with pytest.raises(ValueError):
        envfile.write_env(str(tmp_path / ".env"), {key: "value"})


@pytest.mark.parametrize("value", [
    "a\rb", "a\nb", "a\0b", "a\vb", "a\fb", "a\x1cb", "a\x1db",
    "a\x1eb", "a\x85b", "a\u2028b", "a\u2029b",
])
def test_env_rejects_every_line_separator_without_overwrite(tmp_path, value):
    path = tmp_path / ".env"
    original = b"SAFE=before\n"
    path.write_bytes(original)
    with pytest.raises(ValueError):
        envfile.write_env(str(path), {"VISION_MODEL": value})
    assert path.read_bytes() == original


def test_env_write_non_utf8_uses_recoverable_error(tmp_path):
    path = tmp_path / ".env"
    path.write_bytes("# 中文\n".encode("gbk"))
    with pytest.raises(envfile.EnvDecodeError) as error:
        envfile.write_env(str(path), {"VISION_MODEL": "new"})
    assert "UTF-8" in str(error.value)


def test_non_utf8_pages_are_recoverable(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_bytes("# 中文注释\n".encode("gbk"))
    app = create_app(env_file=str(env_path), data_root=str(tmp_path / "data"))
    app.config["TESTING"] = True
    client = app.test_client()
    for path in ("/", "/settings", "/wizard"):
        resp = client.get(path)
        assert resp.status_code == 200, path
        assert "UTF-8" in resp.get_data(as_text=True)
    resp = client.post("/welcome", headers={"Origin": "http://localhost"})
    assert resp.status_code == 302
    assert "env_error" in resp.headers["Location"]
    assert client.get("/settings").status_code == 200


def test_settings_rejects_env_line_injection(client, env_path):
    resp = client.post("/settings", data={
        "VISION_MODEL": "model\nWEB_ADMIN_TOKEN=injected\rWEB_HOST=0.0.0.0"})
    assert resp.status_code == 400
    assert envfile.read_env(env_path) == {}


def test_empty_environment_value_does_not_lock_toggle(tmp_path, monkeypatch):
    env_path = str(tmp_path / ".env")
    envfile.write_env(env_path, {"VISION_DISABLED": "1"})
    monkeypatch.setenv("VISION_DISABLED", "")
    app = create_app(env_file=env_path, data_root=str(tmp_path / "data"))
    app.config["TESTING"] = True
    client = app.test_client()
    client.post("/welcome", headers={"Origin": "http://localhost"})
    resp = client.post("/settings", data={"FORM_VISION": "1", "VISION_ENABLED": "1"})
    assert resp.status_code == 302
    assert envfile.read_env(env_path)["VISION_DISABLED"] == ""


def test_locked_setting_is_not_written_and_is_reported(tmp_path, monkeypatch):
    env_path = str(tmp_path / ".env")
    monkeypatch.setenv("VISION_BASE_URL", "https://env.example/v1/chat/completions")
    app = create_app(env_file=env_path, data_root=str(tmp_path / "data"))
    app.config["TESTING"] = True
    client = app.test_client()
    client.post("/welcome", headers={"Origin": "http://localhost"})
    resp = client.post("/settings", data={
        "VISION_BASE_URL": "https://attacker.invalid/v1/chat/completions",
        "VISION_MODEL": "allowed-model"})
    assert resp.status_code == 302
    assert "locked=VISION_BASE_URL" in resp.headers["Location"]
    values = envfile.read_env(env_path)
    assert values["VISION_MODEL"] == "allowed-model"
    assert "VISION_BASE_URL" not in values


def test_settings_rejects_non_http_endpoint(client, env_path):
    resp = client.post("/settings", data={
        "VISION_BASE_URL": "file:///tmp/example.json"})
    assert resp.status_code == 400
    assert envfile.read_env(env_path) == {}


def test_models_new_origin_requires_explicit_new_key(client, env_path, monkeypatch):
    import llm_client
    import safe_fetch
    envfile.write_env(env_path, {
        "VISION_API_KEY": "saved-key",
        "VISION_BASE_URL": "https://saved.example/v1/chat/completions"})
    calls = []
    monkeypatch.setattr(safe_fetch, "urlopen", lambda *args: calls.append(args))
    resp = client.post("/settings/models", json={
        "target": "vision", "base_url": "https://other.example/v1"})
    assert resp.status_code == 400
    assert "不同源" in resp.get_json()["error"]
    assert calls == []

    seen = {}
    monkeypatch.setattr(llm_client, "list_models",
                        lambda url, key: seen.setdefault("request", (url, key)) or ["m"])
    resp = client.post("/settings/models", json={
        "target": "vision", "base_url": "https://other.example/v1",
        "api_key": "new-explicit-key"})
    assert resp.status_code == 200
    assert seen["request"] == ("https://other.example/v1", "new-explicit-key")


def test_models_same_origin_can_reuse_saved_key(client, env_path, monkeypatch):
    import llm_client
    envfile.write_env(env_path, {
        "VISION_API_KEY": "saved-key",
        "VISION_BASE_URL": "https://api.example/v1/chat/completions"})
    seen = {}
    monkeypatch.setattr(llm_client, "list_models",
                        lambda url, key: seen.setdefault("request", (url, key)) or ["m"])
    resp = client.post("/settings/models", json={
        "target": "vision", "base_url": "https://api.example:443/v1"})
    assert resp.status_code == 200
    assert seen["request"] == ("https://api.example:443/v1", "saved-key")


def test_models_locked_base_url_ignores_override(tmp_path, monkeypatch):
    import llm_client
    env_path = str(tmp_path / ".env")
    envfile.write_env(env_path, {"VISION_API_KEY": "saved-key"})
    monkeypatch.setenv("VISION_BASE_URL", "https://locked.example/v1/chat/completions")
    app = create_app(env_file=env_path, data_root=str(tmp_path / "data"))
    app.config["TESTING"] = True
    client = app.test_client()
    client.post("/welcome", headers={"Origin": "http://localhost"})
    seen = {}
    monkeypatch.setattr(llm_client, "list_models",
                        lambda url, key: seen.setdefault("request", (url, key)) or ["m"])
    resp = client.post("/settings/models", json={
        "target": "vision", "base_url": "https://attacker.invalid/v1"})
    assert resp.status_code == 200
    assert seen["request"] == ("https://locked.example/v1/chat/completions", "saved-key")


def test_cleared_vision_key_never_uses_legacy_sources(client, monkeypatch):
    import safe_fetch
    monkeypatch.setenv("DASHSCOPE_API_KEY", "legacy-synthetic-key")
    calls = []
    monkeypatch.setattr(safe_fetch, "urlopen", lambda *args: calls.append(args))
    resp = client.post("/settings/test", json={"target": "vision"})
    assert resp.status_code == 400
    assert "未配置" in resp.get_json()["detail"]
    assert calls == []


@pytest.mark.parametrize("key,value", [
    ("LLM_MAX_TOKENS", "abc"), ("LLM_TIMEOUT", "0"),
    ("VISION_TEMPERATURE", "nan"),
])
def test_invalid_numeric_config_returns_400(client, env_path, key, value):
    resp = client.post("/settings", data={key: value})
    assert resp.status_code == 400
    assert key not in envfile.read_env(env_path)


def test_new_numeric_fields_are_visible(client):
    html = client.get("/settings").get_data(as_text=True)
    for key in ("VISION_MAX_TOKENS", "LLM_MAX_TOKENS", "LLM_TIMEOUT"):
        assert f'name="{key}"' in html
    assert 'placeholder="16000"' in html
    assert html.count('min="1"') >= 3


def test_concurrent_requests_keep_provider_snapshot(tmp_path, monkeypatch):
    import threading
    import vision_client
    configs = {
        "x": {"VISION_API_KEY": "kx", "VISION_MODEL": "mx",
              "VISION_BASE_URL": "https://x.invalid/v1/chat/completions",
              "VISION_MAX_TOKENS": "8000", "VISION_TEMPERATURE": "0.6"},
        "y": {"VISION_API_KEY": "ky", "VISION_MODEL": "my",
              "VISION_BASE_URL": "https://y.invalid/v1/chat/completions",
              "VISION_MAX_TOKENS": "9000", "VISION_TEMPERATURE": "0.7"},
    }
    state = {"config": configs["x"]}
    monkeypatch.setattr(envfile, "read_env", lambda path: dict(state["config"]))
    app = create_app(env_file=str(tmp_path / ".env"),
                     data_root=str(tmp_path / "data"))
    app.config["TESTING"] = True
    ready = threading.Barrier(2)
    init_lock = threading.Lock()
    seen = []
    errors = []

    def fake_call(image, prompt, **options):
        seen.append(options)
        return 0, "ok"

    monkeypatch.setattr(vision_client, "call", fake_call)

    def worker(name):
        try:
            with init_lock:
                state["config"] = configs[name]
                client = app.test_client()
                assert client.post("/welcome", headers={
                    "Origin": "http://localhost"}).status_code == 302
            ready.wait(timeout=3)
            state["config"] = configs["y" if name == "x" else "x"]
            resp = client.post("/settings/test", json={"target": "vision"})
            assert resp.status_code == 200, resp.get_data(as_text=True)
            assert resp.get_json()["ok"] is True
        except Exception as error:
            errors.append(error)

    threads = [threading.Thread(target=worker, args=(name,)) for name in ("x", "y")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
    assert errors == []
    assert len(seen) == 2
    for options in seen:
        expected = configs["x" if options["key"] == "kx" else "y"]
        assert options["model"] == expected["VISION_MODEL"]
        assert options["url"] == expected["VISION_BASE_URL"]
        assert options["max_tokens"] == int(expected["VISION_MAX_TOKENS"])
        assert options["temperature"] == float(expected["VISION_TEMPERATURE"])


def test_top_level_envfile_writes_with_repo_on_pythonpath(tmp_path):
    import subprocess
    import sys
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    script = (
        "import envfile; "
        f"path = {str(tmp_path / '.env')!r}; "
        "envfile.write_env(path, {'VISION_MODEL': 'package-mode'}); "
        "assert envfile.read_env(path)['VISION_MODEL'] == 'package-mode'"
    )
    result = subprocess.run([sys.executable, "-c", script], cwd=root,
                            env=dict(os.environ, PYTHONPATH=os.path.join(root, "web")),
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
