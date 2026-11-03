"""B12 出站传输：本地假响应与临时本机 HTTP 服务。"""
import http.client
import io
import json
import threading
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

import safe_fetch


def _response(body):
    if not isinstance(body, bytes):
        body = json.dumps(body).encode()

    class Response:
        status = 200
        headers = {}

        def __init__(self):
            self.stream = io.BytesIO(body)

        def read(self, size=-1):
            return self.stream.read(size)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def close(self):
            pass

    return Response()


def _http_error(url, status, location=None, body=b"error"):
    headers = {"Location": location} if location else {}
    return urllib.error.HTTPError(url, status, "synthetic", headers, io.BytesIO(body))


def test_only_http_https_and_no_link_local(monkeypatch):
    called = []
    monkeypatch.setattr(safe_fetch, "urlopen", lambda *args: called.append(args))
    for url in ("file:///tmp/example.json", "gopher://example.invalid",
                "http://169.254.169.254/latest", "http://user:pass@example.invalid"):
        with pytest.raises(RuntimeError):
            safe_fetch.fetch_json(url)
    assert called == []


def test_local_endpoint_is_allowed(monkeypatch):
    seen = []

    def open_fake(req, timeout):
        seen.append(req)
        return _response({"data": [{"id": "local"}]})

    monkeypatch.setattr(safe_fetch, "urlopen", open_fake)
    result = safe_fetch.fetch_json("http://127.0.0.1:8080/v1/models", api_key="synthetic")
    assert result["data"][0]["id"] == "local"
    assert seen[0].headers["Authorization"] == "Bearer synthetic"


def test_cross_origin_redirect_never_sends_authorization(monkeypatch):
    calls = []

    def open_fake(req, timeout):
        calls.append(req.full_url)
        raise _http_error(req.full_url, 302, "https://evil.invalid/collect")

    monkeypatch.setattr(safe_fetch, "urlopen", open_fake)
    with pytest.raises(RuntimeError, match="重定向"):
        safe_fetch.fetch_json("https://api.invalid/v1/models", api_key="synthetic")
    assert calls == ["https://api.invalid/v1/models"]


def test_https_downgrade_is_rejected(monkeypatch):
    calls = []

    def open_fake(req, timeout):
        calls.append(req.full_url)
        raise _http_error(req.full_url, 301, "http://api.invalid/v1/models")

    monkeypatch.setattr(safe_fetch, "urlopen", open_fake)
    with pytest.raises(RuntimeError, match="重定向"):
        safe_fetch.fetch_json("https://api.invalid/v1/models", api_key="synthetic")
    assert len(calls) == 1


def test_same_origin_redirect_keeps_auth_and_changes_post_to_get(monkeypatch):
    calls = []

    def open_fake(req, timeout):
        calls.append(req)
        if len(calls) == 1:
            raise _http_error(req.full_url, 302, "/v2/chat/completions")
        return _response({"choices": [{"message": {"content": "ok"}}]})

    monkeypatch.setattr(safe_fetch, "urlopen", open_fake)
    result = safe_fetch.fetch_json("https://api.invalid/v1/chat/completions",
                                   payload={"model": "m"}, api_key="synthetic")
    assert result["choices"]
    assert calls[1].get_method() == "GET"
    assert calls[1].data is None
    assert calls[1].headers["Authorization"] == "Bearer synthetic"


def test_response_body_limit(monkeypatch):
    monkeypatch.setattr(safe_fetch, "urlopen",
                        lambda req, timeout: _response(b"123456789"))
    with pytest.raises(RuntimeError, match="上限"):
        safe_fetch.fetch_json("http://local.invalid", max_bytes=8, retries=0)


def test_dripping_response_has_total_deadline(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(safe_fetch.time, "monotonic", lambda: clock[0])

    class Drip:
        def read(self, size=-1):
            clock[0] += 0.6
            return b'{"a":'

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(safe_fetch, "urlopen", lambda req, timeout: Drip())
    with pytest.raises(RuntimeError, match="总时长"):
        safe_fetch.fetch_json("http://local.invalid", timeout=1, retries=0)


def test_429_retries_with_bounded_backoff(monkeypatch):
    calls = []
    sleeps = []

    def open_fake(req, timeout):
        calls.append(req.full_url)
        if len(calls) == 1:
            raise _http_error(req.full_url, 429)
        return _response({"choices": []})

    monkeypatch.setattr(safe_fetch, "urlopen", open_fake)
    result = safe_fetch.fetch_json("http://local.invalid", sleep=sleeps.append)
    assert result == {"choices": []}
    assert len(calls) == 2 and sleeps == [0.5]

    calls.clear()
    sleeps.clear()

    def always_limited(req, timeout):
        calls.append(req.full_url)
        raise _http_error(req.full_url, 429)

    monkeypatch.setattr(safe_fetch, "urlopen", always_limited)
    with pytest.raises(safe_fetch.HTTPStatusError) as error:
        safe_fetch.fetch_json("http://local.invalid", sleep=sleeps.append)
    assert error.value.status == 429
    assert len(calls) == 3 and sleeps == [0.5, 1.0]


@pytest.mark.parametrize("body", [b"\xff", b"<html>error</html>"])
def test_invalid_response_is_runtime_error(monkeypatch, body):
    monkeypatch.setattr(safe_fetch, "urlopen", lambda req, timeout: _response(body))
    with pytest.raises(RuntimeError):
        safe_fetch.fetch_json("http://local.invalid", retries=0)


def test_incomplete_read_is_runtime_error(monkeypatch):
    class Broken:
        def read(self, size=-1):
            raise http.client.IncompleteRead(b"partial")

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(safe_fetch, "urlopen", lambda req, timeout: Broken())
    with pytest.raises(RuntimeError, match="读取响应失败"):
        safe_fetch.fetch_json("http://local.invalid", retries=0)


@pytest.fixture
def local_http_server(monkeypatch):
    import urllib.request
    monkeypatch.setattr(
        safe_fetch, "urlopen",
        lambda req, timeout: urllib.request.build_opener(
            safe_fetch._NoRedirect).open(req, timeout=timeout))
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append((self.path, self.headers.get("Authorization")))
            if self.path == "/redirect":
                self.send_response(302)
                self.send_header("Location", "/final")
                self.end_headers()
                return
            if self.path == "/cross":
                self.send_response(302)
                self.send_header("Location", f"http://localhost:{self.server.server_port}/final")
                self.end_headers()
                return
            body = b'{"data":[{"id":"local-model"}]}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_real_local_same_origin_redirect(local_http_server):
    base, requests = local_http_server
    result = safe_fetch.fetch_json(base + "/redirect", api_key="synthetic", retries=0)
    assert result["data"][0]["id"] == "local-model"
    assert [path for path, _ in requests] == ["/redirect", "/final"]
    assert all(auth == "Bearer synthetic" for _, auth in requests)


def test_real_local_cross_origin_redirect_is_not_followed(local_http_server):
    base, requests = local_http_server
    with pytest.raises(RuntimeError, match="重定向"):
        safe_fetch.fetch_json(base + "/cross", api_key="synthetic", retries=0)
    assert [path for path, _ in requests] == ["/cross"]
