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
import datetime
import importlib
import json
import os
import re
import secrets
import sys
import tempfile

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (_REPO_ROOT, os.path.join(_REPO_ROOT, "scripts"),
           os.path.dirname(os.path.abspath(__file__))):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from flask import Flask, abort, jsonify, redirect, render_template, request, \
    send_file, send_from_directory

import envfile
import llm_client
import mdmini
import records_store
import trends_store
import wizard_store
from src import paths
from src.record import DailyRecord

# 设置页管理的键（顺序即页面展示顺序）
VISION_KEYS = ["VISION_API_KEY", "VISION_MODEL", "VISION_BASE_URL",
               "VISION_TEMPERATURE", "VISION_TIMEOUT"]
LLM_KEYS = ["LLM_API_KEY", "LLM_MODEL", "LLM_BASE_URL"]
SECRET_KEYS = {"VISION_API_KEY", "LLM_API_KEY", "WEB_ADMIN_TOKEN"}

# 64×64 暖纸色 PNG（连通性测试用图，不携带任何真实内容）。
# 注意不能用 1×1：DashScope 等端点要求图片边长 > 10px（实测 400 报错）。
_TINY_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAEAAAABACAIAAAAlC+aJAAAAgElEQVR4nNXOMQ0AIBDAwFL/ZplImBDxA+kpuHXPpkziJE7iJE7iJE7iJE7iJE7iJE7iJE7iJE7iJE7iJE7iJE7iJE7iJE7iJE7iJE7iJE7iJE7iJE7iJE7iJE7iJE7iJE7iJE7iJE7iJE7iJE7iJM7fgakHW94DYirHifcAAAAASUVORK5CYII="
)


