#!/usr/bin/env python3
"""六维望诊 Web 层 — Flask 入口。

用法：
  python3 web/app.py            # 仅本机 http://127.0.0.1:8600
  python3 web/app.py --lan      # 局域网 http://0.0.0.0:8600（需先在设置页设 WEB_ADMIN_TOKEN）

安全默认：绑 127.0.0.1；局域网访问且未设 WEB_ADMIN_TOKEN 时设置页只读。
配置唯一存储 = 项目根 .env（web/envfile.py，严格 UTF-8）。
"""
from __future__ import annotations

import argparse
import importlib
import os
import sys
import tempfile

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (_REPO_ROOT, os.path.join(_REPO_ROOT, "scripts"),
           os.path.dirname(os.path.abspath(__file__))):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from flask import Flask, jsonify, redirect, render_template, request

import envfile
import llm_client

# 设置页管理的键（顺序即页面展示顺序）
VISION_KEYS = ["VISION_API_KEY", "VISION_MODEL", "VISION_BASE_URL",
               "VISION_TEMPERATURE", "VISION_TIMEOUT"]
LLM_KEYS = ["LLM_API_KEY", "LLM_MODEL", "LLM_BASE_URL"]
SECRET_KEYS = {"VISION_API_KEY", "LLM_API_KEY", "WEB_ADMIN_TOKEN"}

# 1×1 白底 PNG（连通性测试用最小合法图片，不携带任何真实内容）
_TINY_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
    "AAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def create_app(env_file: str | None = None) -> Flask:
    app = Flask(__name__)
    env_path = env_file or os.path.join(_REPO_ROOT, ".env")

    def cfg(key: str, default: str = "") -> str:
        return envfile.effective(key, env_path, default)

    def is_local() -> bool:
        return request.remote_addr in ("127.0.0.1", "::1", "localhost")

    def admin_token() -> str:
        return cfg("WEB_ADMIN_TOKEN")

    def admin_allowed() -> bool:
        """本机直接放行；局域网需口令（GET 用 ?token=，POST 用表单/JSON 字段）。"""
        if is_local():
            return True
        token = admin_token()
        if not token:
            return False
        if request.is_json:
            provided = (request.json or {}).get("admin_token")
        else:
            provided = request.args.get("token") or request.form.get("admin_token")
        return bool(provided) and provided == token

    def vision_configured() -> bool:
        return bool(cfg("VISION_API_KEY"))

    @app.get("/")
    def index():
        if not vision_configured():
            return redirect("/settings?welcome=1")
        return render_template("index.html", page="index")

    def settings_values() -> dict:
        values = {}
        for k in VISION_KEYS + LLM_KEYS + ["WEB_ADMIN_TOKEN", "WEB_HOST"]:
            v = cfg(k)
            values[k] = {
                "set": bool(v),
                "value": "" if k in SECRET_KEYS else v,
                "source": "环境变量" if os.environ.get(k) else (".env" if v else "未设置"),
            }
        return values

    @app.get("/settings")
    def settings():
        return render_template(
            "settings.html", page="settings", values=settings_values(),
            read_only=not admin_allowed(),
            token_arg=request.args.get("token", ""),
            welcome=request.args.get("welcome") == "1",
            saved=request.args.get("saved") == "1",
            env_error=request.args.get("env_error", ""),
        )

    @app.post("/settings")
    def settings_save():
        if not admin_allowed():
            return render_template("settings.html", page="settings",
                                   values=settings_values(),
                                   read_only=True, token_arg="", welcome=False,
                                   saved=False,
                                   env_error="无权限：局域网访问需正确管理口令"), 403
        f = request.form
        updates = {}
        # 机密键：留空 = 不修改
        for k in ("VISION_API_KEY", "LLM_API_KEY", "WEB_ADMIN_TOKEN"):
            if f.get(k):
                updates[k] = f[k]
        # 普通键：只更新本表单实际提交的键（缺席 = 不碰，空串 = 显式置空）
        for k in ("VISION_MODEL", "VISION_BASE_URL", "VISION_TEMPERATURE",
                  "VISION_TIMEOUT", "LLM_MODEL", "LLM_BASE_URL"):
            if k in f:
                updates[k] = f[k].strip()
        if "WEB_HOST" in f:
            updates["WEB_HOST"] = f["WEB_HOST"].strip() or "127.0.0.1"
        try:
            envfile.write_env(env_path, updates)
        except envfile.EnvDecodeError as e:
            return redirect(f"/settings?env_error={str(e)}")
        suffix = f"&token={f.get('admin_token')}" if f.get("admin_token") else ""
        return redirect(f"/settings?saved=1{suffix}")

    @app.post("/settings/test")
    def settings_test():
        if not admin_allowed():
            return jsonify({"ok": False, "detail": "无权限：需管理口令"}), 403
        target = (request.json or {}).get("target")
        try:
            if target == "vision":
                import base64
                import vision_client
                # 注入当前生效配置并 reload（模块级 MODEL/URL 在 import 时读取）
                os.environ["VISION_MODEL"] = cfg("VISION_MODEL", "qwen3.8-max")
                os.environ["VISION_BASE_URL"] = cfg(
                    "VISION_BASE_URL",
                    "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions")
                os.environ["VISION_API_KEY"] = cfg("VISION_API_KEY")
                importlib.reload(vision_client)
                with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
                    tf.write(base64.b64decode(_TINY_PNG_B64))
                    tmp = tf.name
                try:
                    dt, _ = vision_client.call(tmp, "这是一张测试图，只回复两个字：正常",
                                               timeout=60)
                finally:
                    os.unlink(tmp)
                return jsonify({"ok": True, "detail": f"连通正常 · 耗时 {dt}s"})
            if target == "llm":
                dt = llm_client.ping(cfg("LLM_MODEL"), cfg("LLM_BASE_URL"),
                                     cfg("LLM_API_KEY"))
                return jsonify({"ok": True, "detail": f"连通正常 · 耗时 {dt}s"})
            return jsonify({"ok": False, "detail": f"未知测试目标 {target!r}"}), 400
        except RuntimeError as e:
            return jsonify({"ok": False, "detail": str(e)})
        except Exception as e:  # 连通性测试的失败必须可见，不静默
            return jsonify({"ok": False, "detail": f"{type(e).__name__}: {e}"})

    return app


def main():
    parser = argparse.ArgumentParser(description="六维望诊 Web 层")
    parser.add_argument("--lan", action="store_true",
                        help="绑 0.0.0.0 开放局域网（需先设 WEB_ADMIN_TOKEN）")
    parser.add_argument("--port", type=int, default=8600)
    args = parser.parse_args()

    app = create_app()
    env_path = os.path.join(_REPO_ROOT, ".env")
    host = "0.0.0.0" if args.lan else envfile.effective("WEB_HOST", env_path,
                                                        "127.0.0.1")
    if host == "0.0.0.0" and not envfile.effective("WEB_ADMIN_TOKEN", env_path):
        print("[web][warn] 局域网模式但未设 WEB_ADMIN_TOKEN——设置页对局域网只读",
              file=sys.stderr)
    print(f"六维望诊 Web 层 → http://{host}:{args.port}", file=sys.stderr)
    app.run(host=host, port=args.port)


if __name__ == "__main__":
    main()
