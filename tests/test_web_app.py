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
    app = create_app(env_file=env_path,
               data_root=os.path.join(os.path.dirname(env_path), "data"))
    app.config["TESTING"] = True
    c = app.test_client()
    c.post("/welcome", headers={"Origin": "http://localhost"})  # 完成启动声明确认，免打扰其余用例
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
    app = create_app(env_file=env_path,
               data_root=os.path.join(os.path.dirname(env_path), "data"))
    app.config["TESTING"] = True
    c = app.test_client()
    resp = c.get("/")
    assert resp.status_code == 302
    assert "/welcome" in resp.headers["Location"]
    # 确认后放行，且未配 key 时落到设置页
    resp = c.post("/welcome", headers={"Origin": "http://localhost"})
    assert resp.status_code == 302
    assert "/settings" in resp.headers["Location"]
    assert c.get("/").status_code == 200


def test_welcome_discloses_model_limits_and_unknown_semantics(client):
    html = client.get("/welcome").get_data(as_text=True)
    assert "不构成医疗诊断" in html
    assert "你在设置页自配置的视觉模型" in html
    assert "新流程会标为「未知」" in html
    assert "兼容 0 分也不代表确认正常" in html
    assert "对照原图人工复核" in html


def test_welcome_ack_lands_home_when_configured(client, env_path):
    envfile.write_env(env_path, {"VISION_API_KEY": "sk-x"})
    resp = client.post("/welcome", headers={"Origin": "http://localhost"})
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
    app = create_app(env_file=env_path,
               data_root=os.path.join(os.path.dirname(env_path), "data"))
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
    app = create_app(env_file=env_path,
               data_root=os.path.join(os.path.dirname(env_path), "data"))
    app.config["TESTING"] = True
    c = app.test_client()
    c.post("/welcome", headers={"Origin": "http://localhost"})
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
    """拉模型列表：mock 安全传输，验证解析与排序。"""
    import io as _io
    import json as _json
    sys.path.insert(0, os.path.join(_ROOT, "web"))
    import safe_fetch

    class Resp:
        def __init__(self):
            self.stream = _io.BytesIO(_json.dumps(
                {"data": [{"id": "qwen3.8-max"}, {"id": "glm-5.3"}]}).encode())
        def read(self, size=-1): return self.stream.read(size)
        def __enter__(self): return self
        def __exit__(self, *a): return False

    monkeypatch.setattr(safe_fetch, "urlopen",
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


def test_vision_config_fresh_request_snapshot(client, env_path, monkeypatch):
    """每个请求独立读取快照，修改配置后无需重启或 reload。"""
    import io as _io
    import json as _json
    import safe_fetch
    seen = []

    class Resp:
        def __init__(self):
            self.stream = _io.BytesIO(_json.dumps(
                {"choices": [{"message": {"content": "舌面"}}]}).encode())
        def read(self, size=-1): return self.stream.read(size)
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def fake_urlopen(req, timeout=None):
        seen.append(_json.loads(req.data.decode())["model"])
        return Resp()
    monkeypatch.setattr(safe_fetch, "urlopen", fake_urlopen)
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
    import safe_fetch
    seen = {}

    class Resp:
        def __init__(self):
            self.stream = _io.BytesIO(_json.dumps({"data": [{"id": "m1"}]}).encode())
        def read(self, size=-1): return self.stream.read(size)
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def capture(req, timeout=None):
        seen["url"] = req.full_url
        seen["auth"] = req.headers.get("Authorization")
        return Resp()

    monkeypatch.setattr(safe_fetch, "urlopen", capture)
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
    app = create_app(env_file=env_path,
               data_root=os.path.join(os.path.dirname(env_path), "data"))
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


def test_welcome_discloses_custom_kb_responsibilities(client):
    html = client.get("/welcome").get_data(as_text=True)
    assert "使用自建知识库时" in html
    assert "有权复制、整理和使用" in html
    assert "候选条文不等于模型实际引用" in html
    assert "不表示系统或作者认可其内容" in html
    assert "记录、照片与知识库文件保存在你的本机" in html
    assert "主动配置云端模型" in html
    assert "不要将私人资料" not in html
    assert "ZIP 提交到公开仓库" not in html
    assert html.count('class="ack-row"') == 3


def test_settings_links_custom_kb_guide(client):
    html = client.get("/settings").get_data(as_text=True)
    assert 'href="/kb-guide/"' in html
    assert "自建知识库指南 ↗" in html
    assert 'target="_blank" rel="noopener"' in html
    heading_index = html.index("<h2>知识库</h2>")
    link_index = html.index('href="/kb-guide/"', heading_index)
    assert heading_index < link_index < html.index('id="kb-card-constitution"')


def test_kb_guide_public_but_settings_requires_boot_ack(env_path, monkeypatch):
    """自建手册保持公开；远程设置页只读状态也必须先确认 welcome。"""
    monkeypatch.delenv("VISION_API_KEY", raising=False)
    app = create_app(env_file=env_path,
                     data_root=os.path.join(os.path.dirname(env_path), "data"))
    app.config["TESTING"] = True
    c = app.test_client()
    response = c.get("/kb-guide/", environ_overrides={"REMOTE_ADDR": "192.0.2.10"})
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    for text in ("从中医著作到知识库", "让 AI 分批整理资料",
                 "第一步：核对资料", "第二步：收到", "第三步：收到",
                 "清单已确认", "正文已核对", "正文格式与原文复核",
                 "导入综合知识库", "导入后的验收"):
        assert text in html
    assert 'href="/settings"' in html
    settings = c.get("/settings", environ_overrides={"REMOTE_ADDR": "192.0.2.10"})
    assert settings.status_code == 302
    assert settings.headers["Location"] == "/welcome"
    c.post("/welcome", headers={"Origin": "http://localhost"},
           environ_overrides={"REMOTE_ADDR": "192.0.2.10"})
    settings = c.get("/settings", environ_overrides={"REMOTE_ADDR": "192.0.2.10"})
    assert settings.status_code == 200
    assert "自建知识库指南" in settings.get_data(as_text=True)


def test_kb_guide_markdown_source_is_indexed():
    import io
    guide = io.open(os.path.join(_ROOT, "docs", "kb-guide.md"),
                    encoding="utf-8").read()
    for text in ("从中医著作到知识库", "schema_version: 1",
                 "category: composite", "category: constitution",
                 "diagnostics/", "diet-lifestyle/", "formulas/",
                 "候选参考不等于模型实际引用", "主题—出处",
                 "第二步：收到“清单已确认”", "第三步：收到“正文已核对”",
                 "普通聊天 AI", "AI 可以协助列出原文与摘要的差异"):
        assert text in guide
    assert "tcm-kb-packages" not in guide and "C:\\Users" not in guide
    html = io.open(os.path.join(_ROOT, "docs", "kb-guide.html"),
                   encoding="utf-8").read()
    for text in ("从中医著作到知识库", "让 AI 分批整理资料",
                 "category: composite", "第一步：核对资料",
                 "第二步：收到", "第三步：收到", "清单已确认", "正文已核对"):
        assert text in html
    index = io.open(os.path.join(_ROOT, "docs", "README.md"),
                    encoding="utf-8").read()
    assert "[从中医著作到知识库](kb-guide.md)" in index


def test_custom_kb_docs_recommend_single_composite_zip():
    import io
    expected = ("只需用 AI 制作一个综合知识库 ZIP，"
                "不必再拆成体质、食疗、方剂三个子库或三个 ZIP")
    for relative in ("docs/kb-guide.md", "docs/kb-guide.html",
                     "docs/KB_AUTHORING.md"):
        text = io.open(os.path.join(_ROOT, relative), encoding="utf-8").read()
        assert expected in text, relative
        assert "综合包内的标准目录只用于主题归类，不是三个子库" in text, relative


def test_user_facing_docs_link_custom_kb_guide():
    import io
    for relative in ("README.md", "docs/web-quickstart.md", "docs/user-guide.md"):
        text = io.open(os.path.join(_ROOT, relative), encoding="utf-8").read()
        assert "kb-guide.md" in text, relative
    html = io.open(os.path.join(_ROOT, "docs", "user-guide.html"),
                   encoding="utf-8").read()
    assert 'href="/kb-guide/"' in html
    assert 'href="#sec-kb"' in html and 'id="sec-kb"' in html


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
    # 真改 WEB_HOST → 跳转带标记；非回环监听须已有管理口令
    client.post("/settings", data={"WEB_ADMIN_TOKEN": "test-secret"})
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


def test_llm_banner_absent_when_ready(client, env_path):
    """辨证模型三要素齐全 → 不弹警告（正例）。"""
    import envfile
    envfile.write_env(env_path, {"LLM_API_KEY": "sk-x", "LLM_MODEL": "m",
                                 "LLM_BASE_URL": "https://x/v1/chat/completions"})
    html = client.get("/").get_data(as_text=True)
    assert "LLM_API_KEY" not in html


def test_welcome_page_exempt_from_banners(client):
    """welcome 页不弹缺配警告（它本身就是引导页）。"""
    html = client.get("/welcome").get_data(as_text=True)
    assert "VISION_API_KEY" not in html and "LLM_API_KEY" not in html


def test_llm_banner_returns_when_reenabled(client):
    """关闭→警告消失；重开→警告恢复（.env 回读链）。"""
    client.post("/settings", data={"FORM_LLM": "1"})
    assert "LLM_API_KEY" not in client.get("/").get_data(as_text=True)
    client.post("/settings", data={"FORM_LLM": "1", "LLM_ENABLED": "1"})
    assert "LLM_API_KEY" in client.get("/").get_data(as_text=True)


def test_vision_settings_reach_photo_observation(tmp_path, monkeypatch):
    import io
    import wizard_store

    for key in ("VISION_API_KEY", "VISION_MODEL", "VISION_BASE_URL",
                "VISION_TEMPERATURE", "VISION_TIMEOUT", "VISION_MAX_TOKENS"):
        monkeypatch.delenv(key, raising=False)
    env_path = str(tmp_path / ".env")
    app = create_app(env_file=env_path, data_root=str(tmp_path / "data"))
    app.config["TESTING"] = True
    client = app.test_client()
    client.post("/welcome", headers={"Origin": "http://localhost"})
    client.post("/settings", data={
        "FORM_VISION": "1", "VISION_ENABLED": "1", "VISION_API_KEY": "sk-test",
        "VISION_MODEL": "model-from-settings",
        "VISION_BASE_URL": "https://example.invalid/v1/chat/completions",
        "VISION_TEMPERATURE": "0.6", "VISION_TIMEOUT": "9",
        "VISION_MAX_TOKENS": "7000",
    })
    seen = {}

    def fake_observe(part, img_path, **options):
        seen.update(options)
        return {"舌质颜色": "淡红"}, []

    monkeypatch.setattr(wizard_store, "observe_photo", fake_observe)
    resp = client.post("/wizard/photo", data={
        "part": "舌面", "file": (io.BytesIO(__import__("test_web_wizard").PNG), "photo.jpg"),
    }, content_type="multipart/form-data")

    assert resp.status_code == 200, resp.get_json()
    assert seen == {
        "model": "model-from-settings",
        "url": "https://example.invalid/v1/chat/completions",
        "key": "sk-test", "timeout": 9, "max_tokens": 7000, "temperature": 0.6,
    }


@pytest.mark.parametrize("key", ["VISION_TEMPERATURE", "VISION_TIMEOUT"])
def test_invalid_vision_number_returns_400(tmp_path, monkeypatch, key):
    import io
    import wizard_store

    for name in ("VISION_API_KEY", "VISION_MODEL", "VISION_BASE_URL",
                 "VISION_TEMPERATURE", "VISION_TIMEOUT"):
        monkeypatch.delenv(name, raising=False)
    app = create_app(env_file=str(tmp_path / ".env"),
                     data_root=str(tmp_path / "data"))
    app.config["TESTING"] = True
    client = app.test_client()
    client.post("/welcome", headers={"Origin": "http://localhost"})
    envfile.write_env(str(tmp_path / ".env"), {
        "VISION_API_KEY": "sk-test", "VISION_MODEL": "m",
        "VISION_BASE_URL": "https://example.invalid/v1/chat/completions",
        key: "not-a-number",
    })
    monkeypatch.setattr(wizard_store, "observe_photo",
                        lambda *args, **kwargs: ({"舌质颜色": "淡红"}, []))

    resp = client.post("/wizard/photo", data={
        "part": "舌面", "file": (io.BytesIO(__import__("test_web_wizard").PNG), "photo.jpg"),
    }, content_type="multipart/form-data")

    assert resp.status_code == 400
    assert key in resp.get_json()["error"]


def test_wizard_submit_rejects_unknown_acknowledgement(tmp_path, monkeypatch):
    import wizard_store

    monkeypatch.delenv("VISION_API_KEY", raising=False)
    app = create_app(env_file=str(tmp_path / ".env"),
                     data_root=str(tmp_path / "data"))
    app.config["TESTING"] = True
    client = app.test_client()
    client.post("/welcome", headers={"Origin": "http://localhost"})
    today = wizard_store.datetime.date.today().isoformat()
    daily = tmp_path / "data" / "records" / "daily"
    draft = {
        "date": today,
        "parts": {p["part"]: {"status": "skip_uncovered"}
                  for p in wizard_store.PARTS},
        "danger_flags": {"triggered": ["daiyang"], "not_triggered": []},
    }
    wizard_store.save_draft(str(daily), draft)

    resp = client.post("/wizard/submit",
                       json={"mode": "new", "acknowledge": "bogus"})

    assert resp.status_code == 400
    assert not (daily / f"{today}_analysis.json").exists()


@pytest.mark.parametrize("key", ["VISION_TEMPERATURE", "VISION_TIMEOUT"])
def test_settings_rejects_invalid_vision_number(client, env_path, key):
    resp = client.post("/settings", data={
        "FORM_VISION": "1", "VISION_ENABLED": "1", key: "not-a-number",
    })

    assert resp.status_code == 400
    assert key in resp.get_data(as_text=True)
    assert key not in envfile.read_env(env_path)


def test_boot_ack_rejects_forged_cookie(client):
    client.set_cookie("boot_ack", "forged")
    resp = client.get("/")
    assert resp.status_code == 302
    assert "/welcome" in resp.headers["Location"]


@pytest.mark.parametrize("path", [
    "/demo", "/settings", "/settings/models", "/settings/test",
    "/record/2026-06-25/field", "/record/2026-06-25/report",
    "/record/2026-06-25/restore", "/wizard/photo", "/wizard/field",
    "/wizard/manual", "/wizard/inquiry", "/wizard/context",
    "/wizard/skip", "/wizard/submit",
])
def test_lan_write_endpoints_reject_missing_credentials(client, env_path, path):
    resp = client.post(path, json={}, environ_overrides={"REMOTE_ADDR": "192.168.1.20"})
    assert resp.status_code == 403, (path, resp.status_code)
    target = os.path.join(os.path.dirname(env_path), "data", "records", "daily",
                          "2026-06-25_analysis.json")
    assert not os.path.exists(target), path


def test_upload_rejects_non_image_extension(client, env_path):
    import io
    resp = client.post("/wizard/photo", data={
        "part": "舌面", "file": (io.BytesIO(b"not-an-image"), "payload.exe"),
    }, content_type="multipart/form-data")
    assert resp.status_code == 400
    photos = os.path.join(os.path.dirname(env_path), "data", "records", "photos")
    assert not os.path.exists(photos)


def test_photo_route_rejects_invalid_date_and_traversal(client):
    assert client.get("/photos/not-a-date/x.jpg").status_code == 404
    assert client.get("/photos/2026-06-25/..%2F..%2F.env").status_code in (400, 404)


def test_default_data_root_and_external_config_are_isolated(tmp_path):
    from src import paths
    assert paths.DATA_ROOT == str(tmp_path / "data")
    with pytest.raises(PermissionError):
        envfile.read_env(os.path.join(_ROOT, ".env"))
