#!/usr/bin/env python3
"""六维望诊 Web 层 — Flask 入口。

用法：
  python3 web/app.py            # 仅本机 http://127.0.0.1:8600
  python3 web/app.py --lan      # 局域网 http://0.0.0.0:8600（需先在设置页设 WEB_ADMIN_TOKEN）

安全默认：绑 127.0.0.1；非回环监听必须设置 WEB_ADMIN_TOKEN。
局域网通过 POST 口令取得会话；未认证时设置页只读，健康数据不可读写。
配置唯一存储 = 项目根 .env（web/envfile.py，严格 UTF-8）。
"""
from __future__ import annotations

import argparse
import datetime
import hmac
import ipaddress
import json
import math
import os
import re
import secrets
import threading
import sys
import tempfile
from urllib.parse import urlsplit

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (_REPO_ROOT, os.path.join(_REPO_ROOT, "scripts"),
           os.path.dirname(os.path.abspath(__file__))):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from flask import Flask, abort, g, jsonify, redirect, render_template, request, \
    send_file, send_from_directory, url_for

import envfile
import kb_routes
import llm_client
import local_report
import mdmini
import records_store
import time_utils
import trends_store
import wizard_store
from server import serve_http
from src import paths
from src.record import DailyRecord

# 设置页管理的键（顺序即页面展示顺序）
VISION_KEYS = ["VISION_API_KEY", "VISION_MODEL", "VISION_BASE_URL",
               "VISION_TEMPERATURE", "VISION_TIMEOUT", "VISION_MAX_TOKENS"]
LLM_KEYS = ["LLM_API_KEY", "LLM_MODEL", "LLM_BASE_URL",
            "LLM_MAX_TOKENS", "LLM_TIMEOUT"]
SECRET_KEYS = {"VISION_API_KEY", "LLM_API_KEY", "WEB_ADMIN_TOKEN"}

# 64×64 暖纸色 PNG（连通性测试用图，不携带任何真实内容）。
def _tiny_png_b64():
    import base64
    import io
    from PIL import Image
    output = io.BytesIO()
    Image.new("RGB", (64, 64), (250, 247, 241)).save(output, format="PNG")
    return base64.b64encode(output.getvalue()).decode("ascii")


_TINY_PNG_B64 = _tiny_png_b64()


