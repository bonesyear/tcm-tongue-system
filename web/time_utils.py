"""本地日期与带偏移时间戳；时区使用标准库 ZoneInfo。"""
from __future__ import annotations

import datetime
import os
import sys
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def timezone(name=None):
    name = name or os.environ.get("TCM_TIMEZONE")
    if name:
        try:
            return ZoneInfo(name)
        except (ZoneInfoNotFoundError, ValueError) as error:
            print(f"⚠️ 警告: 无效 TCM_TIMEZONE {name!r}，回退系统时区: {error}",
                  file=sys.stderr)
    return datetime.datetime.now().astimezone().tzinfo


def now(name=None):
    return datetime.datetime.now(timezone(name))


def today(name=None):
    return now(name).date()


def iso_now(name=None):
    return now(name).isoformat(timespec="seconds")
