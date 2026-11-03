"""知识库配置事务的精确快照与恢复工具。"""
from __future__ import annotations

import os

from io_utils import atomic_write_bytes


def read_config_bytes(path):
    try:
        with open(path, "rb") as handle:
            return handle.read()
    except FileNotFoundError:
        return None


def restore_config_bytes(path, expected):
    if read_config_bytes(path) == expected:
        return
    if expected is None:
        if os.path.exists(path):
            os.unlink(path)
        return
    atomic_write_bytes(path, expected)
