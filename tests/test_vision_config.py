"""B12：视觉配置快照、响应结构与统一输出提取。"""
import io
import json
import urllib.error

import pytest

import envfile
import vision_client
import wizard_store
import safe_fetch
from photo_store import clean_image_bytes


def _valid_image(path):
    from PIL import Image
    Image.new("RGB", (2, 2), (128, 128, 128)).save(path, format="JPEG")


def _response(payload):
    class Response:
        def __init__(self):
            self.stream = io.BytesIO(json.dumps(payload).encode())

        def read(self, size=-1):
            return self.stream.read(size)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    return Response()


def test_cli_env_file_controls_complete_request(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    envfile.write_env(str(tmp_path / ".env"), {
        "VISION_API_KEY": "sk-synthetic",
        "VISION_MODEL": "env-model",
        "VISION_BASE_URL": "http://env.test/v1/chat/completions",
        "VISION_MAX_TOKENS": "8000",
        "VISION_TIMEOUT": "300",
        "VISION_TEMPERATURE": "0.9",
    })
    image = tmp_path / "image.jpg"
    _valid_image(image)
    seen = {}

    def capture(req, timeout):
        seen["url"] = req.full_url
        seen["auth"] = req.headers["Authorization"]
        seen["payload"] = json.loads(req.data.decode())
        seen["timeout"] = round(timeout)
        return _response({"choices": [{"message": {"content": "ok"}}]})

    monkeypatch.setattr(safe_fetch, "urlopen", capture)
    _, text = vision_client.call(str(image), "prompt")
    assert text == "ok"
    assert seen == {
        "url": "http://env.test/v1/chat/completions",
        "auth": "Bearer sk-synthetic",
        "payload": {
            "model": "env-model",
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {
                        "url": "data:image/jpeg;base64," +
                               __import__("base64").b64encode(clean_image_bytes(image.read_bytes())).decode()}},
                    {"type": "text", "text": "prompt"},
                ],
            }],
            "max_tokens": 8000,
            "temperature": 0.9,
        },
        "timeout": 300,
    }


def test_missing_url_fails_closed(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("VISION_API_KEY", "sk-synthetic")
    image = tmp_path / "image.jpg"
    _valid_image(image)
    called = []
    monkeypatch.setattr(safe_fetch, "urlopen", lambda *args: called.append(args))
    with pytest.raises(RuntimeError, match="VISION_BASE_URL"):
        vision_client.call(str(image), "prompt")
    assert called == []


@pytest.mark.parametrize("text,expected", [
    ("舌面。", "舌面"),
    ("**舌面**", "舌面"),
    ("类别：舌面", "舌面"),
    ("<think>观察形态</think>\n头面部。", "头面部"),
    ("舌面部", "其他"),
    ("舌面和舌底", "其他"),
])
def test_classify_normalization(text, expected):
    assert vision_client.normalize_classify(text) == expected


@pytest.mark.parametrize("text", [
    '<think>先看颜色</think>{"舌质颜色":"淡红"}',
    '观察结果：\n```json\n{"舌质颜色":"淡红"}\n```',
    '前言 {"structured":{},"markdown":"正文"} 后缀',
])
def test_extract_json_object(text):
    result = vision_client.extract_json(text)
    assert isinstance(result, dict) and result


def test_extract_json_rejects_missing_object():
    with pytest.raises(ValueError):
        vision_client.extract_json("不是 JSON")


def test_observe_photo_uses_shared_json_extraction(monkeypatch):
    monkeypatch.setattr(
        vision_client, "call",
        lambda *args, **kwargs: (0, '<think>分析</think>前言\n```json\n'
                                 '{"舌质颜色":"淡红"}\n```'))
    result, _ = wizard_store.observe_photo(
        "舌面", "synthetic.jpg", model="m", url="u", key="k")
    assert result == {"舌质颜色": "淡红"}


def test_multipart_content_and_bad_response_shapes(tmp_path, monkeypatch):
    image = tmp_path / "image.jpg"
    _valid_image(image)
    monkeypatch.setattr(safe_fetch, "urlopen", lambda req, timeout: _response({
        "choices": [{"message": {"content": [
            {"type": "text", "text": "舌"}, {"type": "text", "text": "面"},
        ]}}],
    }))
    _, text = vision_client.call(str(image), "prompt", model="m", url="http://local.test", key="k")
    assert text == "舌面"

    for payload in ({"choices": [{"message": None}]}, []):
        monkeypatch.setattr(safe_fetch, "urlopen", lambda req, timeout: _response(payload))
        with pytest.raises(RuntimeError):
            vision_client.call(str(image), "prompt", model="m", url="http://local.test", key="k")


def test_429_has_bounded_retries_and_specific_message(tmp_path, monkeypatch):
    image = tmp_path / "image.jpg"
    _valid_image(image)
    calls = []

    def limited(req, timeout):
        calls.append(req.full_url)
        raise urllib.error.HTTPError(req.full_url, 429, "limited", {},
                                     io.BytesIO(b"busy"))

    monkeypatch.setattr(safe_fetch, "urlopen", limited)
    monkeypatch.setattr(safe_fetch.time, "sleep", lambda _: None)
    with pytest.raises(RuntimeError) as error:
        vision_client.call(str(image), "prompt", model="m", url="http://local.test", key="k")
    assert "限流" in str(error.value)
    assert "检查凭证" not in str(error.value)
    assert len(calls) == 3
