#!/usr/bin/env python3
"""在全新虚拟环境验证 Web 依赖能提供配置所需的 IANA 时区。

运行：python tests/deployment/timezone_clean_env.py
依赖安装可访问包索引，但不读取真实配置、健康记录，也不调用模型。
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import venv


ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / ".timezone-tmp" / f"clean-env-{os.getpid()}"


def run(command, **kwargs):
    return subprocess.run(command, text=True, encoding="utf-8", errors="replace",
                          capture_output=True, timeout=240, **kwargs)


def main():
    env_dir = WORK / "venv"
    data = WORK / "data"
    tzpath = WORK / "empty-tzpath"
    for directory in (data / "records" / "daily", data / "records" / "photos", tzpath):
        directory.mkdir(parents=True, exist_ok=True)
    env_file = WORK / "isolated.env"
    env_file.write_text(
        "VISION_DISABLED=1\nLLM_DISABLED=1\nTCM_TIMEZONE=Asia/Shanghai\n",
        encoding="utf-8")

    venv.EnvBuilder(with_pip=True, clear=False).create(env_dir)
    python = env_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    installed = run([
        str(python), "-m", "pip", "install", "--no-input",
        "--disable-pip-version-check", "--default-timeout=60", "--retries=2",
        "-r", str(ROOT / "web" / "requirements.txt"),
    ], cwd=ROOT)
    if installed.returncode:
        raise AssertionError(
            f"干净环境依赖安装失败：\n{installed.stdout}\n{installed.stderr}")

    child_env = {
        key: value for key, value in os.environ.items()
        if not key.startswith(("VISION_", "LLM_", "WEB_", "TCM_"))
        and key != "DASHSCOPE_API_KEY"
    }
    child_env.update({
        "HOME": str(WORK / "home"),
        "USERPROFILE": str(WORK / "home"),
        "PYTHONTZPATH": str(tzpath),
        "PYTHONUTF8": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
    })
    (WORK / "home").mkdir(exist_ok=True)
    probe = r'''
import datetime
import json
import sys
from importlib.metadata import version
from pathlib import Path
from zoneinfo import ZoneInfo

root = Path(sys.argv[1])
data = Path(sys.argv[2])
env_file = Path(sys.argv[3])
sys.path[:0] = [str(root), str(root / "web")]

zone = ZoneInfo("Asia/Shanghai")
assert zone.key == "Asia/Shanghai"
import time_utils
configured = time_utils.timezone("Asia/Shanghai")
assert getattr(configured, "key", None) == "Asia/Shanghai", configured
timestamp = time_utils.iso_now("Asia/Shanghai")
assert timestamp.endswith("+08:00"), timestamp
assert time_utils.now("Asia/Shanghai").utcoffset() == datetime.timedelta(hours=8)

from app import create_app
import wizard_store
app = create_app(env_file=str(env_file), data_root=str(data))
app.config["TESTING"] = True
client = app.test_client()
welcome = client.post("/welcome", headers={"Origin": "http://localhost"})
assert welcome.status_code in (200, 302), welcome.status_code
wizard = client.get("/wizard")
assert wizard.status_code == 200, wizard.status_code
today = time_utils.today("Asia/Shanghai").isoformat()
assert today in wizard.get_data(as_text=True)
draft = {"date": today, "parts": {
    part["part"]: {"status": "skip_uncovered"} for part in wizard_store.PARTS}}
record = wizard_store.assemble_record(
    draft, "clean-env", timezone_name="Asia/Shanghai")
assert record["timestamp"].endswith("+08:00"), record["timestamp"]
print(json.dumps({
    "result": "CLEAN_TIMEZONE_OK",
    "tzdata_version": version("tzdata"),
    "configured_zone": configured.key,
    "offset": timestamp[-6:],
    "wizard_http": wizard.status_code,
    "record_timestamp_has_configured_offset": True,
}, ensure_ascii=False))
'''
    checked = run([
        str(python), "-c", probe, str(ROOT), str(data), str(env_file),
    ], cwd=ROOT, env=child_env)
    if checked.returncode:
        raise AssertionError(
            "干净环境未能使用配置时区；当前依赖声明不完整：\n"
            f"{checked.stdout}\n{checked.stderr}")
    assert "无效 TCM_TIMEZONE" not in checked.stderr, checked.stderr
    print(checked.stdout.strip())


if __name__ == "__main__":
    try:
        main()
    finally:
        shutil.rmtree(WORK, ignore_errors=True)
        try:
            WORK.parent.rmdir()
        except OSError:
            pass
