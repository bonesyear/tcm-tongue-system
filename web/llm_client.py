"""辨证 LLM 客户端（OpenAI 兼容端点，纯 urllib，零第三方依赖）。

与 scripts/vision_client.py 同风格：模型/端点/Key 全部走配置，可插拔。
配置键：LLM_MODEL / LLM_BASE_URL / LLM_API_KEY（见 web 设置页或 .env）。
本模块切片 1 只用于连通性测试；报告生成在切片 5 接入。
"""
from __future__ import annotations

import json
import socket
import sys
import time
import urllib.error
import urllib.request

WARN_PREFIX = "[web][llm_client][warn]"


def normalize_chat_url(url: str) -> str:
    """规整为 chat/completions 完整地址。

    只填到 /v1（或带尾斜杠）是常见误填（实测 404），此处自动补上
    /chat/completions 并打 stderr 提示——可诊断，不静默。
    """
    u = (url or "").strip().rstrip("/")
    if u and not u.endswith("/chat/completions"):
        print(f"{WARN_PREFIX} 端点 {u!r} 缺少 /chat/completions 后缀，"
              f"已自动补齐；建议把配置改全", file=sys.stderr)
        u += "/chat/completions"
    return u


def _models_url(base_url: str) -> str:
    """从 chat/completions 完整地址推导 /models 地址。"""
    u = base_url.rstrip("/")
    if u.endswith("/chat/completions"):
        u = u[: -len("/chat/completions")]
    return u + "/models"


def list_models(base_url: str, api_key: str, timeout: int = 30) -> list:
    """GET <base>/models，返回模型 id 列表（OpenAI 兼容）。失败抛 RuntimeError。"""
    if not (base_url and api_key):
        raise RuntimeError("端点或 API Key 未配置")
    req = urllib.request.Request(_models_url(base_url),
                                 headers={"Authorization": f"Bearer {api_key}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode(errors="replace")[:200]
        except Exception:
            pass
        raise RuntimeError(f"模型列表 HTTP {e.code}: {body}") from e
    except (urllib.error.URLError, socket.timeout, TimeoutError) as e:
        raise RuntimeError(f"模型列表请求失败: {e}") from e
    except json.JSONDecodeError as e:
        raise RuntimeError(f"模型列表返回非 JSON: {e}") from e
    ids = [m.get("id") for m in data.get("data", []) if m.get("id")]
    if not ids:
        raise RuntimeError(f"端点未返回模型列表: {str(data)[:200]}")
    return sorted(ids)


def ping(model: str, base_url: str, api_key: str, timeout: int = 30) -> float:
    """发一条最小对话验证连通性，返回耗时秒数。失败抛 RuntimeError。

    只验证「端点应答且返回 choices」——不检查 content 非空：思考型模型
    的思考过程可能占满 max_tokens 导致正文为空，端点本身仍是连通的。
    """
    if not (model and base_url and api_key):
        raise RuntimeError("辨证模型未配置完整（LLM_MODEL / LLM_BASE_URL / LLM_API_KEY）")
    base_url = normalize_chat_url(base_url)
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "只回复两个字：正常"}],
        "max_tokens": 512,  # 给思考型模型留思考额度，避免误判不连通
    }
    req = urllib.request.Request(
        base_url, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {api_key}"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode(errors="replace")[:200]
        except Exception:
            pass
        raise RuntimeError(f"LLM API HTTP {e.code}: {body}") from e
    except (urllib.error.URLError, socket.timeout, TimeoutError) as e:
        raise RuntimeError(f"LLM API 请求失败: {e}") from e
    except json.JSONDecodeError as e:
        raise RuntimeError(f"LLM API 返回非 JSON: {e}") from e
    if not data.get("choices"):
        raise RuntimeError(f"LLM API 响应缺少 choices: {str(data)[:200]}")
    return round(time.time() - t0, 1)


def chat(user: str, system: str, model: str, base_url: str, api_key: str,
         timeout: int = 150, max_tokens: int = 4000) -> str:
    """一次对话调用，返回正文文本。失败抛 RuntimeError。"""
    if not (model and base_url and api_key):
        raise RuntimeError("辨证模型未配置完整（LLM_MODEL / LLM_BASE_URL / LLM_API_KEY）")
    base_url = normalize_chat_url(base_url)
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": user})
    payload = {"model": model, "messages": messages, "max_tokens": max_tokens}
    req = urllib.request.Request(
        base_url, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {api_key}"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode(errors="replace")[:200]
        except Exception:
            pass
        raise RuntimeError(f"LLM API HTTP {e.code}: {body}") from e
    except (urllib.error.URLError, socket.timeout, TimeoutError) as e:
        raise RuntimeError(f"LLM API 请求失败: {e}") from e
    except json.JSONDecodeError as e:
        raise RuntimeError(f"LLM API 返回非 JSON: {e}") from e
    choices = data.get("choices")
    if not choices:
        raise RuntimeError(f"LLM API 响应缺少 choices: {str(data)[:200]}")
    content = (choices[0].get("message", {}) or {}).get("content") or ""
    if choices[0].get("finish_reason") == "length":
        # 截断输出不可用（辨证报告写一半等于没写）——失败要可诊断，不静默存档
        raise RuntimeError(
            "LLM 输出被截断（finish_reason=length）：报告不完整。"
            "请提高 max_tokens（当前 %d，建议 ≥8000；思考型模型的"
            "推理过程也占该额度）" % max_tokens)
    if not content.strip():
        raise RuntimeError("LLM 返回空内容（思考型模型可能吃满 max_tokens 额度）")
    return content
