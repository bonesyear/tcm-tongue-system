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


def test_models_endpoint_uses_unsaved_form_values(client, monkeypatch):
    """拉模型列表优先用表单里未保存的端点/Key（先填后拉再存的引导序）。"""
    import io as _io
    import json as _json
    import llm_client
    seen = {}

    class Resp:
        def read(self):
            return _json.dumps({"data": [{"id": "m1"}]}).encode()
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def capture(req, timeout=None):
        seen["url"] = req.full_url
        seen["auth"] = req.headers.get("Authorization")
        return Resp()

    monkeypatch.setattr(llm_client.urllib.request, "urlopen", capture)
    resp = client.post("/settings/models", json={
        "target": "vision",
        "base_url": "https://fresh.example.com/v1",
        "api_key": "sk-fresh"})
    assert resp.status_code == 200
    assert seen["url"] == "https://fresh.example.com/v1/chat/completions".replace(
        "/chat/completions", "/models")
    assert seen["auth"] == "Bearer sk-fresh"


# ---------------- 使用手册入口（2026-10-14 手册入口任务书，完成后已移除） ----------------

def test_guide_serves_user_guide_html(client):
    resp = client.get("/guide/", follow_redirects=True)
    assert resp.status_code == 200
    assert "part-tongue-bottom" in resp.get_data(as_text=True)  # 锚点存在


def test_guide_reachable_without_boot_ack(env_path, monkeypatch):
    """手册在 welcome 门禁之外（welcome 页本身就链它，否则死循环）。"""
    monkeypatch.delenv("VISION_API_KEY", raising=False)
    app = create_app(env_file=env_path)
    app.config["TESTING"] = True
    c = app.test_client()  # 不做 /welcome 确认
    resp = c.get("/guide/", follow_redirects=True)
    assert resp.status_code == 200


def test_guide_link_in_nav_and_wizard(client):
    html = client.get("/").get_data(as_text=True)
    assert 'href="/guide"' in html and "手册" in html
    wiz = client.get("/wizard").get_data(as_text=True)
    assert "guide-link" in wiz and "part-tongue-surface" in wiz  # 深链锚点注入 STATE


def test_guide_images_served(client):
    """手册配图可访问（相对路径经 /guide/ 尾斜杠解析到 /guide/images/）。"""
    resp = client.get("/guide/")  # 尾斜杠形态
    assert resp.status_code == 200
    assert "part-tongue-bottom" in resp.get_data(as_text=True)
    img = client.get("/guide/images/tongue_surface.jpg")
    assert img.status_code == 200
    assert img.content_type.startswith("image/")
    img404 = client.get("/guide/images/nope.jpg")
    assert img404.status_code == 404


def test_wizard_tips_consistent_with_design_mock():
    """口径漂移守卫：wizard_store.PARTS 的 tips 与设计稿 mock-data.js
    WIZARD_STEPS 必须一致（四轮审查发现的双副本漂移风险）。"""
    import io
    import re
    mock_js = io.open(os.path.join(
        _ROOT, "web", "design", "assets", "mock-data.js"),
        encoding="utf-8").read()
    # 只取 WIZARD_STEPS 段（文件里还有 photos 等同名 part 块）
    mock_js = mock_js[mock_js.index("const WIZARD_STEPS"):]
    import wizard_store  # noqa: E402（模块顶部已 insert web 路径，此处仅引入）
    for p in wizard_store.PARTS:
        # [^}]*? 限定在条目内，防止跨条目抓到下一 part 的 tips
        m = re.search(r'\{ part: "%s"[^}]*?tips: \[(.*?)\]' % re.escape(p["part"]),
                      mock_js, re.S)
        assert m, f"mock-data.js 缺 {p['part']}"
        # JS 字符串数组粗略还原为 Python 列表比对
        js_tips = re.findall(r'"(.*?)"', m.group(1))
        assert js_tips == p["tips"], f"{p['part']} 提示语与设计稿 mock 数据不一致"


def test_guide_anchors_match_wizard_parts():
    """锚点映射守卫：wizard_store.PARTS 的 guide_anchor 与手册 html 的
    part-* id 必须一一对应（五轮审查指出的未守护映射）。"""
    import io
    import re
    html = io.open(os.path.join(_ROOT, "docs", "user-guide.html"),
                   encoding="utf-8").read()
    html_anchors = set(re.findall(r'id="(part-[^"]+)"', html))
    sys.path.insert(0, os.path.join(_ROOT, "web"))
    import wizard_store
    wizard_anchors = {p["guide_anchor"] for p in wizard_store.PARTS}
    assert wizard_anchors == html_anchors



def test_inquiry_options_glossary_full_coverage():
    """问诊全部选项词在 GLOSSARY 有白话词条（INQUIRY_UX 任务① 验收）。"""
    import sys as _sys
    _sys.path.insert(0, os.path.join(_ROOT, "web"))
    import records_store
    import wizard_store
    opts = set(wizard_store.INQUIRY_SPEC["options"])
    for item in wizard_store.INQUIRY_ITEMS:
        opts.update(item["options"])
    missing = sorted(o for o in opts if o not in records_store.GLOSSARY)
    assert missing == [], f"缺词条: {missing}"


def test_saved_banner_host_sentence_conditional(client, env_path):
    """监听地址提示只在真改了 WEB_HOST 时出现。"""
    resp = client.post("/settings", data={"VISION_MODEL": "m"})
    assert resp.headers["Location"].startswith("/settings?saved=1")
    assert "host_changed" not in resp.headers["Location"]
    html = client.get("/settings?saved=1").get_data(as_text=True)
    assert "监听地址的变更" not in html
    html2 = client.get("/settings?saved=1&host_changed=1").get_data(as_text=True)
    assert "监听地址的变更" in html2
    # 真改 WEB_HOST → 跳转带标记
    resp = client.post("/settings", data={"WEB_HOST": "0.0.0.0"})
    assert "host_changed=1" in resp.headers["Location"]


def test_llm_missing_banner(client):
    """辨证模型启用但未配置 → 全站警告；关闭开关后不再警告。"""
    html = client.get("/").get_data(as_text=True)
    assert "LLM_API_KEY" in html  # 默认启用、未配置 → 警告
    client.post("/settings", data={"FORM_LLM": "1"})  # 关开关
    html = client.get("/").get_data(as_text=True)
    assert "LLM_API_KEY" not in html  # 主动关闭 → 不警告


def test_vision_disabled_no_banner(client, env_path):
    """视觉模型主动关闭 → 不再弹「未配置」警告。"""
    client.post("/settings", data={"FORM_VISION": "1"})
    html = client.get("/").get_data(as_text=True)
    assert "VISION_API_KEY" not in html