def create_app(env_file: str | None = None,
               data_root: str | None = None) -> Flask:
    app = Flask(__name__)
    from photo_store import MAX_PHOTO_BYTES
    app.config["MAX_CONTENT_LENGTH"] = MAX_PHOTO_BYTES + 1024 * 1024
    env_path = env_file or os.path.join(_REPO_ROOT, ".env")
    # 启动时环境变量优先；每个请求只读取一次 .env，不把配置写回进程环境。
    boot_env = dict(os.environ)
    data_root = data_root or paths.DATA_ROOT
    daily_dir = os.path.join(data_root, "records", "daily")
    photos_dir = os.path.join(data_root, "records", "photos")
    backup_dir = os.path.join(data_root, "records", "_backup")
    app.jinja_env.filters["markdown"] = mdmini.render

    def cfg(key: str, default: str = "") -> str:
        if boot_env.get(key):
            return boot_env[key]
        if "config_snapshot" not in g:
            g.config_snapshot = envfile.read_env(env_path)
        return g.config_snapshot.get(key) or default

    def kb_cfg(key: str, default: str = "") -> str:
        if key == "TCM_DATA_ROOT":
            return data_root
        return cfg(key, default)

    def _today():
        return time_utils.today(cfg("TCM_TIMEZONE") or None).isoformat()

    def _wizard_date(value):
        from date_utils import parse_date
        candidate = parse_date(value) if isinstance(value, str) else None
        if candidate is None:
            return None
        age = (parse_date(_today()) - candidate).days
        if 0 <= age <= 1 and os.path.isfile(wizard_store.draft_path(
                daily_dir, candidate.isoformat())):
            return candidate.isoformat()
        return None

    def _host_name(value):
        try:
            parsed = urlsplit("//" + value.strip())
            parsed.port
        except ValueError:
            return ""
        if parsed.path or parsed.query or parsed.fragment \
                or parsed.username is not None or parsed.password is not None:
            return ""
        return parsed.hostname.rstrip(".") if parsed.hostname else ""

    def is_lan_host(value):
        try:
            return not ipaddress.ip_address(value).is_loopback
        except ValueError:
            return False

    def allowed_hosts():
        hosts = {"127.0.0.1", "localhost", "::1"}
        configured = app.config.get("BOUND_HOST") or cfg("WEB_HOST", "127.0.0.1")
        if configured == "localhost":
            hosts.add("localhost")
        try:
            address = ipaddress.ip_address(configured)
            if not address.is_loopback:
                hosts.add(address.compressed)
        except ValueError:
            pass
        if is_lan_host(configured):
            lan_ip = _lan_ip()
            if lan_ip:
                hosts.add(lan_ip)
        return hosts

    def origin_allowed(value):
        try:
            parsed = urlsplit(value)
            parsed.port
        except ValueError:
            return False
        return (parsed.scheme == request.scheme
                and not parsed.username and not parsed.password
                and parsed.netloc.lower().rstrip(".")
                    == request.host.lower().rstrip(".")
                and _host_name(parsed.netloc) in allowed_hosts())

    def is_local() -> bool:
        if request.headers.get("X-Forwarded-For"):
            return False
        try:
            address = ipaddress.ip_address(request.remote_addr)
        except ValueError:
            return False
        mapped = getattr(address, "ipv4_mapped", None)
        return (mapped or address).is_loopback

    def has_session():
        return request.cookies.get("boot_ack") == boot_token \
            or request.cookies.get("admin_session") in admin_sessions

    def has_admin_session():
        return request.cookies.get("admin_session") in admin_sessions

    def provided_token():
        payload = request.get_json(silent=True)
        if isinstance(payload, dict):
            return payload.get("admin_token")
        return request.form.get("admin_token")

    class InvalidJSON(Exception):
        pass

    def json_object():
        if not request.is_json or not request.data:
            return {}
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            raise InvalidJSON("请求体必须为 JSON 对象")
        return payload

    def admin_token() -> str:
        return cfg("WEB_ADMIN_TOKEN")

    def admin_allowed() -> bool:
        """本机直接放行；非回环需有效会话或管理口令。"""
        if is_local() or has_admin_session():
            return True
        token = admin_token()
        provided = provided_token()
        return bool(token and isinstance(provided, str)
                    and hmac.compare_digest(provided, token))

    def vision_configured() -> bool:
        return bool(cfg("VISION_API_KEY"))

    def vision_disabled() -> bool:
        """设置页「启用视觉模型」开关：关闭后拍照页改走手动录入。"""
        return cfg("VISION_DISABLED") == "1"

    def vision_ready() -> bool:
        """可实际调用视觉模型：开关启用且已配置 key。"""
        return not vision_disabled() and vision_configured()

    def llm_disabled() -> bool:
        """设置页「启用辨证模型」开关：关闭后报告区改走本地规则速览。"""
        return cfg("LLM_DISABLED") == "1"

    def llm_ready() -> bool:
        """可实际调用辨证 LLM：开关启用且三要素齐全。"""
        return (not llm_disabled() and bool(cfg("LLM_API_KEY")
                and cfg("LLM_MODEL") and cfg("LLM_BASE_URL")))

    # 每次进程启动生成新口令 → 重启后声明页必重新确认
    boot_token = secrets.token_hex(8)
    admin_sessions = set()
    # 本进程配置写入串行化；跨线程/进程文件锁由 envfile/io_utils 提供。
    env_lock = threading.Lock()

    from io_utils import WriteConflictError

    @app.errorhandler(413)
    def upload_too_large(error):
        return jsonify({"ok": False, "error": "上传请求超过 20 MiB 图片上限"}), 413

    @app.errorhandler(WriteConflictError)
    def write_conflict(error):
        if request.endpoint == "wizard_context":
            return redirect(url_for("wizard", context_error=str(error)))
        message = str(error)
        return jsonify({"ok": False, "conflict": True,
                        "error": message, "errors": [message]}), 409

    @app.errorhandler(InvalidJSON)
    def invalid_json(error):
        message = str(error)
        return jsonify({"ok": False, "error": message, "errors": [message]}), 400

    @app.errorhandler(envfile.EnvDecodeError)
    def env_decode_error(error):
        g.config_error = True
        if request.method == "POST":
            return redirect(url_for("settings", env_error=str(error)))
        return app.response_class(
            f"配置读取失败：{error}\n请将该文件转换为 UTF-8 后重启服务。\n",
            status=200, mimetype="text/plain; charset=utf-8")

    def security_error(message):
        if request.is_json:
            return jsonify({"ok": False, "error": message,
                            "errors": [message]}), 403
        return message, 403

    @app.before_request
    def security_guard():
        if _host_name(request.host) not in allowed_hosts():
            return security_error("请求被拒绝：主机名不受信任")
        if request.method not in ("POST", "PUT", "PATCH", "DELETE"):
            return None
        fetch_site = request.headers.get("Sec-Fetch-Site")
        if fetch_site == "cross-site":
            return security_error("请求被拒绝：跨站操作")
        origin = request.headers.get("Origin") or request.headers.get("Referer")
        # Origin:null 不能直接信任；仅接受浏览器明确标记的 same-origin。
        metadata_same_origin = origin == "null" and fetch_site == "same-origin"
        if origin and not metadata_same_origin and not origin_allowed(origin):
            return security_error("请求被拒绝：来源不受信任")
        if not origin and not metadata_same_origin:
            if request.endpoint == "welcome_ack":
                return security_error("请求被拒绝：缺少同源信息")
            if not has_session():
                return security_error("请求被拒绝：缺少同源信息或有效会话")
        return None

    @app.before_request
    def require_boot_ack():
        # guide 是只读公开文档且被 welcome 页引用，必须在门禁之外；
        # settings 另由 admin_allowed 保护，可提供口令登录。
        if request.endpoint in ("welcome", "welcome_ack", "license_text", "settings",
                                "settings_save", "settings_toggle", "settings_kb_import", "settings_kb_mode", "settings_kb_reset", "settings_login", "guide", "guide_doc",
                                "guide_images", "static"):
            return None
        if not is_local() and not admin_allowed():
            if request.is_json:
                return jsonify({"ok": False, "error": "无权限：需管理口令或有效会话"}), 403
            return redirect(url_for("settings", welcome=1))
        if request.cookies.get("boot_ack") != boot_token:
            return redirect("/welcome")
        return None

    @app.after_request
    def security_headers(resp):
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Content-Security-Policy"] = "frame-ancestors 'none'"
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["Vary"] = "Sec-Fetch-Dest, Sec-Fetch-Mode, Sec-Fetch-Site"
        if not is_local() and not has_admin_session() \
                and not g.get("config_error", False) and admin_token():
            provided = provided_token()
            if isinstance(provided, str) and hmac.compare_digest(provided, admin_token()):
                session = secrets.token_urlsafe(24)
                admin_sessions.add(session)
                resp.set_cookie("admin_session", session, httponly=True,
                                samesite="Strict", secure=request.is_secure)
        return resp

    @app.context_processor
    def inject_flags():
        # 开关主动关闭 = 有意不用，不弹警告；启用但配置不全才提示
        return {
            "vision_missing": not vision_disabled() and not vision_configured(),
            "llm_missing": not llm_disabled() and not llm_ready(),
        }

    @app.get("/welcome")
    def welcome():
        return render_template("welcome.html", page="welcome")

    @app.post("/welcome")
    def welcome_ack():
        resp = redirect("/" if vision_configured() or vision_disabled() else "/settings")
        resp.set_cookie("boot_ack", boot_token, httponly=True,
                        samesite="Strict", secure=request.is_secure)
        return resp

    @app.get("/license")
    def license_text():
        try:
            with open(os.path.join(_REPO_ROOT, "LICENSE"), encoding="utf-8") as f:
                return app.response_class(f.read(), mimetype="text/plain; charset=utf-8")
        except OSError:
            return "LICENSE 文件缺失，见 https://www.gnu.org/licenses/gpl-3.0.txt", 404

    @app.get("/guide")
    def guide():
        """/guide → /guide/（尾斜杠让手册里的相对图片路径 images/xxx.jpg
        解析到 /guide/images/xxx.jpg；浏览器在重定向后保留 #锚点）。"""
        return redirect("/guide/")

    @app.get("/guide/")
    def guide_doc():
        """使用手册（独立静态页，自包含暖纸主题；新标签打开，不包外壳）。"""
        path = os.path.join(_REPO_ROOT, "docs", "user-guide.html")
        if not os.path.exists(path):
            return "使用手册缺失：docs/user-guide.html 不存在", 404
        return send_file(path, mimetype="text/html")

    @app.get("/guide/images/<path:filename>")
    def guide_images(filename):
        """手册配图（docs/images/ 下的静态资源）。"""
        return send_from_directory(os.path.join(_REPO_ROOT, "docs", "images"),
                                   filename)

    _MONTH_RE = re.compile(r"^\d{4}-\d{2}$")
    _DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

    @app.get("/")
    def index():
        from date_utils import parse_month
        today = _today()
        month = (parse_month(request.args.get("m", "")) or parse_month(today[:7]))
        month = month.strftime("%Y-%m")
        summaries = records_store.list_summaries(daily_dir, limit=7)
        return render_template(
            "index.html", page="index",
            summaries=summaries,
            stats=records_store.week_stats(
                summaries, today, records_store.list_dates(daily_dir)),
            cal=records_store.calendar_month(daily_dir, month, today),
            empty=not summaries,
            sev=records_store.sev_class,
        )

    @app.post("/demo")
    def load_demo():
        """空库引导：载入合成示例记录（fixture 自述为合成数据）。"""
        if not admin_allowed():
            return redirect("/")
        try:
            date = records_store.load_demo(daily_dir)
        except FileExistsError:
            return "示例数据只能在空库中载入", 409
        return redirect(f"/record/{date}")

    @app.get("/record/<date>")
    def record_detail(date):
        from date_utils import parse_date
        if parse_date(date) is None:
            abort(404)
        rec = records_store.load_record(daily_dir, date)
        if rec is None:
            abort(404)
        diag = rec.raw.get("diagnosis")
        from src.retrieval import KB_CATEGORY_DEFS, inspect_kb, inspect_kb_categories, \
            kb_legacy_root
        current_categories = inspect_kb_categories(kb_cfg)
        state = trends_store.report_state(
            rec, kb_info=inspect_kb(kb_legacy_root(kb_cfg)),
            kb_categories=current_categories)
        has_llm_content = (isinstance(diag, dict)
                           and isinstance(diag.get("report"), dict)) \
            or bool(rec.get_pattern_differentiation())
        local_mode = (llm_disabled()
                      or (not llm_ready() and (not has_llm_content or state["stale"])))
        view = records_store.record_detail(rec, date_str=date)
        view["report_stale"] = state["stale"]
        view["stale_reasons"] = state["reasons"]
        if state["stale"]:
            view["diagnosis"] = None
        return render_template(
            "record.html", page="index", r=view,
            report=None if local_mode or state["stale"] else view["report"],
            llm_configured=llm_ready(),
            local_mode=local_mode,
            kb_categories=current_categories, kb_category_defs=KB_CATEGORY_DEFS,
            local_overview=(local_report.build_pattern_overview(rec)
                            if local_mode else None),
            photos=records_store.list_photos(photos_dir, date, rec),
            sev=records_store.sev_class,
        )

    @app.post("/record/<date>/report")
    def record_report(date):
        """生成/重新生成辨证报告（辨证 LLM → Markdown → 写回记录 JSON）。"""
        if not admin_allowed():
            return jsonify({"ok": False, "error": "无权限：需管理口令"}), 403
        if not _DATE_RE.match(date):
            abort(404)
        if llm_disabled():
            return jsonify({"ok": False,
                            "error": "辨证模型已在设置页关闭（本地速览模式）"}), 400
        from src.retrieval import KB_CATEGORY_DEFS, kb_category_root
        result = trends_store.generate_and_store_report(
            daily_dir, backup_dir, date,
            lambda: {"model": cfg("LLM_MODEL"), "base_url": cfg("LLM_BASE_URL"),
                     "api_key": cfg("LLM_API_KEY"),
                     "max_tokens": cfg("LLM_MAX_TOKENS"),
                     "timeout": cfg("LLM_TIMEOUT"),
                     "kb_root": cfg("TCM_KB_ROOT") or None,
                     "kb_roots": {category: kb_category_root(category, kb_cfg)
                                  for category in KB_CATEGORY_DEFS}},
            timezone_name=cfg("TCM_TIMEZONE") or None)
        return jsonify(result), (200 if result["ok"]
                                 else 409 if result.get("in_progress") else 400)

    @app.get("/trends")
    def trends():
        from date_utils import add_days, parse_date
        today = _today()
        target_d = parse_date(request.args.get("week", "")) or parse_date(_today())
        target = target_d.isoformat()
        payload = trends_store.week_payload(daily_dir, target)
        latest = None
        if payload is None:
            latest = records_store.latest_record_date(daily_dir)
        return render_template(
            "trends.html", page="trends", week=payload,
            latest_with_records=latest,
            prev_week=add_days(target_d, -7),
            next_week=add_days(target_d, 7),
            is_current=target == today,
        )

    @app.post("/record/<date>/field")
    def record_update_field(date):
        """修正一个观察值：validator ❌ 拦截 / ⚠️ 放行展示；成功后前端整页刷新。"""
        if not admin_allowed():
            return jsonify({"ok": False, "errors": ["无权限：需管理口令"]}), 403
        from date_utils import parse_date
        if parse_date(date) is None:
            abort(404)
        body = json_object()
        action = body.get("action", "set")
        if not isinstance(action, str) or action not in ("set", "clear"):
            return jsonify({"ok": False, "errors": ["action 必须为 set 或 clear"]}), 400
        dim, indicator = body.get("dim"), body.get("indicator")
        if not all(isinstance(v, str) for v in (dim, indicator)):
            return jsonify({"ok": False,
                            "errors": ["dim/indicator 必须为字符串"]}), 400
        value = body.get("value")
        if action == "set" and not isinstance(value, str):
            return jsonify({"ok": False, "errors": ["value 必须为字符串"]}), 400
        method = body.get("method", "manual")
        evidence = body.get("evidence", {})
        if not isinstance(method, str) or not method.strip() or not isinstance(evidence, dict):
            return jsonify({"ok": False, "errors": ["采集方式或证据格式错误"]}), 400
        result = records_store.update_observation(
            daily_dir, backup_dir, date, dim, indicator, value,
            method=method.strip(), evidence=evidence, action=action,
            client=request.remote_addr or "",
            timezone_name=cfg("TCM_TIMEZONE") or None)
        status = 200 if result["ok"] else 400
        return jsonify(result), status

    @app.post("/record/<date>/restore")
    def record_restore(date):
        """恢复当前代修正前状态，或撤销最近一次恢复；报告保留。"""
        if not admin_allowed():
            return jsonify({"ok": False, "error": "无权限：需管理口令"}), 403
        if not _DATE_RE.match(date):
            abort(404)
        result = records_store.restore_original(
            daily_dir, backup_dir, date, timezone_name=cfg("TCM_TIMEZONE") or None)
        return jsonify(result), (200 if result["ok"] else 400)

    @app.post("/record/<date>/delete")
    def record_delete(date):
        if not admin_allowed():
            return jsonify({"ok": False, "error": "无权限：需管理口令"}), 403
        from date_utils import parse_date
        if parse_date(date) is None:
            abort(404)
        confirmation = (json_object() if request.is_json else request.form).get("confirm")
        if confirmation != "DELETE":
            return jsonify({"ok": False, "error": "必须明确确认 DELETE"}), 400
        from lifecycle_store import delete_day
        result = delete_day(daily_dir, backup_dir, photos_dir, date, confirmed=True)
        if request.is_json or not result["ok"]:
            return jsonify(result), (200 if result["ok"] else 400)
        return redirect("/")

    @app.get("/photos/<date>/<path:filename>")
    def photo(date, filename):
        """原图对照：只提供当前记录绑定的清洗后图片。"""
        rec = records_store.load_record(daily_dir, date)
        if rec is None or filename not in records_store.list_photos(
                photos_dir, date, rec):
            abort(404)
        return send_from_directory(os.path.join(photos_dir, date), filename)

    @app.get("/photos-staging/<date>/<path:filename>")
    def photo_staging(date, filename):
        if not _DATE_RE.match(date) or os.path.basename(filename) != filename \
                or not filename.endswith(".jpg"):
            abort(404)
        return send_from_directory(os.path.join(photos_dir, date, ".staging"), filename)

    # ---------------- 拍照向导（切片 4） ----------------

    def _number(key, value, default, kind, positive):
        if value is None or isinstance(value, str) and not value.strip():
            return default
        try:
            result = kind(value)
        except (TypeError, ValueError) as error:
            raise ValueError(f"{key} 数值格式无效: {value!r}") from error
        if not math.isfinite(result) or positive and result <= 0:
            raise ValueError(f"{key} 必须为{'正数' if positive else '有限数值'}")
        return result

    def _validate_vision_number(key, value):
        return _number(key, value, None,
                       float if key == "VISION_TEMPERATURE" else int,
                       key != "VISION_TEMPERATURE")

    def _vision_options():
        return {
            "model": cfg("VISION_MODEL", "qwen3.8-max"),
            "url": llm_client.normalize_chat_url(cfg("VISION_BASE_URL")),
            "key": cfg("VISION_API_KEY"),
            "timeout": _number("VISION_TIMEOUT", cfg("VISION_TIMEOUT"), 150, int, True),
            "max_tokens": _number("VISION_MAX_TOKENS", cfg("VISION_MAX_TOKENS"),
                                  600, int, True),
            "temperature": _number("VISION_TEMPERATURE", cfg("VISION_TEMPERATURE"),
                                   None, float, False),
        }

    def _recent_draft():
        candidates = []
        if os.path.isdir(daily_dir):
            for entry in os.scandir(daily_dir):
                match = re.fullmatch(r"\.wizard-(\d{4}-\d{2}-\d{2})\.json", entry.name)
                if match:
                    date = _wizard_date(match.group(1))
                    if date and date < _today():
                        candidates.append(date)
        return max(candidates) if candidates else None

    @app.get("/wizard")
    def wizard():
        requested = _wizard_date(request.args.get("date"))
        today = requested or _today()
        if not requested and request.args.get("new") != "1" \
                and not os.path.isfile(wizard_store.draft_path(daily_dir, today)):
            today = _recent_draft() or today
        existing_rec = records_store.load_record(daily_dir, today)
        existing = None
        if existing_rec:
            covered = existing_rec.get_dimension_coverage()
            existing = {
                "coverage": existing_rec.get_covered_dimension_count(),
                "uncovered": [d.chinese_name for d, c in covered.items() if not c],
            }
        return render_template(
            "wizard.html", page="wizard",
            state=wizard_store.wizard_state(daily_dir, today, existing),
            inquiry_spec=wizard_store.INQUIRY_SPEC,
            inquiry_items=wizard_store.INQUIRY_ITEMS,
            danger_flags=records_store.DANGER_FLAGS,
            glossary=records_store.GLOSSARY,
            correction_meta=records_store.correction_meta(),
            context_spec=wizard_store.CONTEXT_SPEC,
            context_error=request.args.get("context_error", ""),
            manual_mode=not vision_ready(),
            server_date=_today(), resumed=today != _today(),
        )

    # 部位 → 可写的 B 路径前缀（舌面/舌底共享舌诊维度，防止跨部位写
    # 静默顶掉同维度真值；其余维度一部件一维度全量放开）
    _PART_B_PREFIX = {"舌面": ("body.", "coating."), "舌底": ("sublingual.",)}

    @app.post("/wizard/field")
    def wizard_update_field():
        """向导草稿就地修正一个观察值（第 8 步复核卡片）。
        只写草稿不落盘；危险信号在提交组装时统一重探（assemble_record）。"""
        if not admin_allowed():
            return jsonify({"ok": False, "error": "无权限：需管理口令"}), 403
        body = json_object()
        part, indicator, value = (body.get("part"), body.get("indicator"),
                                  body.get("value"))
        if not all(isinstance(item, str) for item in (part, indicator, value)):
            return jsonify({"ok": False, "error": "部位、指标和值必须为字符串"}), 400
        value = value.strip()
        p = wizard_store.PART_BY_NAME.get(part)
        if not p:
            return jsonify({"ok": False, "error": f"未知部位: {part}"}), 400
        from src.dimensions import from_chinese
        from src.record import _DIMENSION_INDICATORS
        dim = from_chinese(p["dim"])
        shapes = _DIMENSION_INDICATORS.get(dim, {}).get(indicator)
        if shapes is None:
            return jsonify({"ok": False, "error":
                            f"未知指标: {part}/{indicator}"}), 400
        b_path = ".".join(shapes["B"])
        prefixes = _PART_B_PREFIX.get(part)
        if prefixes and not b_path.startswith(prefixes):
            return jsonify({"ok": False, "error":
                            f"{part} 不可写指标 {indicator}"}), 400
        if not value:
            return jsonify({"ok": False, "error": "值不能为空"}), 400
        today = _wizard_date(body.get("date")) or _today()
        draft, draft_version = wizard_store.load_draft_with_version(daily_dir, today)
        st = draft["parts"].get(part, {})
        # 只允许修订已识图/已手动录入部位——防凭空造「无来源伪观察」
        # （虚增覆盖度/photo_coverage/confidence），也保住「声明正常」的审计痕迹
        if st.get("status") not in ("observed", "manual") or not isinstance(
                st.get("observation"), dict):
            return jsonify({"ok": False, "error":
                            "该部位未识图/未录入，无观察值可修正"}), 400
        method = body.get("method", "manual")
        evidence = body.get("evidence", {})
        if not isinstance(method, str) or not method.strip() or not isinstance(evidence, dict):
            return jsonify({"ok": False, "error": "采集方式或证据格式错误"}), 400
        try:
            obs = wizard_store.update_draft_observation(
                st, dim, indicator, value, source="manual", method=method.strip(),
                evidence=evidence, part=part)
        except ValueError as e:
            return jsonify({"ok": False, "error": str(e)}), 400
        st["status"] = "manual"
        wizard_store.save_draft(daily_dir, draft, draft_version)
        # 即时红线反馈（全草稿 + 问诊答案，与 assemble 探测同口径）
        all_obs = {pt: s.get("observation")
                   for pt, s in draft["parts"].items() if s.get("observation")}
        all_obs["inquiry"] = draft.get("inquiry") or {}
        danger = wizard_store.detect_danger(all_obs)
        return jsonify({"ok": True, "observation_meta": obs.to_meta() if obs else None,
                        "danger": danger,
                        "danger_names": [records_store.DANGER_FLAGS.get(
                            k, {}).get("name", k) for k in danger]})

    @app.post("/wizard/manual")
    def wizard_manual_field():
        """手动录入一个观察值（视觉模型未启用时的录入通道，状态 manual）。

        校验链与 /wizard/field 同口径（部位/指标/B 路径前缀/封闭词表），
        空值不写入（留空字段 = 未检出）；危险信号提交组装时统一重探。"""
        if not admin_allowed():
            return jsonify({"ok": False, "error": "无权限：需管理口令"}), 403
        body = json_object()
        part, indicator, value = (body.get("part"), body.get("indicator"),
                                  body.get("value", ""))
        if not all(isinstance(item, str) for item in (part, indicator, value)):
            return jsonify({"ok": False, "error": "部位、指标和值必须为字符串"}), 400
        value = value.strip()
        p = wizard_store.PART_BY_NAME.get(part)
        if not p:
            return jsonify({"ok": False, "error": f"未知部位: {part}"}), 400
        from src.dimensions import from_chinese
        from src.record import _DIMENSION_INDICATORS
        dim = from_chinese(p["dim"])
        shapes = _DIMENSION_INDICATORS.get(dim, {}).get(indicator)
        if shapes is None:
            return jsonify({"ok": False, "error":
                            f"未知指标: {part}/{indicator}"}), 400
        b_path = ".".join(shapes["B"])
        prefixes = _PART_B_PREFIX.get(part)
        if prefixes and not b_path.startswith(prefixes):
            return jsonify({"ok": False, "error":
                            f"{part} 不可写指标 {indicator}"}), 400
        today = _wizard_date(body.get("date")) or _today()
        draft, draft_version = wizard_store.load_draft_with_version(daily_dir, today)
        st = draft["parts"].setdefault(part, {})
        # 可写状态：未开始/已手动录入/已跳过（跳过后改主意允许用真实值覆盖——
        # 真实录入优先于声明，审计语义更好，也给误点跳过留逃生口）
        if st.get("status") not in (None, "manual", "skip_normal", "skip_uncovered"):
            return jsonify({"ok": False, "error":
                            f"{part} 已是「{st.get('status')}」状态，不可手动录入"}), 400
        method = body.get("method", "manual")
        evidence = body.get("evidence", {})
        if not isinstance(method, str) or not method.strip() or not isinstance(evidence, dict):
            return jsonify({"ok": False, "error": "采集方式或证据格式错误"}), 400
        try:
            obs = wizard_store.update_draft_observation(
                st, dim, indicator, value, source="manual", method=method.strip(),
                evidence=evidence, part=part)
        except ValueError as e:
            return jsonify({"ok": False, "error": str(e)}), 400
        st["status"] = "manual"
        wizard_store.save_draft(daily_dir, draft, draft_version)
        all_obs = {pt: s.get("observation")
                   for pt, s in draft["parts"].items() if s.get("observation")}
        all_obs["inquiry"] = draft.get("inquiry") or {}
        danger = wizard_store.detect_danger(all_obs)
        return jsonify({"ok": True, "observation_meta": obs.to_meta() if obs else None,
                        "danger": danger,
                        "danger_names": [records_store.DANGER_FLAGS.get(
                            k, {}).get("name", k) for k in danger]})

    @app.post("/wizard/inquiry")
    def wizard_inquiry():
        """向导问诊步（手足温凉）：答案写入草稿。"""
        if not admin_allowed():
            return jsonify({"ok": False, "error": "无权限：需管理口令"}), 403
        body = json_object()
        today = _wizard_date(body.get("date")) or _today()
        draft, draft_version = wizard_store.load_draft_with_version(daily_dir, today)
        if body.get("clear_all"):
            draft["inquiry"] = {}
            try:
                events = wizard_store.refresh_draft_review(
                    draft, source="inquiry", client=request.remote_addr or "")
            except ValueError as error:
                return jsonify({"ok": False, "error": str(error)}), 400
            wizard_store.save_draft(daily_dir, draft, draft_version)
            return jsonify({"ok": True, **events})
        from src.textnorm import canonical_option, has_line_breaks
        answer = body.get("answer", "")
        question = body.get("question", wizard_store.INQUIRY_SPEC["key"])
        if not isinstance(answer, str) or not isinstance(question, str):
            return jsonify({"ok": False, "error": "问诊项和答案必须为字符串"}), 400
        definitions = {canonical_option(wizard_store.INQUIRY_SPEC["key"]):
                       wizard_store.INQUIRY_SPEC}
        definitions.update({canonical_option(item["q"]): item
                            for item in wizard_store.INQUIRY_ITEMS})
        spec = definitions.get(canonical_option(question))
        if spec is None:
            return jsonify({"ok": False, "error": f"未知问诊项: {question}"}), 400
        question = spec.get("key", spec.get("q"))
        answer = answer.strip()
        if len(answer) > 64 or has_line_breaks(answer):
            return jsonify({"ok": False, "error": "答案不得超过 64 字且不得换行"}), 400
        normalized = canonical_option(answer)
        allowed = {canonical_option(option) for option in spec["options"]}
        if normalized and normalized not in allowed:
            return jsonify({"ok": False, "error": f"答案不在封闭选项内: {answer}"}), 400
        if normalized:
            answer = next(option for option in spec["options"]
                          if canonical_option(option) == normalized)
        if question == "有汗or无汗？" and answer != "没有外感不适":
            previous = draft.get("inquiry", {}).get("恶寒or恶热？")
            previous_answer = previous.get("answer") if isinstance(previous, dict) else previous
            if previous_answer not in ("恶寒", "恶热", "往来寒热"):
                return jsonify({"ok": False,
                                "error": "请先回答恶寒/恶热/往来寒热，再评估有汗无汗"}), 400
        draft.setdefault("inquiry", {})
        if answer:
            if question == "恶寒or恶热？" and answer not in ("恶寒", "恶热", "往来寒热"):
                draft["inquiry"].pop("有汗or无汗？", None)
            draft["inquiry"][question] = answer
        else:
            draft["inquiry"].pop(question, None)
        try:
            events = wizard_store.refresh_draft_review(
                draft, source="inquiry", client=request.remote_addr or "")
        except ValueError as error:
            return jsonify({"ok": False, "error": str(error)}), 400
        wizard_store.save_draft(daily_dir, draft, draft_version)
        return jsonify({"ok": True, **events})

    @app.post("/wizard/context")
    def wizard_context():
        if not admin_allowed():
            return jsonify({"ok": False, "error": "无权限：需管理口令"}), 403
        context = {}
        for field in wizard_store.CONTEXT_SPEC:
            value = request.form.get(field["key"], "")
            if not isinstance(value, str) or len(value.strip()) > 300:
                return jsonify({"ok": False, "error": f"{field['label']}需为不超过 300 字的文本"}), 400
            value = value.strip()
            if field.get("options") and value and value not in field["options"]:
                return jsonify({"ok": False, "error": f"{field['label']}不在允许选项内"}), 400
            if value:
                context[field["key"]] = value
        today = _wizard_date(request.form.get("date")) or _today()
        draft, draft_version = wizard_store.load_draft_with_version(daily_dir, today)
        draft["context"] = context
        try:
            wizard_store.refresh_draft_review(
                draft, source="context", client=request.remote_addr or "")
        except ValueError as error:
            return jsonify({"ok": False, "error": str(error)}), 400
        wizard_store.save_draft(daily_dir, draft, draft_version)
        return redirect(url_for("wizard", date=today))

    @app.post("/wizard/photo")
    def wizard_photo():
        if not admin_allowed():
            return jsonify({"ok": False, "error": "无权限：需管理口令"}), 403
        part = request.form.get("part", "")
        meta = wizard_store.PART_BY_NAME.get(part)
        file = request.files.get("file")
        if not meta or not file or not file.filename:
            return jsonify({"ok": False, "error": "缺少部位或文件"}), 400
        ext = os.path.splitext(file.filename)[1].lower()
        if ext not in (".jpg", ".jpeg", ".png", ".webp"):
            return jsonify({"ok": False, "error": f"不支持的图片格式 {ext}"}), 400
        evidence_kind = request.form.get("evidence_kind", "")
        if evidence_kind not in ("", "clothing"):
            return jsonify({"ok": False, "error": "未知证据类型"}), 400
        evidence = {
            "has_scale": request.form.get("has_scale") in ("1", "true", "on"),
            "exposed": request.form.get("exposed") in ("1", "true", "on"),
        }
        if evidence_kind:
            evidence["kind"] = evidence_kind
        today = _wizard_date(request.form.get("date")) or _today()
        from photo_store import stage_upload
        try:
            staging_name = stage_upload(file, photos_dir, today, part)
        except ValueError as error:
            return jsonify({"ok": False, "error": str(error)}), 400
        img_path = os.path.join(photos_dir, today, ".staging", staging_name)

        if not vision_ready():
            return jsonify({"ok": False, "photo_saved": True, "staged": True,
                            "error": "图片已清洗并暂存，未替换已提交原图；视觉模型未启用，请启用后重试或使用手动录入"}), 400
        try:
            observe_json, _ = wizard_store.observe_photo(
                part, img_path, **_vision_options())
            node, unmapped, observations = wizard_store.map_observation_with_metadata(
                part, observe_json, source="vision", method="photo", evidence=evidence)
        except ValueError as e:
            return jsonify({"ok": False, "photo_saved": True, "staged": True,
                            "error": str(e)}), 400
        except RuntimeError as e:
            return jsonify({"ok": False, "photo_saved": True, "staged": True,
                            "error": str(e)}), 502
        draft, draft_version = wizard_store.load_draft_with_version(daily_dir, today)
        metadata = {obs.path: obs.to_meta() for obs in observations}
        draft["parts"][part] = {
            "status": "observed", "observation": node,
            "photo": f"{part}.jpg", "photo_staging": staging_name,
            "part": part, "source": "vision", "method": "photo",
            "observation_meta": metadata,
        }
        wizard_store.save_draft(daily_dir, draft, draft_version)
        return jsonify({"ok": True, "observation": node,
                        "observation_meta": metadata, "unmapped": unmapped,
                        "type_errors": node.get("_type_errors", []),
                        "photo": f"/photos-staging/{today}/{staging_name}"})

    @app.post("/wizard/skip")
    def wizard_skip():
        if not admin_allowed():
            return jsonify({"ok": False, "error": "无权限：需管理口令"}), 403
        body = json_object()
        part = body.get("part", "")
        mode = body.get("mode", "")
        if part not in wizard_store.PART_BY_NAME or mode not in (
                "normal", "uncovered", "refused", "unavailable"):
            return jsonify({"ok": False, "error": "参数错误"}), 400
        reason = body.get("reason", "")
        if not isinstance(reason, str) or len(reason) > 200:
            return jsonify({"ok": False, "error": "声明原因需为不超过 200 字的文本"}), 400
        today = _wizard_date(body.get("date")) or _today()
        draft, draft_version = wizard_store.load_draft_with_version(daily_dir, today)
        status = f"skip_{mode}" if mode in ("normal", "uncovered") else mode
        draft["parts"][part] = {"status": status, "reason": reason.strip()}
        wizard_store.save_draft(daily_dir, draft, draft_version)
        return jsonify({"ok": True})

    @app.post("/wizard/submit")
    def wizard_submit():
        if not admin_allowed():
            return jsonify({"ok": False, "error": "无权限：需管理口令"}), 403
        body = json_object()
        if not isinstance(body, dict):
            return jsonify({"ok": False, "error": "请求体必须为对象"}), 400
        mode = body.get("mode", "new")          # new（整体重建）| merge（只补未覆盖）
        acknowledge = body.get("acknowledge", "")
        if mode not in ("new", "merge"):
            return jsonify({"ok": False, "error": "mode 必须为 new 或 merge"}), 400
        if isinstance(acknowledge, str):
            if acknowledge not in ("", "keep", "fix"):
                return jsonify({"ok": False, "error": "acknowledge 必须为 keep 或 fix"}), 400
        elif not isinstance(acknowledge, dict) or any(
                not isinstance(key, str) or value not in ("keep", "dismiss")
                for key, value in acknowledge.items()):
            return jsonify({"ok": False, "error": "请逐项给出 keep 或 dismiss 裁决"}), 400
        token = body.get("danger_token", "")
        if not isinstance(token, str):
            return jsonify({"ok": False, "error": "danger_token 必须为字符串"}), 400
        today = _wizard_date(body.get("date")) or _today()
        draft, draft_version = wizard_store.load_draft_with_version(daily_dir, today)

        pending = [p["part"] for p in wizard_store.PARTS
                   if draft["parts"].get(p["part"], {}).get("status") == "pending"
                   or p["part"] not in draft["parts"]]
        if pending:
            return jsonify({"ok": False,
                            "error": f"还有未处理的部位：{'、'.join(pending)}"}), 400

        existing_rec, record_version = records_store.load_record_with_version(daily_dir, today)
        with open(os.path.join(_REPO_ROOT, "VERSION"), encoding="utf-8") as vf:
            version = vf.read().strip()
        try:
            raw = wizard_store.assemble_record(
                draft, version,
                existing_raw=existing_rec.raw if existing_rec else None,
                merge_only_uncovered=(mode == "merge"),
                timezone_name=cfg("TCM_TIMEZONE") or None)
        except ValueError as e:
            return jsonify({"ok": False, "error": str(e)}), 400

        from src.danger_review import (
            DangerReviewConflict, apply_decision, merge_scope, refresh_danger, review_snapshot,
        )
        try:
            events = refresh_danger(
                raw, previous_raw=existing_rec.raw if mode == "merge" and existing_rec else None,
                source="wizard", client=request.remote_addr or "")
        except ValueError as error:
            return jsonify({"ok": False, "errors": [str(error)]}), 400
        errors, warnings = records_store.validate_candidate(
            raw, daily_dir, previous_raw=existing_rec.raw if existing_rec else None)
        if errors:
            return jsonify({"ok": False, "errors": errors}), 400

        def scope_for(snapshot):
            if mode != "merge":
                return None
            from src.dimensions import from_chinese
            dimensions = {from_chinese(p["dim"]).english_name for p in wizard_store.PARTS
                          if draft["parts"].get(p["part"], {}).get("status")
                          in ("observed", "manual")}
            return merge_scope(snapshot, dimensions, draft.get("inquiry") or {})

        def review_response(snapshot, status=200, error=None):
            scope = scope_for(snapshot)
            payload = {
                "ok": False, "need_danger_ack": True,
                "danger_token": snapshot["token"],
                "danger": [{"key": key,
                            **records_store.DANGER_FLAGS.get(
                                key, {"name": key, "sign": "", "note": ""}),
                            **snapshot["evaluations"].get(key, {}),
                            "evidence": snapshot["evidence"].get(key, []),
                            "can_dismiss": scope is None or key in scope}
                           for key in snapshot["pending"]],
            }
            if error:
                payload["error"] = error
            return jsonify(payload), status

        snapshot = review_snapshot(raw)
        if snapshot["pending"] and not acknowledge:
            return review_response(snapshot)
        if acknowledge:
            decisions = acknowledge if isinstance(acknowledge, dict) else {
                key: "dismiss" if acknowledge == "fix" else "keep"
                for key in snapshot["pending"]}
            try:
                apply_decision(raw, token, decisions, scope_for(snapshot),
                               source="wizard", client=request.remote_addr or "")
            except DangerReviewConflict as error:
                return review_response(review_snapshot(raw), 409, str(error))
            except ValueError as error:
                return jsonify({"ok": False, "error": str(error)}), 400

        from src.derived import current_derived_meta
        raw["derived_meta"] = current_derived_meta(DailyRecord(raw))
        errors, warnings = records_store.validate_candidate(
            raw, daily_dir, previous_raw=existing_rec.raw if existing_rec else None)
        if errors:
            return jsonify({"ok": False, "errors": errors}), 400

        # 每次提交登记当前代 pristine；恢复与撤销只使用该快照链。
        from lifecycle_store import create_pristine_snapshot
        raw["pristine_snapshot"] = create_pristine_snapshot(raw, backup_dir)
        raw.pop("restore_state", None)
        # 落盘：覆盖旧档前备份（merge 与重新分析都动旧档）
        os.makedirs(daily_dir, exist_ok=True)
        target = records_store.select_daily_file(daily_dir, today) or \
            os.path.join(daily_dir, f"{today}_analysis.json")
        from io_utils import WriteConflictError, atomic_write_json, file_version, write_lock
        draft_file = wizard_store.draft_path(daily_dir, today)
        from src.dimensions import from_chinese
        covered = existing_rec.get_dimension_coverage() if mode == "merge" and existing_rec else {}
        allowed_parts = [p["part"] for p in wizard_store.PARTS
                         if draft["parts"].get(p["part"], {}).get("status") == "observed"
                         and not covered.get(from_chinese(p["dim"]), False)]
        from photo_store import commit_photos, rollback_photos
        transaction = {"moves": []}
        try:
            transaction = commit_photos(
                draft, photos_dir, today, allowed_parts, backup_dir)
            if os.path.exists(target):
                records_store.backup_file(target, backup_dir, purpose="wizard")
            with write_lock(daily_dir):
                if file_version(draft_file) != draft_version:
                    raise WriteConflictError(draft_file)
                if file_version(target) != record_version:
                    raise WriteConflictError(target)
                atomic_write_json(target, raw, record_version)
                wizard_store.discard_draft(daily_dir, today, draft_version)
        except ValueError as error:
            return jsonify({"ok": False, "error": str(error)}), 400
        except Exception:
            rollback_photos(transaction)
            raise
        return jsonify({"ok": True, "date": today, "warnings": warnings,
                        "danger_acknowledged": acknowledge or None,
                        "cleared": events["cleared"], "revived": events["revived"]})


    def settings_values() -> dict:
        values = {}
        for k in VISION_KEYS + LLM_KEYS + ["WEB_ADMIN_TOKEN", "WEB_HOST"]:
            v = cfg(k)
            values[k] = {
                "set": bool(v),
                "value": "" if k in SECRET_KEYS else v,
                "source": "环境变量" if boot_env.get(k) else (".env" if v else "未设置"),
            }
        return values

    def is_env_locked(key):
        return bool(boot_env.get(key))

    def _env_locked():
        return [k for k in VISION_KEYS + LLM_KEYS +
                ["WEB_ADMIN_TOKEN", "WEB_HOST", "VISION_DISABLED", "LLM_DISABLED",
                 "TCM_KB_ROOT", "TCM_KB_CONSTITUTION_ROOT", "TCM_KB_DIET_ROOT",
                 "TCM_KB_FORMULA_ROOT", "TCM_KB_STRICT_CATEGORIES",
                 "TCM_KB_CONSTITUTION_DISABLED", "TCM_KB_DIET_DISABLED",
                 "TCM_KB_FORMULA_DISABLED"] if is_env_locked(k)]

    def render_settings(**extra):
        bound_host = app.config.get("BOUND_HOST") or cfg("WEB_HOST", "127.0.0.1")
        host_is_lan = is_lan_host(bound_host)
        extra = {"welcome": False, "saved": False, "host_changed": False,
                 "env_error": "", "locked": "", "kb_reset": "", **extra}
        from src.retrieval import KB_CATEGORY_DEFS, inspect_kb_categories
        allowed = admin_allowed()
        categories = inspect_kb_categories(kb_cfg) if allowed else {}
        import_roots = {category: os.path.join(os.path.abspath(data_root),
                                               "private_kb", category)
                        for category in KB_CATEGORY_DEFS}
        return render_template(
            "settings.html", page="settings", values=settings_values(),
            kb_categories=categories, kb_category_defs=KB_CATEGORY_DEFS,
            kb_import_roots=import_roots,
            kb_strict=cfg("TCM_KB_STRICT_CATEGORIES") == "1",
            env_locked=_env_locked(), read_only=not admin_allowed(),
            llm_disabled=llm_disabled(), vision_disabled=vision_disabled(),
            lan_ip=_lan_ip() if host_is_lan else "",
            bound_host=bound_host, bound_port=app.config.get("BOUND_PORT", 8600),
            host_is_lan=host_is_lan, **extra)

    @app.get("/settings")
    def settings():
        return render_settings(
            welcome=request.args.get("welcome") == "1",
            saved=request.args.get("saved") == "1",
            host_changed=request.args.get("host_changed") == "1",
            locked=request.args.get("locked", ""),
            env_error=request.args.get("env_error", ""),
            kb_reset=request.args.get("kb_reset", ""))

    @app.post("/settings/login")
    def settings_login():
        if not admin_allowed():
            return render_settings(env_error="管理口令不正确"), 403
        return redirect("/")

    @app.post("/settings")
    def settings_save():
        if not admin_allowed():
            return render_settings(env_error="无权限：局域网访问需正确管理口令"), 403
        f = request.form
        for key in ("VISION_TEMPERATURE", "VISION_TIMEOUT", "VISION_MAX_TOKENS",
                    "LLM_MAX_TOKENS", "LLM_TIMEOUT"):
            value = f.get(key, "").strip()
            if value:
                try:
                    _validate_vision_number(key, value)
                except ValueError as e:
                    return render_settings(env_error=str(e)), 400
        from safe_fetch import validate_url
        for key in ("VISION_BASE_URL", "LLM_BASE_URL"):
            value = f.get(key, "").strip()
            if value:
                try:
                    validate_url(value)
                except RuntimeError as e:
                    return render_settings(env_error=str(e)), 400
        updates = {}
        skipped = []
        # 机密键：留空 = 不修改；勾选「清除」= 显式删除
        for k in ("VISION_API_KEY", "LLM_API_KEY", "WEB_ADMIN_TOKEN"):
            if is_env_locked(k):
                if k in f or "CLEAR_" + k in f:
                    skipped.append(k)
                continue
            if f.get("CLEAR_" + k):
                updates[k] = ""
            elif f.get(k):
                updates[k] = f[k]
        # 普通键：只更新本表单实际提交的键（缺席 = 不碰，空串 = 显式置空）
        for k in ("VISION_MODEL", "VISION_BASE_URL", "VISION_TEMPERATURE",
                  "VISION_TIMEOUT", "VISION_MAX_TOKENS", "LLM_MODEL",
                  "LLM_BASE_URL", "LLM_MAX_TOKENS", "LLM_TIMEOUT"):
            if k in f:
                if is_env_locked(k):
                    skipped.append(k)
                else:
                    updates[k] = f[k].strip()
        for prefix in ("VISION", "LLM"):
            key = prefix + "_DISABLED"
            if "FORM_" + prefix not in f:
                continue
            if is_env_locked(key):
                skipped.append(key)
            else:
                updates[key] = "" if f.get(prefix + "_ENABLED") else "1"
        # 监听地址提示只在真改了 WEB_HOST 时出现——必须先读旧值再写回
        host_flag = ""
        if "WEB_HOST" in f:
            if is_env_locked("WEB_HOST"):
                skipped.append("WEB_HOST")
            else:
                cur = envfile.effective("WEB_HOST", env_path, "127.0.0.1")
                candidate_token = updates.get(
                    "WEB_ADMIN_TOKEN", envfile.effective("WEB_ADMIN_TOKEN", env_path))
                try:
                    new_v = _validated_host(f["WEB_HOST"], env_path, candidate_token)
                except ValueError as e:
                    return render_settings(env_error=str(e)), 400
                updates["WEB_HOST"] = new_v
                if new_v != cur:
                    host_flag = "&host_changed=1"
        try:
            with env_lock:
                envfile.write_env(env_path, updates)
        except envfile.EnvDecodeError as e:
            return redirect(f"/settings?env_error={str(e)}")
        except ValueError as e:
            return render_settings(env_error=str(e)), 400
        locked_flag = "&locked=" + ",".join(dict.fromkeys(skipped)) if skipped else ""
        return redirect(f"/settings?saved=1{host_flag}{locked_flag}")

    @app.post("/settings/toggle")
    def settings_toggle():
        if not admin_allowed():
            return jsonify({"ok": False, "error": "会话已失效，请重新验证管理口令"}), 403
        body = json_object()
        target = body.get("target")
        enabled = body.get("enabled")
        if target not in ("vision", "llm") or not isinstance(enabled, bool):
            return jsonify({"ok": False, "error": "开关参数必须为模型类别和布尔值"}), 400
        prefix = target.upper()
        key = prefix + "_DISABLED"
        if is_env_locked(key):
            return jsonify({"ok": False, "error": f"{key} 已被环境变量锁定"}), 409
        try:
            with env_lock:
                envfile.write_env(env_path, {key: "" if enabled else "1"})
        except (envfile.EnvDecodeError, ValueError) as error:
            return jsonify({"ok": False, "error": str(error)}), 400
        return jsonify({"ok": True, "target": target, "enabled": enabled,
                        "disabled": not enabled})

    kb_routes.register_kb_routes(
        app, admin_allowed=admin_allowed, is_env_locked=is_env_locked,
        env_lock=env_lock, data_root=data_root, env_path=env_path,
        envfile=envfile, render_settings=render_settings)

    @app.post("/settings/models")
    def settings_models():
        """从配置的端点拉取可用模型列表（供设置页下拉选择）。"""
        if not admin_allowed():
            return jsonify({"ok": False, "error": "无权限：需管理口令"}), 403
        from safe_fetch import same_origin, validate_url
        body = json_object()
        target = body.get("target")
        url_override = body.get("base_url") or ""
        key_override = body.get("api_key") or ""
        if not isinstance(url_override, str) or not isinstance(key_override, str):
            return jsonify({"ok": False, "error": "端点和 API Key 必须为字符串"}), 400
        url_override = url_override.strip()
        key_override = key_override.strip()
        if target == "vision":
            prefix = "VISION"
        elif target == "llm":
            prefix = "LLM"
        else:
            return jsonify({"ok": False, "error": f"未知目标 {target!r}"}), 400
        saved_url, saved_key = cfg(prefix + "_BASE_URL"), cfg(prefix + "_API_KEY")
        if is_env_locked(prefix + "_BASE_URL"):
            url_override = ""
        url = url_override or saved_url
        key = key_override or saved_key
        try:
            validate_url(url)
            if not key_override and url_override \
                    and (not saved_url or not same_origin(saved_url, url)):
                return jsonify({"ok": False,
                                "error": "换用不同源端点时必须同时输入新的 API Key"}), 400
            return jsonify({"ok": True, "models": llm_client.list_models(url, key)})
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)})

    @app.post("/settings/test")
    def settings_test():
        if not admin_allowed():
            return jsonify({"ok": False, "detail": "无权限：需管理口令"}), 403
        target = json_object().get("target")
        try:
            if target == "vision":
                import base64
                import vision_client
                options = _vision_options()
                if not options["key"]:
                    return jsonify({"ok": False,
                                    "detail": "未配置 VISION_API_KEY，连通性测试已取消"}), 400
                with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
                    tf.write(base64.b64decode(_TINY_PNG_B64))
                    tmp = tf.name
                try:
                    dt, _ = vision_client.call(
                        tmp, "这是一张测试图，只回复两个字：正常",
                        **{**options, "timeout": 60})
                finally:
                    os.unlink(tmp)
                return jsonify({"ok": True, "detail": f"连通正常 · 耗时 {dt}s"})
            if target == "llm":
                dt = llm_client.ping(cfg("LLM_MODEL"), cfg("LLM_BASE_URL"),
                                     cfg("LLM_API_KEY"))
                return jsonify({"ok": True, "detail": f"连通正常 · 耗时 {dt}s"})
            return jsonify({"ok": False, "detail": f"未知测试目标 {target!r}"}), 400
        except ValueError as e:
            return jsonify({"ok": False, "detail": str(e)}), 400
        except RuntimeError as e:
            return jsonify({"ok": False, "detail": str(e)})
        except Exception as e:  # 连通性测试的失败必须可见，不静默
            return jsonify({"ok": False, "detail": f"{type(e).__name__}: {e}"})

    return app


