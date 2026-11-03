#!/usr/bin/env python3
"""生成并校验医学治理清单；不调用模型、不读取健康记录。"""
import argparse
import json
import os
import tempfile
from pathlib import Path
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from src.governance import build_decision_inventory, validate_decision_table
from src.paths import REPO_ROOT


def write_inventory(path):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {"schema_version": 1, "status": "pending",
               "entries": build_decision_inventory()}
    with tempfile.NamedTemporaryFile(
            "w", dir=target.parent, prefix=target.name + ".",
            suffix=".tmp", delete=False, encoding="utf-8") as handle:
        temp = handle.name
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    os.replace(temp, target)
    return target


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=os.path.join(
        REPO_ROOT, "governance", "medical_decisions.json"))
    parser.add_argument("--check", action="store_true", help="只校验，不写文件")
    args = parser.parse_args(argv)
    target = Path(args.output)
    if not args.check:
        target = write_inventory(target)
        print(f"已写入 {target}；共 {len(build_decision_inventory())} 项，保持当前实现")
        return 0
    if not target.is_file():
        parser.error(f"清单不存在: {target}")
    with target.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    errors = validate_decision_table(payload.get("entries", []))
    if errors:
        for error in errors:
            print(error, file=os.sys.stderr)
        return 1
    print(f"清单校验通过：{len(payload.get('entries', []))} 项")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
