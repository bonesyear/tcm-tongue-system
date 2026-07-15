"""pytest 共享配置：把仓库根与 scripts/ 加入 import 路径。

仓库根入 sys.path → 测试与 README 一致地使用 `from src.record import ...`；
scripts/ 入 sys.path → 可直接 `import generate_weekly_report` 做集成测试。
"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SCRIPTS = os.path.join(_ROOT, "scripts")
for p in (_ROOT, _SCRIPTS):
    if p not in sys.path:
        sys.path.insert(0, p)
