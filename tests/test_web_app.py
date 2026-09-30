"""web 层切片 1 测试：.env 读写 + Flask 设置页行为。

Flask 是 web/ 独立依赖（web/requirements.txt），未装时整模块跳过，
不影响核心库测试基线。
"""
import os
import sys

import pytest

pytest.importorskip("flask")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "web"))

import envfile  # noqa: E402
from app import create_app  # noqa: E402


@pytest.fixture
def env_path(tmp_path):
    return str(tmp_path / ".env")


@pytest.fixture
def client(env_path, monkeypatch):
    for k in ("VISION_API_KEY", "VISION_MODEL", "VISION_BASE_URL",
              "LLM_API_KEY", "WEB_ADMIN_TOKEN", "WEB_HOST"):
        monkeypatch.delenv(k, raising=False)
    app = create_app(env_file=env_path)
    app.config["TESTING"] = True
    return app.test_client()


# ---------------- envfile ----------------

def test_envfile_roundtrip_preserves_comments(env_path):
    with open(env_path, "w", encoding="utf-8") as f:
        f.write("# 注释\nVISION_MODEL=old-model\n\nOTHER=keep\n")
    envfile.write_env(env_path, {"VISION_MODEL": "new-model", "LLM_MODEL": "m1"})
    text = open(env_path, encoding="utf-8").read()
    assert "# 注释" in text
    assert "VISION_MODEL=new-model" in text
    assert "old-model" not in text
    assert "OTHER=keep" in text
    assert "LLM_MODEL=m1" in text
    assert envfile.read_env(env_path)["VISION_MODEL"] == "new-model"


def test_envfile_write_none_means_untouched(env_path):
    envfile.write_env(env_path, {"A": "1"})
    envfile.write_env(env_path, {"A": None, "B": "2"})
    env = envfile.read_env(env_path)
    assert env == {"A": "1", "B": "2"}


def test_envfile_non_utf8_raises(env_path):
    with open(env_path, "wb") as f:
        f.write("# 中文\nKEY=v".encode("gbk"))
    with pytest.raises(envfile.EnvDecodeError):
        envfile.read_env(env_path)


def test_envfile_missing_returns_empty(env_path):
    assert envfile.read_env(env_path) == {}


# ---------------- 设置页行为 ----------------

def test_first_run_redirects_to_settings(client):
    resp = client.get("/")
    assert resp.status_code == 302
    assert "/settings" in resp.headers["Location"]


def test_index_ok_when_configured(client, env_path):
    envfile.write_env(env_path, {"VISION_API_KEY": "sk-x"})
    resp = client.get("/")
    assert resp.status_code == 200


def test_settings_save_writes_env(client, env_path):
    resp = client.post("/settings", data={
        "VISION_API_KEY": "sk-secret",
        "VISION_MODEL": "qwen3.8-max",
        "VISION_BASE_URL": "https://example.com/v1/chat/completions",
    })
    assert resp.status_code == 302
    env = envfile.read_env(env_path)
    assert env["VISION_API_KEY"] == "sk-secret"
    assert env["VISION_MODEL"] == "qwen3.8-max"


def test_settings_secret_blank_keeps_existing(client, env_path):
    envfile.write_env(env_path, {"VISION_API_KEY": "sk-old"})
    client.post("/settings", data={"VISION_API_KEY": "", "VISION_MODEL": "m"})
    assert envfile.read_env(env_path)["VISION_API_KEY"] == "sk-old"


def test_settings_partial_form_does_not_clear_others(client, env_path):
    """只提交 LLM 表单时，VISION_* 不得被清空（分表单语义）。"""
    envfile.write_env(env_path, {"VISION_MODEL": "vm", "VISION_API_KEY": "sk-v"})
    client.post("/settings", data={"LLM_MODEL": "deepseek-v3"})
    env = envfile.read_env(env_path)
    assert env["VISION_MODEL"] == "vm"
    assert env["VISION_API_KEY"] == "sk-v"
    assert env["LLM_MODEL"] == "deepseek-v3"


def test_lan_readonly_without_token(client):
    resp = client.get("/settings", environ_overrides={"REMOTE_ADDR": "192.168.3.20"})
    assert resp.status_code == 200
    assert "只读" in resp.get_data(as_text=True)
    resp = client.post("/settings", data={"VISION_MODEL": "m"},
                       environ_overrides={"REMOTE_ADDR": "192.168.3.20"})
    assert resp.status_code == 403


def test_lan_with_token_can_write(client, env_path):
    envfile.write_env(env_path, {"WEB_ADMIN_TOKEN": "t123"})
    resp = client.post("/settings",
                       data={"VISION_MODEL": "m", "admin_token": "t123"},
                       environ_overrides={"REMOTE_ADDR": "192.168.3.20"})
    assert resp.status_code == 302
    assert envfile.read_env(env_path)["VISION_MODEL"] == "m"


def test_lan_wrong_token_rejected(client, env_path):
    envfile.write_env(env_path, {"WEB_ADMIN_TOKEN": "t123"})
    resp = client.post("/settings",
                       data={"VISION_MODEL": "m", "admin_token": "wrong"},
                       environ_overrides={"REMOTE_ADDR": "192.168.3.20"})
    assert resp.status_code == 403


def test_test_endpoint_rejects_unknown_target(client):
    resp = client.post("/settings/test", json={"target": "bogus"})
    assert resp.status_code == 400
