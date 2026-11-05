"""知识库设置、分类导入与重置路由；依赖由 create_app 显式注入。"""
from __future__ import annotations

import os

from flask import jsonify, redirect, request
from io_utils import write_lock


def register_kb_routes(app, *, admin_allowed, is_env_locked, env_lock,
                       data_root, env_path, envfile, render_settings):
    @app.post("/settings/kb/mode")
    def settings_kb_mode():
        if not admin_allowed():
            return render_settings(env_error="无权限：需管理口令或有效会话"), 403
        if is_env_locked("TCM_KB_STRICT_CATEGORIES"):
            return render_settings(env_error="TCM_KB_STRICT_CATEGORIES 已被环境变量锁定"), 409
        enabled = request.form.get("enabled") == "1"
        try:
            with env_lock, write_lock(os.path.dirname(os.path.abspath(env_path))):
                envfile.write_env(env_path, {"TCM_KB_STRICT_CATEGORIES": "1" if enabled else ""})
        except (envfile.EnvDecodeError, ValueError) as error:
            return render_settings(env_error=str(error)), 400
        return redirect("/settings?saved=1#kb-import-card")

    @app.post("/settings/kb/reset")
    def settings_kb_reset():
        if not admin_allowed():
            return render_settings(env_error="无权限：需管理口令或有效会话"), 403
        from src.retrieval import kb_disabled_key, kb_env_key
        category = request.form.get("category", "")
        try:
            env_key = kb_env_key(category)
            disabled_key = kb_disabled_key(category)
        except ValueError as error:
            return render_settings(env_error=str(error)), 400
        if is_env_locked(env_key) or is_env_locked(disabled_key):
            return render_settings(env_error="该类知识库配置被环境变量锁定，不能重置"), 409
        from kb_reset import reset_kb
        try:
            with env_lock, write_lock(os.path.dirname(os.path.abspath(env_path))):
                result = reset_kb(data_root, env_path, category,
                                  write_env=envfile.write_env)
        except ValueError as error:
            return render_settings(env_error=str(error)), 400
        except OSError as error:
            return render_settings(env_error=str(error)), 500
        if not result["ok"]:
            return render_settings(env_error=result["error"]), 500
        return redirect(f"/settings?kb_reset={category}#kb-import-card")

    @app.post("/settings/kb/import")
    def settings_kb_import():
        if not admin_allowed():
            return jsonify({"ok": False, "error": "无权限：需管理口令或有效会话"}), 403
        upload = request.files.get("kb_file")
        if upload is None or not upload.filename:
            return jsonify({"ok": False, "error": "请选择要导入的 ZIP 文件"}), 400
        if not upload.filename.lower().endswith(".zip"):
            return jsonify({"ok": False, "error": "只支持 .zip 文件"}), 400
        from kb_import import import_kb
        from src.retrieval import kb_disabled_key, kb_env_key
        category = request.form.get("category", "composite")
        try:
            env_key = kb_env_key(category)
            disabled_key = kb_disabled_key(category)
        except ValueError as error:
            return jsonify({"ok": False, "error": str(error)}), 400
        locked = is_env_locked(env_key) or is_env_locked(disabled_key)
        try:
            with env_lock, write_lock(os.path.dirname(os.path.abspath(env_path))):
                result = import_kb(upload, data_root, env_path,
                                   env_locked=locked,
                                   write_env=envfile.write_env, category=category)
        except ValueError as error:
            return jsonify({"ok": False, "error": str(error)}), 400
        except OSError as error:
            return jsonify({"ok": False, "error": f"知识库导入失败: {error}"}), 500
        return jsonify(result), 200 if result["ok"] else 500
