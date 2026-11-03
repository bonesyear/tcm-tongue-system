#!/usr/bin/env python3
"""路径配置模块(Paths module)
================================

集中定义仓库内数据目录,消除 scripts/ 各自硬编码绝对路径
(原 `/root/tcm-tongue-system/...` 仅在部署机存在,任何其他机器上
import 即崩)。

解析规则:
    REPO_ROOT   由本文件位置上溯一级得到(src/ 的父目录)
    DATA_ROOT   由 TCM_DATA_ROOT 解析而来(B02 规则,按序匹配):
                1. 未设置或 strip 后为空白串 → REPO_ROOT(行为不变);
                2. 绝对路径 → 原样使用(仅 normpath 清理分隔符);
                3. 相对路径 → 解释为相对 REPO_ROOT——消除旧实现
                   「相对运行时 cwd」的隐式依赖(同一脚本换目录执行
                   结果就漂),规则一处写清、可预测。
    RECORDS_DAILY_DIR / RECORDS_WEEKLY_DIR / CHARTS_DIR 均在 DATA_ROOT 下

约束:本模块 import 零副作用——目录创建(os.makedirs)只由调用方在
运行入口显式调用 ensure_data_dirs() 完成,不得在 import 时执行。
"""

import os

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _resolve_data_root() -> str:
    """按文档声明的三条规则解析 TCM_DATA_ROOT → DATA_ROOT。"""
    raw = os.environ.get("TCM_DATA_ROOT")
    cleaned = raw.strip() if raw else ""
    if not cleaned:
        return REPO_ROOT
    if os.path.isabs(cleaned):
        return os.path.normpath(cleaned)
    return os.path.join(REPO_ROOT, cleaned)


# 数据根目录:部署机可用 TCM_DATA_ROOT 指到别处(如 /root/tcm-tongue-system)
DATA_ROOT = _resolve_data_root()

RECORDS_DAILY_DIR = os.path.join(DATA_ROOT, "records", "daily")
RECORDS_WEEKLY_DIR = os.path.join(DATA_ROOT, "records", "weekly")
CHARTS_DIR = os.path.join(DATA_ROOT, "charts")

# 文档配图输出目录(始终在仓库内,与数据目录无关)
DOCS_IMAGES_DIR = os.path.join(REPO_ROOT, "docs", "images")


def ensure_data_dirs() -> None:
    """创建数据输出目录(幂等)。仅应在脚本 main() 中调用。"""
    for d in (RECORDS_DAILY_DIR, RECORDS_WEEKLY_DIR, CHARTS_DIR):
        os.makedirs(d, exist_ok=True)
