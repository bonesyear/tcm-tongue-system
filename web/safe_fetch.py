"""受限的 OpenAI 兼容 HTTP 传输；不依赖第三方包。"""
from __future__ import annotations

import http.client
import ipaddress
import json
import math
import socket
import time
import urllib.error
import urllib.request
from urllib.parse import urljoin, urlsplit

MAX_RESPONSE_BYTES = 8 * 1024 * 1024
_REDIRECTS = {301, 302, 303, 307, 308}
_RETRY_STATUSES = {429, 502, 503, 504}


class HTTPStatusError(RuntimeError):
    def __init__(self, status, body):
        self.status = status
        self.body = body
        super().__init__(f"HTTP {status}: {body}")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def urlopen(request, timeout):
    """默认不自动重定向；测试在此替换本地假端点。"""
    return urllib.request.build_opener(_NoRedirect).open(request, timeout=timeout)


def validate_url(url):
    if not isinstance(url, str):
        raise RuntimeError("端点必须是 HTTP(S) URL")
    url = url.strip()
    try:
        parsed = urlsplit(url)
        parsed.port
    except ValueError as error:
        raise RuntimeError("端点 URL 无效") from error
    if parsed.scheme not in ("http", "https") or not parsed.hostname \
            or parsed.username is not None or parsed.password is not None:
        raise RuntimeError("端点只允许不带内嵌凭据的 HTTP(S) URL")
    try:
        address = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        address = None
    if address is not None and address.is_link_local:
        raise RuntimeError("不允许访问链路本地或云元数据地址")
    return url


def same_origin(left, right):
    def origin(url):
        parsed = urlsplit(validate_url(url))
        port = parsed.port or (80 if parsed.scheme == "http" else 443)
        return parsed.scheme, parsed.hostname.rstrip("."), port
    return origin(left) == origin(right)


def _remaining(deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise RuntimeError("请求总时长超限")
    return remaining


def _read_json(response, deadline, max_bytes):
    chunks = []
    size = 0
    while True:
        chunk = response.read(min(65536, max_bytes + 1 - size))
        if not chunk:
            break
        size += len(chunk)
        if size > max_bytes:
            raise RuntimeError(f"响应体超过 {max_bytes} 字节上限")
        chunks.append(chunk)
        _remaining(deadline)
    try:
        text = b"".join(chunks).decode("utf-8")
    except UnicodeDecodeError as error:
        raise RuntimeError("响应不是合法 UTF-8") from error
    try:
        return json.loads(text)
    except json.JSONDecodeError as error:
        raise RuntimeError("invalid JSON（响应不是合法 JSON）") from error


def _redirect(current_url, headers, status, data, method):
    location = headers.get("Location")
    if not location:
        raise RuntimeError(f"HTTP {status} 重定向缺少 Location")
    target = validate_url(urljoin(current_url, location))
    if not same_origin(current_url, target):
        raise RuntimeError("拒绝跨源或 HTTPS 降级重定向")
    if status in (301, 302, 303) and method == "POST":
        return target, None, "GET"
    return target, data, method


def _request_json(url, payload, api_key, method, deadline, max_bytes):
    data = None if payload is None else json.dumps(payload).encode()
    for _ in range(4):
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        if data is not None:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            response = urlopen(req, timeout=_remaining(deadline))
        except urllib.error.HTTPError as error:
            if error.code in _REDIRECTS:
                url, data, method = _redirect(
                    url, error.headers or {}, error.code, data, method)
                continue
            _remaining(deadline)
            try:
                body = error.read(201).decode("utf-8", errors="replace")[:200]
            except (OSError, http.client.HTTPException):
                body = str(error.reason)
            raise HTTPStatusError(error.code, body) from error
        except (urllib.error.URLError, socket.timeout, TimeoutError,
                http.client.HTTPException, OSError) as error:
            raise RuntimeError(f"请求失败: {error}") from error
        status = getattr(response, "status", 200)
        if status in _REDIRECTS:
            headers = getattr(response, "headers", {}) or {}
            response.close()
            url, data, method = _redirect(url, headers, status, data, method)
            continue
        try:
            with response:
                return _read_json(response, deadline, max_bytes)
        except (urllib.error.URLError, socket.timeout, TimeoutError,
                http.client.HTTPException, OSError) as error:
            raise RuntimeError(f"读取响应失败: {error}") from error
    raise RuntimeError("重定向次数过多")


def fetch_json(url, *, payload=None, api_key="", method=None, timeout=30,
               max_bytes=MAX_RESPONSE_BYTES, retries=2, sleep=None):
    """返回解析后的 JSON；网络、限量和协议失败统一为 RuntimeError。"""
    url = validate_url(url)
    try:
        timeout = float(timeout)
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError
        if not isinstance(max_bytes, int) or max_bytes <= 0:
            raise ValueError
        if retries not in (0, 1, 2):
            raise ValueError
    except (TypeError, ValueError) as error:
        raise RuntimeError("超时、响应上限或重试次数配置无效") from error
    method = method or ("POST" if payload is not None else "GET")
    deadline = time.monotonic() + timeout
    sleep = sleep or time.sleep
    for attempt in range(retries + 1):
        try:
            return _request_json(url, payload, api_key, method, deadline, max_bytes)
        except HTTPStatusError as error:
            if error.status not in _RETRY_STATUSES or attempt == retries:
                raise
            delay = min(0.5 * (2 ** attempt),
                        max(0, deadline - time.monotonic()))
            sleep(delay)
            _remaining(deadline)
