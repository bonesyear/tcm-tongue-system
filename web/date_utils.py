"""小日期接口：合法性解析与不会抛溢出的边界计算。"""
from __future__ import annotations

import datetime
import re


def parse_date(value):
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    if not isinstance(value, str):
        return None
    try:
        return datetime.date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def parse_month(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}", value):
        return None
    return parse_date(value + "-01")


def add_days(value, days):
    value = parse_date(value)
    if value is None:
        return None
    try:
        return value + datetime.timedelta(days=days)
    except (OverflowError, ValueError):
        return None


def add_month(value, months):
    if isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}", value):
        value = parse_month(value)
    else:
        value = parse_date(value)
    if value is None:
        return None
    total = value.year * 12 + value.month - 1 + months
    year, month = divmod(total, 12)
    if not 1 <= year <= 9999:
        return None
    return datetime.date(year, month + 1, 1)
