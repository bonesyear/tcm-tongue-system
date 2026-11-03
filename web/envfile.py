"""项目根 .env 的读写（Web 设置页的唯一存储）。

读取使用严格 UTF-8（允许起始 BOM）；写入保留原有行与注释，
键和值经过校验，特殊字符以双引号及转义保存，并回读核对。
"""
from __future__ import annotations

import json
import os
import re


class EnvDecodeError(Exception):
    """配置无法解码或引号格式不完整，可由用户修复。"""


_KEY_RE = re.compile(r"^[A-Z_][A-Z0-9_]*$")
_LINE_BREAKS = "\r\n\0\v\f\x1c\x1d\x1e\x85\u2028\u2029"


def _decode(raw: bytes, path: str) -> str:
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise EnvDecodeError(
            f"读取 {path} 失败：第 {error.start} 字节不是合法 UTF-8"
            "（该文件可能由其他编码如 GBK 保存，请转为 UTF-8 后重试）") from error


def _quoted_value(text: str, path: str):
    if text.startswith('"'):
        try:
            value, end = json.JSONDecoder().raw_decode(text)
        except json.JSONDecodeError as error:
            raise EnvDecodeError(f"解析 {path} 失败：双引号或转义不完整") from error
    else:
        end = text.find("'", 1)
        if end < 0:
            raise EnvDecodeError(f"解析 {path} 失败：单引号未闭合")
        value = text[1:end]
        end += 1
    trailing = text[end:]
    if trailing.strip() and not re.match(r"\s+#", trailing):
        raise EnvDecodeError(f"解析 {path} 失败：引号后存在无法识别的内容")
    return value


def _value(text: str, path: str):
    stripped = text.lstrip()
    if stripped.startswith(('"', "'")):
        return _quoted_value(stripped, path)
    return re.split(r"\s+#", text, maxsplit=1)[0].strip()


def parse_env(text: str, path: str = "<env>") -> dict:
    """解析文本；供严格 Web 读取与带告警的 CLI 读取共用。"""
    out = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, raw_value = line.split("=", 1)
        key = key.strip()
        if key and key not in out:
            out[key] = _value(raw_value, path)
    return out


def read_env(path: str) -> dict:
    """读取配置；不存在返回 {}，首个重复键生效。"""
    try:
        with open(path, "rb") as file:
            text = _decode(file.read(), path)
    except FileNotFoundError:
        return {}
    return parse_env(text, path)


def _validate(key, value):
    if not isinstance(key, str) or not _KEY_RE.fullmatch(key):
        raise ValueError(f".env 键名无效: {key!r}")
    if not isinstance(value, str):
        raise ValueError(f".env {key} 的值必须是字符串")
    if any(char in value for char in _LINE_BREAKS):
        raise ValueError(f".env {key} 不得包含换行或 NUL 字符")


def _format_value(value: str) -> str:
    if any(char.isspace() or not char.isprintable()
           or char in ('#', '\\', '"', "'") for char in value):
        return json.dumps(value, ensure_ascii=False)
    return value


def write_env(path: str, updates: dict) -> None:
    """更新指定键；None 表示不修改，空字符串表示显式置空。"""
    for key, value in updates.items():
        if value is not None:
            _validate(key, value)
    updates = {key: value for key, value in updates.items() if value is not None}
    if not updates:
        return
    try:
        with open(path, "rb") as file:
            text = _decode(file.read(), path)
    except FileNotFoundError:
        text = ""
    lines = text.splitlines()
    remaining = dict(updates)
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key = stripped.split("=", 1)[0].strip()
        if key in remaining:
            lines[index] = f"{key}={_format_value(remaining.pop(key))}"
    for key, value in remaining.items():
        lines.append(f"{key}={_format_value(value)}")
    try:
        from .io_utils import atomic_write_text
    except ImportError:
        from io_utils import atomic_write_text
    atomic_write_text(path, "\n".join(lines) + "\n")
    actual = read_env(path)
    for key, value in updates.items():
        if actual.get(key) != value:
            raise RuntimeError(f".env {key} 写入后回读不一致")


def effective(key: str, env_file: str, default: str = "") -> str:
    """生效值 = 非空环境变量优先，其次 .env。"""
    return os.environ.get(key) or read_env(env_file).get(key) or default
