"""辨证 LLM 客户端（OpenAI 兼容端点，纯标准库）。"""
from __future__ import annotations

import sys
import time

from safe_fetch import HTTPStatusError, fetch_json

WARN_PREFIX = "[web][llm_client][warn]"


def normalize_chat_url(url: str) -> str:
    """规整为 chat/completions 完整地址并保留可诊断提示。"""
    url = (url or "").strip().rstrip("/")
    if url and not url.endswith("/chat/completions"):
        print(f"{WARN_PREFIX} 端点 {url!r} 缺少 /chat/completions 后缀，"
              "已自动补齐；建议把配置改全", file=sys.stderr)
        url += "/chat/completions"
    return url


def _models_url(base_url: str) -> str:
    base_url = base_url.rstrip("/")
    if base_url.endswith("/chat/completions"):
        base_url = base_url[:-len("/chat/completions")]
    return base_url + "/models"


def _request_json(label, url, *, payload=None, api_key, timeout):
    try:
        return fetch_json(url, payload=payload, api_key=api_key, timeout=timeout)
    except HTTPStatusError as error:
        raise RuntimeError(f"{label} HTTP {error.status}: {error.body}") from error
    except RuntimeError as error:
        raise RuntimeError(f"{label} 请求失败: {error}") from error


def _first_choice(data, label):
    if not isinstance(data, dict):
        raise RuntimeError(f"{label} 响应顶层必须是对象")
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise RuntimeError(f"{label} 响应缺少有效 choices")
    return choices[0]


def _content(choice, label):
    message = choice.get("message")
    if not isinstance(message, dict):
        raise RuntimeError(f"{label} 响应缺少有效 message")
    content = message.get("content")
    if content is None:
        return ""
    if isinstance(content, list):
        content = "".join(part.get("text", "") for part in content
                          if isinstance(part, dict) and part.get("type") == "text"
                          and isinstance(part.get("text"), str))
    if not isinstance(content, str):
        raise RuntimeError(f"{label} content 类型不支持")
    return content


def list_models(base_url: str, api_key: str, timeout: int = 30) -> list:
    """GET <base>/models，返回模型 id 列表。失败抛 RuntimeError。"""
    if not (base_url and api_key):
        raise RuntimeError("端点或 API Key 未配置")
    data = _request_json("模型列表", _models_url(base_url), api_key=api_key,
                         timeout=timeout)
    if not isinstance(data, dict) or not isinstance(data.get("data"), list):
        raise RuntimeError("模型列表响应缺少 data 数组")
    ids = sorted(item["id"].strip() for item in data["data"]
                 if isinstance(item, dict) and isinstance(item.get("id"), str)
                 and item["id"].strip())
    if not ids:
        raise RuntimeError("端点未返回有效模型 ID")
    return ids


def ping(model: str, base_url: str, api_key: str, timeout: int = 30) -> float:
    """发一条最小对话验证连通性，返回耗时秒数。"""
    if not (model and base_url and api_key):
        raise RuntimeError("辨证模型未配置完整（LLM_MODEL / LLM_BASE_URL / LLM_API_KEY）")
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "只回复两个字：正常"}],
        "max_tokens": 512,
    }
    started = time.monotonic()
    data = _request_json("LLM API", normalize_chat_url(base_url), payload=payload,
                         api_key=api_key, timeout=timeout)
    _first_choice(data, "LLM API")
    return round(time.monotonic() - started, 1)


def chat(user: str, system: str, model: str, base_url: str, api_key: str,
         timeout: int = 150, max_tokens: int = 4000) -> str:
    """一次对话调用，返回正文文本。失败抛 RuntimeError。"""
    if not (model and base_url and api_key):
        raise RuntimeError("辨证模型未配置完整（LLM_MODEL / LLM_BASE_URL / LLM_API_KEY）")
    if not isinstance(max_tokens, int) or max_tokens <= 0:
        raise RuntimeError("max_tokens 必须是正整数")
    messages = ([{"role": "system", "content": system}] if system else [])
    messages.append({"role": "user", "content": user})
    payload = {"model": model, "messages": messages, "max_tokens": max_tokens}
    data = _request_json("LLM API", normalize_chat_url(base_url), payload=payload,
                         api_key=api_key, timeout=timeout)
    choice = _first_choice(data, "LLM API")
    content = _content(choice, "LLM API")
    if choice.get("finish_reason") == "length":
        raise RuntimeError(
            "LLM 输出被截断（finish_reason=length）：报告不完整。"
            f"请提高 max_tokens（当前 {max_tokens}，建议 ≥8000；"
            "思考型模型的推理过程也占该额度）")
    if not content.strip():
        raise RuntimeError("LLM 返回空内容（思考型模型可能吃满 max_tokens 额度）")
    return content