def create_app(env_file: str | None = None,
               data_root: str | None = None) -> Flask:
    app = Flask(__name__)
    env_path = env_file or os.path.join(_REPO_ROOT, ".env")
    # 进程启动时的环境变量快照：_configure_vision() 会把生效配置注入
    # os.environ 供 vision_client 读取；若 cfg() 读 live os.environ，
    # 注入值会反过来压住 .env 的后续修改（自我锁存——改了配置却不生效）。
    boot_env = dict(os.environ)
    data_root = data_root or paths.DATA_ROOT
    daily_dir = os.path.join(data_root, "records", "daily")
    photos_dir = os.path.join(data_root, "records", "photos")
    backup_dir = os.path.join(data_root, "records", "_backup")
    app.jinja_env.filters["markdown"] = mdmini.render

    def cfg(key: str, default: str = "") -> str:
        """生效值：启动时的环境变量快照优先，其次 .env（不读 live os.environ，
        防 _configure_vision 的注入自我锁存）。"""
        return boot_env.get(key) or envfile.read_env(env_path).get(key) or default

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

    # 每次进程启动生成新口令 → 重启后声明页必重新确认
    boot_token = secrets.token_hex(8)

    @app.before_request
    def require_boot_ack():
        # guide 是只读公开文档且被 welcome 页引用，必须在门禁之外
        if request.endpoint in ("welcome", "welcome_ack", "license_text",
                                "guide", "guide_doc", "guide_images", "static"):
            return None
        if request.cookies.get("boot_ack") != boot_token:
            return redirect("/welcome")
        return None

    @app.context_processor
    def inject_flags():
        return {"vision_missing": not vision_configured()}

    @app.get("/welcome")
    def welcome():
        return render_template("welcome.html", page="welcome")

    @app.post("/welcome")
    def welcome_ack():
        resp = redirect("/" if vision_configured() else "/settings")
        resp.set_cookie("boot_ack", boot_token)
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
        today = datetime.date.today().isoformat()
        month = request.args.get("m", "")
        if not _MONTH_RE.match(month):
            month = today[:7]
        summaries = records_store.list_summaries(daily_dir)
        return render_template(
            "index.html", page="index",
            summaries=summaries[:7],
            stats=records_store.week_stats(summaries, today),
            cal=records_store.calendar_month(daily_dir, month, today),
            empty=not summaries,
            sev=records_store.sev_class,
        )

    @app.post("/demo")
    def load_demo():
        """空库引导：载入合成示例记录（fixture 自述为合成数据）。"""
        if not admin_allowed():
            return redirect("/")
        date = records_store.load_demo(daily_dir)
        return redirect(f"/record/{date}")

    @app.get("/record/<date>")
    def record_detail(date):
        if not _DATE_RE.match(date):
            abort(404)
        rec = records_store.load_record(daily_dir, date)
        if rec is None:
            abort(404)
        diag = rec.raw.get("diagnosis")
        return render_template(
            "record.html", page="index",
            r=records_store.record_detail(rec),
            report=(diag.get("report") if isinstance(diag, dict) else None),
            llm_configured=bool(cfg("LLM_API_KEY") and cfg("LLM_MODEL")
                                and cfg("LLM_BASE_URL")),
            photos=records_store.list_photos(photos_dir, date),
            sev=records_store.sev_class,
        )

    @app.post("/record/<date>/report")
    def record_report(date):
        """生成/重新生成辨证报告（辨证 LLM → Markdown → 写回记录 JSON）。"""
        if not admin_allowed():
            return jsonify({"ok": False, "error": "无权限：需管理口令"}), 403
        if not _DATE_RE.match(date):
            abort(404)
        result = trends_store.generate_and_store_report(
            daily_dir, backup_dir, date,
            lambda: (cfg("LLM_MODEL"), cfg("LLM_BASE_URL"), cfg("LLM_API_KEY")))
        return jsonify(result), 200 if result["ok"] else 400

    @app.get("/trends")
    def trends():
        today = datetime.date.today().isoformat()
        target = request.args.get("week", "")
        if not _DATE_RE.match(target):
            target = today
        payload = trends_store.week_payload(daily_dir, target)
        latest = None
        if payload is None:
            all_dates = records_store.list_dates(daily_dir)  # 降序
            if all_dates:
                latest = all_dates[0]  # 最近有记录的一天
        t = datetime.date.fromisoformat(target)
        return render_template(
            "trends.html", page="trends", week=payload,
            latest_with_records=latest,
            prev_week=(t - datetime.timedelta(days=7)).isoformat(),
            next_week=(t + datetime.timedelta(days=7)).isoformat(),
            is_current=target == today,
        )

    @app.post("/record/<date>/field")
    def record_update_field(date):
        """修正一个观察值：validator ❌ 拦截 / ⚠️ 放行展示；成功后前端整页刷新。"""
        if not admin_allowed():
            return jsonify({"ok": False, "errors": ["无权限：需管理口令"]}), 403
        if not _DATE_RE.match(date):
            abort(404)
        body = request.json or {}
        result = records_store.update_observation(
            daily_dir, backup_dir, date,
            str(body.get("dim", "")), str(body.get("indicator", "")),
            str(body.get("value", "")))
        status = 200 if result["ok"] else 400
        return jsonify(result), status

    @app.post("/record/<date>/restore")
    def record_restore(date):
        """恢复为首次修正前的原始记录（最早备份 = LLM 原始输出；
        恢复前当前状态自动备份，可再撤销）。"""
        if not admin_allowed():
            return jsonify({"ok": False, "error": "无权限：需管理口令"}), 403
        if not _DATE_RE.match(date):
            abort(404)
        result = records_store.restore_original(daily_dir, backup_dir, date)
        return jsonify(result), (200 if result["ok"] else 400)

    @app.get("/photos/<date>/<path:filename>")
    def photo(date, filename):
        """原图对照：仅服务 records/photos/<date>/ 下的图片文件。"""
        if not _DATE_RE.match(date):
            abort(404)
        return send_from_directory(os.path.join(photos_dir, date), filename)

    # ---------------- 拍照向导（切片 4） ----------------

    def _configure_vision():
        """把当前生效的视觉配置注入环境变量（vision_client 模块级读取）。"""
        os.environ["VISION_MODEL"] = cfg("VISION_MODEL", "qwen3.8-max")
        os.environ["VISION_BASE_URL"] = llm_client.normalize_chat_url(
            cfg("VISION_BASE_URL",
                "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"))
        os.environ["VISION_API_KEY"] = cfg("VISION_API_KEY")

    @app.get("/wizard")
    def wizard():
        today = datetime.date.today().isoformat()
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
        body = request.json or {}
        part = str(body.get("part", ""))
        indicator = str(body.get("indicator", ""))
        value = str(body.get("value", "")).strip()
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
        # 封闭选项即时校验（与详情页修正同口径，防词表外措辞静默 0 分）
        opts = records_store._field_options(dim, indicator)
        if opts and value not in opts:
            return jsonify({"ok": False, "error":
                            f"值不在封闭词表内: {value}"}), 400
        today = datetime.date.today().isoformat()
        draft = wizard_store.load_draft(daily_dir, today)
        st = draft["parts"].get(part, {})
        # 只允许修订已识图部位——防凭空造「无照片伪观察」（虚增覆盖度/
        # photo_coverage/confidence），也保住「声明正常」的审计痕迹
        if st.get("status") != "observed" or not isinstance(
                st.get("observation"), dict):
            return jsonify({"ok": False, "error":
                            "该部位未识图，无观察值可修正"}), 400
        node = st["observation"]
        for k in shapes["B"][:-1]:
            node = node.setdefault(k, {})
            if not isinstance(node, dict):
                return jsonify({"ok": False, "error": "草稿结构异常"}), 400
        node[shapes["B"][-1]] = value
        wizard_store.save_draft(daily_dir, draft)
        # 即时红线反馈（全草稿 + 问诊答案，与 assemble 探测同口径）
        all_obs = {pt: s.get("observation")
                   for pt, s in draft["parts"].items() if s.get("observation")}
        all_obs["inquiry"] = draft.get("inquiry") or {}
        danger = wizard_store.detect_danger(all_obs)
        return jsonify({"ok": True, "danger": danger,
                        "danger_names": [records_store.DANGER_FLAGS.get(
                            k, {}).get("name", k) for k in danger]})

    @app.post("/wizard/inquiry")
    def wizard_inquiry():
        """向导问诊步（手足温凉）：答案写入草稿。"""
        if not admin_allowed():
            return jsonify({"ok": False, "error": "无权限：需管理口令"}), 403
        body = request.json or {}
        today = datetime.date.today().isoformat()
        draft = wizard_store.load_draft(daily_dir, today)
        if body.get("clear_all"):
            # 清除全部问诊已选（用户主动清空，不留痕迹）
            draft["inquiry"] = {}
            wizard_store.save_draft(daily_dir, draft)
            return jsonify({"ok": True})
        answer = (body.get("answer") or "").strip()
        question = (body.get("question") or wizard_store.INQUIRY_SPEC["key"]).strip()
        # 键名白名单：只接受 17 个既定问诊键（防任意键注入记录 inquiry）
        known = {wizard_store.INQUIRY_SPEC["key"]} | {
            i["q"] for i in wizard_store.INQUIRY_ITEMS}
        if question not in known:
            return jsonify({"ok": False, "error": f"未知问诊项: {question}"}), 400
        draft.setdefault("inquiry", {})
        if answer:
            draft["inquiry"][question] = answer
        else:
            draft["inquiry"].pop(question, None)
        wizard_store.save_draft(daily_dir, draft)
        return jsonify({"ok": True})

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
        today = datetime.date.today().isoformat()
        day_dir = os.path.join(photos_dir, today)
        os.makedirs(day_dir, exist_ok=True)
        img_path = os.path.join(day_dir, f"{part}{ext}")
        file.save(img_path)

        if not vision_configured():
            return jsonify({"ok": False, "photo_saved": True,
                            "error": "照片已保存，但未配置视觉模型——请到设置页配置后重试识图"}), 400
        _configure_vision()
        try:
            observe_json, _ = wizard_store.observe_photo(part, img_path)
        except RuntimeError as e:
            return jsonify({"ok": False, "photo_saved": True, "error": str(e)}), 502
        node, unmapped = wizard_store.map_observation(part, observe_json)
        draft = wizard_store.load_draft(daily_dir, today)
        draft["parts"][part] = {"status": "observed", "observation": node,
                                "photo": f"{part}{ext}"}
        wizard_store.save_draft(daily_dir, draft)
        return jsonify({"ok": True, "observation": node,
                        "unmapped": unmapped,
                        "photo": f"/photos/{today}/{part}{ext}"})

    @app.post("/wizard/skip")
    def wizard_skip():
        if not admin_allowed():
            return jsonify({"ok": False, "error": "无权限：需管理口令"}), 403
        body = request.json or {}
        part = body.get("part", "")
        mode = body.get("mode", "")
        if part not in wizard_store.PART_BY_NAME or mode not in ("normal", "uncovered"):
            return jsonify({"ok": False, "error": "参数错误"}), 400
        today = datetime.date.today().isoformat()
        draft = wizard_store.load_draft(daily_dir, today)
        draft["parts"][part] = {"status": f"skip_{mode}"}
        wizard_store.save_draft(daily_dir, draft)
        return jsonify({"ok": True})

    @app.post("/wizard/submit")
    def wizard_submit():
        if not admin_allowed():
            return jsonify({"ok": False, "error": "无权限：需管理口令"}), 403
        body = request.json or {}
        mode = body.get("mode", "new")          # new（整体重建）| merge（只补未覆盖）
        acknowledge = body.get("acknowledge", "")  # "keep"=已复核保留 | "fix"=误判去修正
        today = datetime.date.today().isoformat()
        draft = wizard_store.load_draft(daily_dir, today)

        pending = [p["part"] for p in wizard_store.PARTS
                   if draft["parts"].get(p["part"], {}).get("status") == "pending"
                   or p["part"] not in draft["parts"]]
        if pending:
            return jsonify({"ok": False,
                            "error": f"还有未处理的部位：{'、'.join(pending)}"}), 400

        existing_rec = records_store.load_record(daily_dir, today)
        with open(os.path.join(_REPO_ROOT, "VERSION"), encoding="utf-8") as vf:
            version = vf.read().strip()
        try:
            raw = wizard_store.assemble_record(
                draft, version,
                existing_raw=existing_rec.raw if existing_rec else None,
                merge_only_uncovered=(mode == "merge"))
        except ValueError as e:
            return jsonify({"ok": False, "error": str(e)}), 400

        # 「误判去修正」：用户判定红线为误判 → 移入 not_triggered 后落盘，
        # 再去详情页修正底层观察值（与「保留警示」语义分岔）
        if acknowledge == "fix":
            df = raw.get("danger_flags", {})
            raw["danger_flags"] = {
                "triggered": [],
                "not_triggered": sorted(set(
                    df.get("not_triggered", [])) | set(df.get("triggered", []))),
            }

        # 校验：先临时档过 validator，❌ 拦截
        errors, warnings = records_store.validate_candidate(raw, daily_dir)
        blocking = [e for e in errors if e.startswith("❌")]
        if blocking:
            return jsonify({"ok": False, "errors": blocking}), 400

        # 危险信号：未确认则返回给前端弹拦截层
        triggered = wizard_store.danger_triggered(raw)
        if triggered and not acknowledge:
            return jsonify({
                "ok": False, "need_danger_ack": True,
                "danger": [{"key": k,
                            **records_store.DANGER_FLAGS.get(
                                k, {"name": k, "sign": "", "note": ""})}
                           for k in triggered]})

        # 落盘：覆盖旧档前备份（merge 与重新分析都动旧档）
        os.makedirs(daily_dir, exist_ok=True)
        target = records_store.select_daily_file(daily_dir, today) or \
            os.path.join(daily_dir, f"{today}_analysis.json")
        if os.path.exists(target):
            records_store.backup_file(target, backup_dir)
        with open(target, "w", encoding="utf-8") as f:
            json.dump(raw, f, ensure_ascii=False, indent=2)
        wizard_store.discard_draft(daily_dir, today)
        return jsonify({"ok": True, "date": today, "warnings": warnings,
                        "danger_acknowledged": acknowledge or None})


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

    def _env_locked():
        return [k for k in VISION_KEYS + LLM_KEYS + ["WEB_ADMIN_TOKEN", "WEB_HOST"]
                if boot_env.get(k)]

    @app.get("/settings")
    def settings():
        return render_template(
            "settings.html", page="settings", values=settings_values(),
            env_locked=_env_locked(),
            read_only=not admin_allowed(),
            token_arg=request.args.get("token", ""),
            welcome=request.args.get("welcome") == "1",
            saved=request.args.get("saved") == "1",
            env_error=request.args.get("env_error", ""),
            lan_ip=_lan_ip(),
        )

    @app.post("/settings")
    def settings_save():
        if not admin_allowed():
            return render_template("settings.html", page="settings",
                                   values=settings_values(),
                                   env_locked=_env_locked(),
                                   read_only=True, token_arg="", welcome=False,
                                   saved=False,
                                   env_error="无权限：局域网访问需正确管理口令"), 403
        f = request.form
        updates = {}
        # 机密键：留空 = 不修改；勾选「清除」= 显式删除
        for k in ("VISION_API_KEY", "LLM_API_KEY", "WEB_ADMIN_TOKEN"):
            if f.get("CLEAR_" + k):
                updates[k] = ""
            elif f.get(k):
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

    @app.post("/settings/models")
    def settings_models():
        """从配置的端点拉取可用模型列表（供设置页下拉选择）。"""
        if not admin_allowed():
            return jsonify({"ok": False, "error": "无权限：需管理口令"}), 403
        body = request.json or {}
        target = body.get("target")
        # 表单里未保存的值优先（先填端点→拉列表→再保存的引导顺序）；
        # 机密 key 未输入新值时回落到已保存配置
        url_override = (body.get("base_url") or "").strip()
        key_override = (body.get("api_key") or "").strip()
        if target == "vision":
            url, key = cfg("VISION_BASE_URL"), cfg("VISION_API_KEY")
        elif target == "llm":
            url, key = cfg("LLM_BASE_URL"), cfg("LLM_API_KEY")
        else:
            return jsonify({"ok": False, "error": f"未知目标 {target!r}"}), 400
        url = url_override or url
        key = key_override or key
        try:
            return jsonify({"ok": True, "models": llm_client.list_models(url, key)})
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)})

    @app.post("/settings/test")
    def settings_test():
        if not admin_allowed():
            return jsonify({"ok": False, "detail": "无权限：需管理口令"}), 403
        target = (request.json or {}).get("target")
        try:
            if target == "vision":
                import base64
                import vision_client
                _configure_vision()  # 注入生效配置（含端点规整）
                importlib.reload(vision_client)  # 模块级 MODEL/URL 在 import 时读取
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
    host = "0.0.0.0" if args.lan else envfile.effective("WEB_HOST", env_path,
                                                        "127.0.0.1")
    if host == "0.0.0.0" and not envfile.effective("WEB_ADMIN_TOKEN", env_path):
        print("[web][warn] 局域网模式但未设 WEB_ADMIN_TOKEN——设置页对局域网只读",
              file=sys.stderr)
    print(f"六维望诊 Web 层 → http://{host}:{args.port}", file=sys.stderr)
    app.run(host=host, port=args.port)


if __name__ == "__main__":
    main()
