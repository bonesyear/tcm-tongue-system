"""Paths module 测试：TCM_DATA_ROOT 解析规则（B02）。

src.paths 在 import 时读取环境变量，因此用例内 importlib.reload 刷新
模块级常量；fixture 负责测试后恢复环境并 reload 回默认状态，
避免污染同进程的其他测试。
"""
import importlib
import os

import pytest

import src.paths as paths


@pytest.fixture
def paths_env():
    saved = os.environ.get("TCM_DATA_ROOT")
    yield os.environ
    if saved is None:
        os.environ.pop("TCM_DATA_ROOT", None)
    else:
        os.environ["TCM_DATA_ROOT"] = saved
    importlib.reload(paths)


def test_default_data_root_is_repo_root(paths_env):
    os.environ.pop("TCM_DATA_ROOT", None)
    mod = importlib.reload(paths)
    assert mod.DATA_ROOT == mod.REPO_ROOT
    assert mod.RECORDS_DAILY_DIR == os.path.join(
        mod.REPO_ROOT, "records", "daily")
    assert mod.CHARTS_DIR == os.path.join(mod.REPO_ROOT, "charts")


def test_whitespace_only_data_root_falls_back_to_repo_root(paths_env):
    """全空白（含纯空格/制表）等同未设置——旧实现 `or REPO_ROOT` 把
    空白字符串当真值，DATA_ROOT 会变成不可用的相对目录。"""
    for blank in ("", "   ", "\t \n"):
        os.environ["TCM_DATA_ROOT"] = blank
        mod = importlib.reload(paths)
        assert mod.DATA_ROOT == mod.REPO_ROOT, f"空白值 {blank!r} 应回退"


def test_absolute_data_root_is_used(paths_env, tmp_path):
    os.environ["TCM_DATA_ROOT"] = str(tmp_path)
    mod = importlib.reload(paths)
    assert mod.DATA_ROOT == os.path.normpath(str(tmp_path))
    assert mod.RECORDS_WEEKLY_DIR == os.path.join(
        os.path.normpath(str(tmp_path)), "records", "weekly")


def test_relative_data_root_anchors_to_repo_root(paths_env):
    """相对路径解释为相对 REPO_ROOT（消除对 cwd 的隐式依赖——
    旧实现相对路径锚定运行时的 cwd，同一脚本换目录执行结果就漂）。"""
    os.environ["TCM_DATA_ROOT"] = "data"
    mod = importlib.reload(paths)
    assert mod.DATA_ROOT == os.path.join(mod.REPO_ROOT, "data")
    # 带首尾空白的相对路径同样先 strip 再锚定
    os.environ["TCM_DATA_ROOT"] = "  data2  "
    mod = importlib.reload(paths)
    assert mod.DATA_ROOT == os.path.join(mod.REPO_ROOT, "data2")


def test_docs_images_dir_always_in_repo(paths_env, tmp_path):
    """docs 配图目录与数据根无关：即使数据根外置也在仓库内。"""
    os.environ["TCM_DATA_ROOT"] = str(tmp_path)
    mod = importlib.reload(paths)
    assert mod.DOCS_IMAGES_DIR == os.path.join(
        mod.REPO_ROOT, "docs", "images")
