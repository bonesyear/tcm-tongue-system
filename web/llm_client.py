"""辨证 LLM 客户端（OpenAI 兼容端点，纯 urllib，零第三方依赖）。

与 scripts/vision_client.py 同风格：模型/端点/Key 全部走配置，可插拔。
配置键：LLM_MODEL / LLM_BASE_URL / LLM_API_KEY（见 web 设置页或 .env）。
本模块切片 1 只用于连通性测试；报告生成在切片 5 接入。
"""
from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.request

WARN_PREFIX = "[web][llm_client][warn]"


def ping(model: str, base_url: str, api_key: str, timeout: int = 30) -> float:
    """发一条最小对话验证连通性，返回耗时秒数。失败抛 RuntimeError。"""
    if not (model and base_url and api_key):
        raise RuntimeError("辨证模型未配置完整（LLM_MODEL / LLM_BASE_URL / LLM_API_KEY）")
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "只回复两个字：正常"}],
        "max_tokens": 16,
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
