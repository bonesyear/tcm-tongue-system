"""vision_client 单元测试 — 全部 mock，无真实网络请求。"""
import io
import json
import socket
import urllib.error

import pytest

import vision_client


def _fake_response(payload):
    """构造 urlopen 返回值：支持 with 上下文管理，read() 返回 JSON 字节。"""
    class Resp:
        def read(self):
            return json.dumps(payload).encode()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False
    return Resp()


@pytest.fixture(autouse=True)
def _clean_vision_param_env(monkeypatch):
    """清除运行环境残留的 VISION_* 参数变量，避免影响 payload/超时断言。"""
    for name in ("VISION_TEMPERATURE", "VISION_MAX_TOKENS", "VISION_TIMEOUT"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def img(tmp_path):
    p = tmp_path / "t.jpg"
    p.write_bytes(b"\xff\xd8fake-jpeg-bytes")
    return str(p)


@pytest.fixture
def key(monkeypatch):
    monkeypatch.setenv("VISION_API_KEY", "test-key")


def _block_env_files(monkeypatch, tmp_path):
    """让 load_key 读到的 .env 路径都指向不存在的位置。"""
    monkeypatch.setattr(vision_client.os.path, "expanduser",
                        lambda p: str(tmp_path / "nonexistent" / p[2:])
                        if p.startswith("~/") else p)
    monkeypatch.chdir(tmp_path)  # 同时隔离候选清单里的相对路径 ".env"


# ① 正常调用
def test_call_success(monkeypatch, img, key):
    monkeypatch.setattr(vision_client.urllib.request, "urlopen",
                        lambda req, timeout=None: _fake_response(
                            {"choices": [{"message": {"content": "舌面"}}]}))
    dt, out = vision_client.call(img, "prompt")
    assert out == "舌面"
    assert isinstance(dt, int)


def test_call_uses_mime_of_extension(monkeypatch, tmp_path, key):
    png = tmp_path / "t.png"
    png.write_bytes(b"\x89PNG-fake")
    seen = {}

    def capture(req, timeout=None):
        seen["body"] = json.loads(req.data.decode())
        return _fake_response({"choices": [{"message": {"content": "ok"}}]})

    monkeypatch.setattr(vision_client.urllib.request, "urlopen", capture)
    vision_client.call(str(png), "prompt")
    url = seen["body"]["messages"][0]["content"][0]["image_url"]["url"]
    assert url.startswith("data:image/png;base64,")


def test_call_payload_defaults(monkeypatch, img, key):
    """默认（未设 VISION_* 参数）：payload 完全不含 temperature 键（由服务端
    模型默认值生效），max_tokens=600，不擅自加 seed/top_p。"""
    seen = {}

    def capture(req, timeout=None):
        seen["body"] = json.loads(req.data.decode())
        return _fake_response({"choices": [{"message": {"content": "ok"}}]})

    monkeypatch.setattr(vision_client.urllib.request, "urlopen", capture)
    vision_client.call(img, "prompt")
    assert "temperature" not in seen["body"]
    assert seen["body"]["max_tokens"] == 600
    assert "seed" not in seen["body"]
    assert "top_p" not in seen["body"]


def test_call_payload_temperature_from_env(monkeypatch, img, key):
    """设置 VISION_TEMPERATURE 后 payload 出现 temperature 键。"""
    monkeypatch.setenv("VISION_TEMPERATURE", "0.6")
    seen = {}

    def capture(req, timeout=None):
        seen["body"] = json.loads(req.data.decode())
        return _fake_response({"choices": [{"message": {"content": "ok"}}]})

    monkeypatch.setattr(vision_client.urllib.request, "urlopen", capture)
    vision_client.call(img, "prompt")
    assert seen["body"]["temperature"] == 0.6


def test_call_payload_max_tokens_from_env(monkeypatch, img, key):
    """VISION_MAX_TOKENS 生效并覆盖默认 600。"""
    monkeypatch.setenv("VISION_MAX_TOKENS", "8000")
    seen = {}

    def capture(req, timeout=None):
        seen["body"] = json.loads(req.data.decode())
        return _fake_response({"choices": [{"message": {"content": "ok"}}]})

    monkeypatch.setattr(vision_client.urllib.request, "urlopen", capture)
    vision_client.call(img, "prompt")
    assert seen["body"]["max_tokens"] == 8000


# ② HTTP 4xx/5xx 与缺 choices 不抛 KeyError，而是带状态码的 RuntimeError
def test_call_http_500(monkeypatch, img, key):
    def boom(req, timeout=None):
        raise urllib.error.HTTPError("http://x", 500, "Server Error", {},
                                     io.BytesIO(b"internal boom"))
    monkeypatch.setattr(vision_client.urllib.request, "urlopen", boom)
    with pytest.raises(RuntimeError) as e:
        vision_client.call(img, "p")
    assert "500" in str(e.value)


def test_call_http_401(monkeypatch, img, key):
    def boom(req, timeout=None):
        raise urllib.error.HTTPError("http://x", 401, "Unauthorized", {},
                                     io.BytesIO(b"bad key"))
    monkeypatch.setattr(vision_client.urllib.request, "urlopen", boom)
    with pytest.raises(RuntimeError) as e:
        vision_client.call(img, "p")
    assert "401" in str(e.value)


def test_call_missing_choices(monkeypatch, img, key):
    monkeypatch.setattr(vision_client.urllib.request, "urlopen",
                        lambda req, timeout=None: _fake_response({"error": "nope"}))
    with pytest.raises(RuntimeError):
        vision_client.call(img, "p")


def test_call_url_error(monkeypatch, img, key):
    def boom(req, timeout=None):
        raise urllib.error.URLError("connection refused")
    monkeypatch.setattr(vision_client.urllib.request, "urlopen", boom)
    with pytest.raises(RuntimeError):
        vision_client.call(img, "p")


# ③ 参数不足 / 未知 mode 退出码 2
def test_main_no_args(capsys):
    with pytest.raises(SystemExit) as e:
        vision_client.main([])
    assert e.value.code == 2
    assert "用法" in capsys.readouterr().err


def test_main_observe_missing_part(img, capsys):
    with pytest.raises(SystemExit) as e:
        vision_client.main(["observe", img])
    assert e.value.code == 2
    assert "用法" in capsys.readouterr().err


def test_main_unknown_mode(img, capsys):
    with pytest.raises(SystemExit) as e:
        vision_client.main(["bogus", img])
    assert e.value.code == 2
    assert capsys.readouterr().err  # 不得静默无输出


# ④ key 未设置时报错（显式 RuntimeError，非 assert）
def test_call_without_key(monkeypatch, img, tmp_path):
    monkeypatch.delenv("VISION_API_KEY", raising=False)
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    _block_env_files(monkeypatch, tmp_path)
    with pytest.raises(RuntimeError) as e:
        vision_client.call(img, "p")
    assert "VISION_API_KEY" in str(e.value)


# ⑤ .env 注释行与行内注释处理
def test_load_key_env_file_comments(monkeypatch, tmp_path):
    monkeypatch.delenv("VISION_API_KEY", raising=False)
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    env_dir = tmp_path / ".hermes" / "profiles" / "tcm-tongue"
    env_dir.mkdir(parents=True)
    (env_dir / ".env").write_text(
        "# 整行注释\n"
        "\n"
        "VISION_API_KEY=sk-abc  # 行内注释\n"
        "EMPTY=\n"
        "INVALID_LINE_WITHOUT_EQUALS\n"
        'QUOTED="sk-quoted"\n',
        encoding="utf-8")
    monkeypatch.setattr(vision_client.os.path, "expanduser",
                        lambda p: str(tmp_path / p[2:]) if p.startswith("~/") else p)
    monkeypatch.chdir(tmp_path)  # 隔离候选清单里的相对路径 ".env"
    assert vision_client.load_key() == "sk-abc"


# ⑥ MIME 映射
@pytest.mark.parametrize("name,expected", [
    ("a.png", "image/png"),
    ("a.jpg", "image/jpeg"),
    ("a.jpeg", "image/jpeg"),
    ("a.JPG", "image/jpeg"),
    ("a.webp", "image/webp"),
    ("a.bmp", "image/jpeg"),
    ("a", "image/jpeg"),
])
def test_mime_type(name, expected):
    assert vision_client.mime_type(name) == expected


# ⑦ classify 未知类别回退 '其他'
def test_classify_unknown_fallback(monkeypatch, img, capsys):
    monkeypatch.setattr(vision_client, "call",
                        lambda *a, **k: (1, "这是一张舌头照片\n第二行"))
    vision_client.main(["classify", img])
    captured = capsys.readouterr()
    assert captured.out.strip() == "其他"
    assert captured.err  # stderr 有警告


def test_classify_known_output(monkeypatch, img, capsys):
    monkeypatch.setattr(vision_client, "call", lambda *a, **k: (1, "舌面\n"))
    vision_client.main(["classify", img])
    captured = capsys.readouterr()
    assert captured.out.strip() == "舌面"
    assert captured.err == ""


# ⑧ observe 未知部位打 warning 并回退 '其他' prompt（与 classify 对齐，
#    不得静默回退——调用方拼错部位名会拿到通用 prompt 却不自知）
def test_observe_unknown_part_warns_and_falls_back(monkeypatch, img, capsys):
    seen = {}

    def fake_call(img_path, prompt, timeout=150):
        seen["prompt"] = prompt
        return (1, "{}")

    monkeypatch.setattr(vision_client, "call", fake_call)
    vision_client.main(["observe", img, "鼻子"])
    captured = capsys.readouterr()
    assert "鼻子" in captured.err  # warning 含实际收到值
    assert "舌面" in captured.err  # warning 含可用类别列表
    assert seen["prompt"] == vision_client.PROMPTS["其他"]  # 行为仍回退


# ⑨ respond 非 JSON 文本 → RuntimeError（不得裸 JSONDecodeError 崩溃）
def test_call_invalid_json_response(monkeypatch, img, key):
    class Resp:
        def read(self):
            return b"<html>gateway error</html>"

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(vision_client.urllib.request, "urlopen",
                        lambda req, timeout=None: Resp())
    with pytest.raises(RuntimeError) as e:
        vision_client.call(img, "p")
    assert "invalid JSON" in str(e.value)


# ⑩ 超时类异常 → RuntimeError（socket.timeout 与 TimeoutError 同路径）
def test_call_socket_timeout(monkeypatch, img, key):
    def boom(req, timeout=None):
        raise socket.timeout("timed out")
    monkeypatch.setattr(vision_client.urllib.request, "urlopen", boom)
    with pytest.raises(RuntimeError) as e:
        vision_client.call(img, "p")
    assert "timed out" in str(e.value)


# ⑪ 舌面 prompt 的"舌质润燥"键名指令钉住——record.py A 路径依赖该键名
#    约定，被误改会静默断链（prompt 键名与解析键名漂移无任何报错）
def test_tongue_prompt_declares_rzao_key_name():
    assert '键名固定为"舌质润燥"' in vision_client.PROMPTS["舌面"]


# ⑫ 可观测性告警：四类失败从静默变为 stderr 可见（统一前缀 [vision_client][warn]）
def test_call_warns_on_empty_content(monkeypatch, img, key, capsys):
    """① 空 content：告警指向 reasoning_content 与 VISION_MAX_TOKENS。"""
    monkeypatch.setattr(vision_client.urllib.request, "urlopen",
                        lambda req, timeout=None: _fake_response(
                            {"choices": [{"message": {"content": "  \n"},
                                          "finish_reason": "stop"}]}))
    dt, out = vision_client.call(img, "prompt")
    assert out.strip() == ""
    err = capsys.readouterr().err
    assert vision_client.WARN_PREFIX in err
    assert "VISION_MAX_TOKENS" in err
    assert "reasoning_content" in err


def test_call_warns_on_length_finish_reason(monkeypatch, img, key, capsys):
    """② finish_reason=length → 截断告警；正常 finish_reason=stop 无任何告警。"""
    # 正常路径基线：stderr 必须为空
    monkeypatch.setattr(vision_client.urllib.request, "urlopen",
                        lambda req, timeout=None: _fake_response(
                            {"choices": [{"message": {"content": "ok"},
                                          "finish_reason": "stop"}]}))
    vision_client.call(img, "prompt")
    assert capsys.readouterr().err == ""

    monkeypatch.setattr(vision_client.urllib.request, "urlopen",
                        lambda req, timeout=None: _fake_response(
                            {"choices": [{"message": {"content": '{"舌质颜色":"淡红'},
                                          "finish_reason": "length"}]}))
    vision_client.call(img, "prompt")
    err = capsys.readouterr().err
    assert vision_client.WARN_PREFIX in err
    assert "length" in err
    assert "截断" in err


def test_observe_warns_on_non_json_output(monkeypatch, img, capsys):
    """③ observe 输出非 JSON（去围栏后不以 '{' 开头）→ 告警；stdout 契约不变。"""
    monkeypatch.setattr(vision_client, "call",
                        lambda *a, **k: (1, "舌质淡红，舌苔薄白"))
    vision_client.main(["observe", img, "舌面"])
    captured = capsys.readouterr()
    assert vision_client.WARN_PREFIX in captured.err
    assert "JSON" in captured.err
    assert captured.out == "[1s] 舌质淡红，舌苔薄白\n"  # stdout 不受影响


def test_call_http_4xx_includes_troubleshooting_hint(monkeypatch, img, key):
    """④ HTTP 4xx → RuntimeError 追加通用排查提示；5xx 不追加。"""
    def boom400(req, timeout=None):
        raise urllib.error.HTTPError("http://x", 400, "Bad Request", {},
                                     io.BytesIO(b"invalid parameter"))
    monkeypatch.setattr(vision_client.urllib.request, "urlopen", boom400)
    with pytest.raises(RuntimeError) as e:
        vision_client.call(img, "p")
    assert "400" in str(e.value)
    assert "排查提示" in str(e.value)
    assert "VISION_API_KEY" in str(e.value)

    def boom500(req, timeout=None):
        raise urllib.error.HTTPError("http://x", 500, "Server Error", {},
                                     io.BytesIO(b"boom"))
    monkeypatch.setattr(vision_client.urllib.request, "urlopen", boom500)
    with pytest.raises(RuntimeError) as e:
        vision_client.call(img, "p")
    assert "排查提示" not in str(e.value)


# ⑬ 历史兼容 key 变量（DASHSCOPE_API_KEY）：可用但打弃用提示；新名优先
def test_load_key_legacy_env_var_still_works(monkeypatch, tmp_path, capsys):
    """旧变量仍可用（作者环境回归防护），但打一条 stderr 弃用提示。"""
    monkeypatch.delenv("VISION_API_KEY", raising=False)
    monkeypatch.setenv("DASHSCOPE_API_KEY", "legacy-key")
    _block_env_files(monkeypatch, tmp_path)
    assert vision_client.load_key() == "legacy-key"
    err = capsys.readouterr().err
    assert vision_client.WARN_PREFIX in err
    assert "DASHSCOPE_API_KEY" in err and "VISION_API_KEY" in err


def test_load_key_new_var_preferred_over_legacy(monkeypatch, tmp_path, capsys):
    """新名优先：两者都设时取 VISION_API_KEY，且无任何告警。"""
    monkeypatch.setenv("VISION_API_KEY", "new-key")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "legacy-key")
    _block_env_files(monkeypatch, tmp_path)
    assert vision_client.load_key() == "new-key"
    assert capsys.readouterr().err == ""


def test_load_key_legacy_from_env_file(monkeypatch, tmp_path, capsys):
    """.env 里的旧变量同样兼容（.env 回退路径回归防护）。"""
    monkeypatch.delenv("VISION_API_KEY", raising=False)
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    (tmp_path / ".env").write_text("DASHSCOPE_API_KEY=sk-legacy\n",
                                   encoding="utf-8")
    _block_env_files(monkeypatch, tmp_path)  # chdir(tmp_path) 使相对 .env 指向它
    assert vision_client.load_key() == "sk-legacy"
    assert vision_client.WARN_PREFIX in capsys.readouterr().err


def test_missing_key_error_message_vendor_neutral(monkeypatch, img, tmp_path):
    """缺 key 报错厂商中立：主变量是 VISION_API_KEY，旧变量只作兼容说明出现。"""
    monkeypatch.delenv("VISION_API_KEY", raising=False)
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    _block_env_files(monkeypatch, tmp_path)
    with pytest.raises(RuntimeError) as e:
        vision_client.call(img, "p")
    msg = str(e.value)
    assert "VISION_API_KEY" in msg
    assert "历史变量" in msg  # 旧变量仅以兼容说明的身份出现