def _is_non_loopback_host(value) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except (TypeError, ValueError):
        return False
    mapped = getattr(address, "ipv4_mapped", None)
    return not (mapped or address).is_loopback


def _validated_host(value, env_path, token=None):
    value = value.strip().lower() or "127.0.0.1"
    if value == "localhost":
        return value
    try:
        address = ipaddress.ip_address(value)
    except ValueError as error:
        raise ValueError(f"WEB_HOST 地址无效: {value!r}") from error
    if token is None:
        token = envfile.effective("WEB_ADMIN_TOKEN", env_path)
    if _is_non_loopback_host(address.compressed) and not token:
        raise ValueError("非回环监听必须先设置 WEB_ADMIN_TOKEN")
    return address.compressed


def _lan_ip() -> str:
    """本机局域网 IP（UDP 探测默认路由网卡，不实际发包）；探测失败返回空串。"""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("192.0.2.1", 80))  # TEST-NET-1，仅用于让内核选路
        return s.getsockname()[0]
    except OSError:
        return ""
    finally:
        s.close()


def main():
    parser = argparse.ArgumentParser(description="六维望诊 Web 层")
    parser.add_argument("--lan", action="store_true",
                        help="绑 0.0.0.0 开放局域网（需先设 WEB_ADMIN_TOKEN）")
    parser.add_argument("--port", type=int, default=8600)
    args = parser.parse_args()

    app = create_app()
    env_path = os.path.join(_REPO_ROOT, ".env")
    try:
        host = _validated_host(
            "0.0.0.0" if args.lan else envfile.effective(
                "WEB_HOST", env_path, "127.0.0.1"), env_path)
    except ValueError as e:
        parser.error(str(e))
    app.config.update(BOUND_HOST=host, BOUND_PORT=args.port)
    display_host = f"[{host}]" if ":" in host else host
    print(f"六维望诊 Web 层 → http://{display_host}:{args.port}", file=sys.stderr)
    serve_http(app, host=host, port=args.port)


if __name__ == "__main__":
    main()
