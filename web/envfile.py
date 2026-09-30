"""项目根 .env 的读写（Web 设置页的唯一存储）。

读：与 scripts/vision_client.py 的 _read_env_text 同语义——原始 bytes →
严格 UTF-8（不依赖平台默认编码），失败抛 EnvDecodeError 由 UI 呈现，
不用平台默认编码重开文件。
写：保留既有行与注释，原地更新已存在的键、追加新键，一律 UTF-8 落盘。
"""
from __future__ import annotations

import io
import os


class EnvDecodeError(Exception):
    """.env 含非 UTF-8 字节：携带可行动的错误信息（哪个文件、哪一字节）。"""


def read_env(path: str) -> dict:
    """读 .env 为 {键: 值}。文件不存在返回 {}。非 UTF-8 抛 EnvDecodeError。"""
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except FileNotFoundError:
        return {}
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as e:
        raise EnvDecodeError(
            f"读取 {path} 失败：第 {e.start} 字节不是合法 UTF-8"
            f"（该文件可能由其他编码如 GBK 保存，请转为 UTF-8 后重试）") from e
    out = {}
    for line in io.StringIO(text, newline=None):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.split("#", 1)[0].strip().strip('"').strip("'")
        if k and k not in out:
            out[k] = v
    return out


def write_env(path: str, updates: dict) -> None:
    """把 updates 写进 .env：已存在的键原地替换整行，新键追加到末尾。

    updates 里值为 None 的键表示「不修改」（留空密码框的语义）；
    值为空字符串表示「显式置空」（写成 KEY=，用于清除可选项）。
    """
    updates = {k: v for k, v in updates.items() if v is not None}
    if not updates:
        return
    try:
        with open(path, "rb") as f:
            text = f.read().decode("utf-8")
    except FileNotFoundError:
        text = ""
    lines = text.splitlines()
    remaining = dict(updates)
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        k = stripped.split("=", 1)[0].strip()
        if k in remaining:
            lines[i] = f"{k}={remaining.pop(k)}"
    for k, v in remaining.items():
        lines.append(f"{k}={v}")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")


def effective(key: str, env_file: str, default: str = "") -> str:
    """生效值 = 环境变量优先，其次 .env（与 vision_client 的优先级一致）。"""
    return os.environ.get(key) or read_env(env_file).get(key) or default
