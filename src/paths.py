#!/usr/bin/env python3
"""路径配置模块(Paths module)
================================

集中定义仓库内数据目录,消除 scripts/ 各自硬编码绝对路径
(原 `/root/tcm-tongue-system/...` 仅在部署机存在,任何其他机器上
import 即崩,见 docs/CODE_REVIEW_2026-07-12.md Bug 1/3)。

解析规则:
    REPO_ROOT   由本文件位置上溯一级得到(src/ 的父目录)
    DATA_ROOT   环境变量 TCM_DATA_ROOT 优先,否则等于 REPO_ROOT
    RECORDS_DAILY_DIR / RECORDS_WEEKLY_DIR / CHARTS_DIR 均在 DATA_ROOT 下

约束:本模块 import 零副作用——目录创建(os.makedirs)只由调用方在
运行入口显式调用 ensure_data_dirs() 完成,不得在 import 时执行。
"""

import os

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 数据根目录:部署机可用 TCM_DATA_ROOT 指到别处(如 /root/tcm-tongue-system)
DATA_ROOT = os.environ.get("TCM_DATA_ROOT") or REPO_ROOT

RECORDS_DAILY_DIR = os.path.join(DATA_ROOT, "records", "daily")
RECORDS_WEEKLY_DIR = os.path.join(DATA_ROOT, "records", "weekly")
CHARTS_DIR = os.path.join(DATA_ROOT, "charts")

# 文档配图输出目录(始终在仓库内,与数据目录无关)
DOCS_IMAGES_DIR = os.path.join(REPO_ROOT, "docs", "images")


def ensure_data_dirs() -> None:
    """创建数据输出目录(幂等)。仅应在脚本 main() 中调用。"""
    for d in (RECORDS_DAILY_DIR, RECORDS_WEEKLY_DIR, CHARTS_DIR):
        os.makedirs(d, exist_ok=True)
