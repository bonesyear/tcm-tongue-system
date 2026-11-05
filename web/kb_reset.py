"""分类知识库重置；只处理程序管理的导入副本，不触碰外部原库。"""
from __future__ import annotations

import os
import shutil
import uuid

from src.retrieval import (
    KB_CATEGORY_DEFS, invalidate_kb_caches, kb_disabled_key, kb_env_key)


def reset_kb(data_root, env_path, category, write_env=None):
    """停用指定子库并删除其导入副本，失败时恢复配置和目录。"""
    if category not in KB_CATEGORY_DEFS:
        raise ValueError("未知知识库类别")
    env_key = kb_env_key(category)
    disabled_key = kb_disabled_key(category)
    data_root = os.path.abspath(data_root)
    final = os.path.join(data_root, "private_kb", category)
    if os.path.lexists(final) and (not os.path.isdir(final) or os.path.islink(final)):
        raise ValueError("重置目标不是普通的导入副本目录，已停止操作")
    backup = os.path.join(data_root, f".kb-reset-backup-{uuid.uuid4().hex}")
    has_previous = os.path.exists(final)
    if has_previous:
        os.replace(final, backup)

    from kb_config_tx import read_config_bytes, restore_config_bytes
    previous = read_config_bytes(env_path)
    try:
        write_env(env_path, {env_key: final, disabled_key: "1"})
    except Exception as error:
        rollback_error = None
        try:
            restore_config_bytes(env_path, previous)
        except Exception as restore_error:
            rollback_error = restore_error
        if has_previous:
            try:
                os.replace(backup, final)
            except OSError as restore_error:
                raise OSError(f"重置配置及副本恢复均失败: {restore_error}；"
                              f"旧副本保留在 {backup}") from restore_error
        invalidate_kb_caches(final)
        if rollback_error is not None:
            raise OSError(f"重置配置失败，且配置回滚失败: {rollback_error}；"
                          "目录已恢复，请检查 .env 实际内容") from error
        return {"ok": False, "root": final, "category": category,
                "error": f"重置配置失败，已恢复原状态: {error}"}
    if has_previous:
        shutil.rmtree(backup)
    invalidate_kb_caches(final)
    return {"ok": True, "root": final, "category": category, "configured": True}
