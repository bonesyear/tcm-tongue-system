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
    c = app.test_client()
    c.post("/welcome")  # 完成启动声明确认，免打扰其余用例
    return c


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


# ---------------- 启动须知页 + 缺 key 警告 ----------------

def test_first_visit_redirects_to_welcome(env_path, monkeypatch):
    for k in ("VISION_API_KEY",):
        monkeypatch.delenv(k, raising=False)
    app = create_app(env_file=env_path)
    app.config["TESTING"] = True
    c = app.test_client()
    resp = c.get("/")
    assert resp.status_code == 302
    assert "/welcome" in resp.headers["Location"]
    # 确认后放行，且未配 key 时落到设置页
    resp = c.post("/welcome")
    assert resp.status_code == 302
    assert "/settings" in resp.headers["Location"]
    assert c.get("/").status_code == 200


def test_welcome_ack_lands_home_when_configured(client, env_path):
    envfile.write_env(env_path, {"VISION_API_KEY": "sk-x"})
    resp = client.post("/welcome")
    assert resp.headers["Location"] == "/"
    # 已确认用户可随时回看须知页
    assert client.get("/welcome").status_code == 200


def test_index_warns_when_key_missing(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "VISION_API_KEY" in resp.get_data(as_text=True)


def test_index_ok_when_configured(client, env_path):
    envfile.write_env(env_path, {"VISION_API_KEY": "sk-x"})
    resp = client.get("/")
    assert resp.status_code == 200
    assert "VISION_API_KEY</code>" not in resp.get_data(as_text=True)


def test_license_served_locally_without_ack(env_path, monkeypatch):
    monkeypatch.delenv("VISION_API_KEY", raising=False)
    app = create_app(env_file=env_path)
    app.config["TESTING"] = True
    c = app.test_client()  # 未确认须知也可直接读 LICENSE
    resp = c.get("/license")
    assert resp.status_code == 200
    assert "GNU GENERAL PUBLIC LICENSE" in resp.get_data(as_text=True)


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


def test_env_var_sourced_fields_locked(env_path, monkeypatch):
    """环境变量来源的字段：页面锁定 + 醒目提示（防止「保存了又变回」的困惑）。"""
    monkeypatch.setenv("VISION_BASE_URL", "https://env-var.example.com/v1/chat/completions")
    app = create_app(env_file=env_path)
    app.config["TESTING"] = True
    c = app.test_client()
    c.post("/welcome")
    html = c.get("/settings").get_data(as_text=True)
    assert "来自系统环境变量" in html
    assert "VISION_BASE_URL" in html
    assert "来自环境变量，页面不可改" in html
    # 被锁字段带 disabled
    assert 'name="VISION_BASE_URL" value="https://env-var.example.com/v1/chat/completions" disabled' in html
    # 但保存 .env 中自己设置的值不受影响（.env 优先于页面，环境变量优先于 .env）
    resp = c.post("/settings", data={"VISION_MODEL": "m1"})
    assert resp.status_code == 302
    import envfile
    assert envfile.read_env(env_path)["VISION_MODEL"] == "m1"


# ---------------- 模型列表（settings/models） ----------------

def test_list_models_url_derivation():
    sys.path.insert(0, os.path.join(_ROOT, "web"))
    import llm_client
    assert llm_client._models_url(
        "https://x.com/compatible-mode/v1/chat/completions") == \
        "https://x.com/compatible-mode/v1/models"
    assert llm_client._models_url("https://x.com/v1/") == "https://x.com/v1/models"


def test_settings_models_endpoint(client, env_path, monkeypatch):
    """拉模型列表：mock urlopen，验证解析与排序。"""
    import io as _io
    import json as _json
    sys.path.insert(0, os.path.join(_ROOT, "web"))
    import llm_client

    class Resp:
        def read(self):
            return _json.dumps({"data": [{"id": "qwen3.8-max"}, {"id": "glm-5.3"}]}).encode()
        def __enter__(self): return self
        def __exit__(self, *a): return False

    monkeypatch.setattr(llm_client.urllib.request, "urlopen",
                        lambda req, timeout=None: Resp())
    envfile.write_env(env_path, {
        "VISION_API_KEY": "sk-x",
        "VISION_BASE_URL": "https://x.com/v1/chat/completions"})
    resp = client.post("/settings/models", json={"target": "vision"})
    assert resp.status_code == 200
    assert resp.get_json()["models"] == ["glm-5.3", "qwen3.8-max"]


def test_normalize_chat_url_appends_suffix(capsys):
    """端点缺 /chat/completions 时自动补齐并告警（不静默）。"""
    import llm_client
    assert llm_client.normalize_chat_url("https://x.com/v1") == \
        "https://x.com/v1/chat/completions"
    assert "补齐" in capsys.readouterr().err
    assert llm_client.normalize_chat_url(
        "https://x.com/v1/chat/completions") == "https://x.com/v1/chat/completions"


# ---------------- 设置页 UX 修正（2026-10-14） ----------------

def test_clear_secret_via_checkbox(client, env_path):
    """机密键勾选「清除」→ 显式置空（留空=不修改的语义不变）。"""
    envfile.write_env(env_path, {"VISION_API_KEY": "sk-old"})
    resp = client.post("/settings", data={"CLEAR_VISION_API_KEY": "on"})
    assert resp.status_code == 302
    env = envfile.read_env(env_path)
    assert env.get("VISION_API_KEY", None) in (None, "")


def test_settings_hints_temperature_and_timeout(client):
    html = client.get("/settings").get_data(as_text=True)
    assert "随机性" in html and "推荐留空" in html      # 温度说明
    assert "推荐 150–300" in html                        # 超时推荐值
    assert "获取列表" in html and "datalist" in html     # 模型下拉


def test_models_endpoint_requires_admin(client):
    resp = client.post("/settings/models", json={"target": "vision"},
                       environ_overrides={"REMOTE_ADDR": "192.168.3.20"})
    assert resp.status_code == 403


def test_vision_config_not_self_latching(client, env_path, monkeypatch):
    """_configure_vision 把生效配置注入 os.environ 后，cfg() 仍读 .env 新值
    （回归：进程内注入不得自我锁存，改配置后无需重启服务）。"""
    import json as _json
    import vision_client
    seen = []

    class Resp:
        def read(self):
            return _json.dumps({"choices": [{"message": {"content": "舌面"}}]}).encode()
        def __enter__(self): return self
        def __exit__(self, *a): return False

    # reload 会重建 vision_client.call，只能钉在更底层 urlopen 上
    def fake_urlopen(req, timeout=None):
        seen.append(_json.loads(req.data.decode())["model"])
        return Resp()
    monkeypatch.setattr(vision_client.urllib.request, "urlopen", fake_urlopen)
    envfile.write_env(env_path, {
        "VISION_API_KEY": "sk-x", "VISION_MODEL": "model-a",
        "VISION_BASE_URL": "https://x.com/v1/chat/completions"})
    client.post("/settings/test", json={"target": "vision"})
    envfile.write_env(env_path, {"VISION_MODEL": "model-b"})
    client.post("/settings/test", json={"target": "vision"})
    assert seen == ["model-a", "model-b"]
