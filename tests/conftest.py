"""pytest 共享导入路径、环境隔离与敏感文件访问边界。"""
import os
import sys
import tempfile

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SCRIPTS = os.path.join(_ROOT, "scripts")
for p in (_ROOT, _SCRIPTS, os.path.join(_ROOT, "web")):
    if p not in sys.path:
        sys.path.insert(0, p)

from src import paths


def _inside_temp(path, tmp_path):
    target = os.path.abspath(os.fspath(path))
    roots = (os.path.abspath(str(tmp_path)), os.path.abspath(tempfile.gettempdir()))
    return any(target == root or target.startswith(root + os.sep) for root in roots)


@pytest.fixture(autouse=True)
def isolate_test_environment(tmp_path, monkeypatch):
    """每个测试都用独立数据根、HOME 和配置；越界访问直接失败。"""
    for name in list(os.environ):
        if name.startswith(("VISION_", "LLM_", "WEB_", "TCM_")) \
                or name == "DASHSCOPE_API_KEY":
            monkeypatch.delenv(name, raising=False)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    data_root = tmp_path / "data"
    monkeypatch.setenv("TCM_DATA_ROOT", str(data_root))
    monkeypatch.setenv("TCM_KB_ROOT", os.path.join(
        _ROOT, "tests", "fixtures", "knowledge_base"))
    monkeypatch.setenv("TCM_KB_ALLOW_EXTERNAL_KB", "1")
    daily = data_root / "records" / "daily"
    weekly = data_root / "records" / "weekly"
    charts = data_root / "charts"
    monkeypatch.setattr(paths, "DATA_ROOT", str(data_root))
    monkeypatch.setattr(paths, "RECORDS_DAILY_DIR", str(daily))
    monkeypatch.setattr(paths, "RECORDS_WEEKLY_DIR", str(weekly))
    monkeypatch.setattr(paths, "CHARTS_DIR", str(charts))
    weekly_module = sys.modules.get("generate_weekly_report")
    if weekly_module is not None:
        monkeypatch.setattr(weekly_module, "RECORDS_DIR", str(daily))
        monkeypatch.setattr(weekly_module, "WEEKLY_DIR", str(weekly))
        monkeypatch.setattr(weekly_module, "CHARTS_DIR", str(charts))

    import envfile
    import safe_fetch
    import vision_client

    original_read = envfile.read_env
    original_write = envfile.write_env
    original_vision_read = vision_client._read_env_text

    def checked_read(path):
        if not _inside_temp(path, tmp_path):
            raise PermissionError(f"测试禁止读取临时目录外的配置: {path}")
        return original_read(path)

    def checked_write(path, updates):
        if not _inside_temp(path, tmp_path):
            raise PermissionError(f"测试禁止写入临时目录外的配置: {path}")
        return original_write(path, updates)

    def checked_vision_read(path):
        if not _inside_temp(path, tmp_path):
            raise FileNotFoundError(path)
        return original_vision_read(path)

    def reject_unmocked_http(req, timeout):
        raise RuntimeError("测试禁止未 mock 的 HTTP 请求")

    monkeypatch.setattr(envfile, "read_env", checked_read)
    monkeypatch.setattr(envfile, "write_env", checked_write)
    monkeypatch.setattr(vision_client, "_read_env_text", checked_vision_read)
    monkeypatch.setattr(safe_fetch, "urlopen", reject_unmocked_http)
    yield tmp_path
