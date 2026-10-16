"""记录存取层：records/daily 的扫描、选档与页面视图模型。

把「文件 → DailyRecord → 页面所需 dict」的复杂度收敛在这里，
app.py 只负责路由。选档规则与 scripts/generate_weekly_report.py 的
_select_daily_file 同口径（规范名优先；否则排除备份/临时后取 mtime 最新，
多份候选打 stderr 警告）。
"""
from __future__ import annotations

import datetime
import glob
import json
import os
import re
import shutil
import sys

from src import paths
from src.dimensions import DIMENSIONS
from src.record import DailyRecord
from src.scoring import DIMENSION_RULES, score, score_indicators

# 与 generate_weekly_report._SUSPECT_ARCHIVE_RE 同口径：备份/临时快照不参与选档
_SUSPECT_ARCHIVE_RE = re.compile(r"\.bak|copy|tmp|_旧格式", re.IGNORECASE)
_DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})")

# 退出评分层的字段：只展示不打分（KNOWN_ISSUES #5 点刺 / #18 掌温）
REF_FIELDS = {
    "prickles": "退出评分层，仅供辨证（需肉眼确认）",
    "palm_temp": "照片不可判，已降级为参考项",
}

# 修正选项（web 层 UI 数据，不进 src 核心库契约）：
# 有评分词表的字段直接用 DIMENSION_RULES 的 key 作选项（选中即得分，消灭
# 「词表外措辞静默读 0 分」）；无评分词表的字段（照片不可判、降级到辨证层）
# 用下方人工词表——用户肉眼/触诊给出权威值，只入档案供辨证，不参与评分。
FIELD_OPTIONS = {
    "body_luster":          ["荣润", "少华", "枯"],
    "prickles":             ["无", "少量", "点刺", "芒刺"],  # 留存词表复活
    "body_dynamics":        ["正常", "颤动", "歪斜", "痿软", "强硬"],
    "coating_distribution": ["满布", "偏布一侧", "苔少"],
    "lip_around":           ["正常", "发暗", "红肿", "疱疹"],
    "nose_color":           ["正常", "红赤", "青黑", "枯槁"],
    "nose_bleeding":        ["无", "少量", "较多"],
    "palm_temp":            ["温", "凉", "不温", "厥冷"],     # 留存词表复活
}

# 词表无 0 分基线词时给修正 UI 补的「正常」选项：措辞落在 validator 的
# 正常/否定语义豁免区（input_validator 对「未见」类描述不做词表覆盖告警），
# 且不命中任何评分关键词 → 0 分 = 正常，方向正确。
NORMAL_OPTION = "未见异常"


def _field_options(dim, indicator: str):
    """修正 UI 的封闭选项；无词表且未人工指定时返回 None（回落自由文本）。"""
    rules = DIMENSION_RULES.get(dim, {}).get(indicator)
    if rules:
        opts = list(rules.keys())
        if not any(v == 0 for v in rules.values()):
            opts.insert(0, NORMAL_OPTION)
        return opts
    return FIELD_OPTIONS.get(indicator)

# 待复核字段：照常评分，但需肉眼签认（2026-10-16 P1 原著审查；
# 手册 user-guide.md「识图结果需肉眼确认的体征」清单 + 原著危重鉴别点）
REVIEW_FIELDS = {
    "jaundice": "急性黄疸红线相关，需肉眼复核",
    "face_color": "红赤需与戴阳鉴别复核（太阳面赤 vs 戴阳面红如妆）",
    "sublingual_varicosity": "血证核心体征，需肉眼复核",
    "tooth_marks": "识图抖动高发字段，需肉眼复核",
    "coating_greasy": "识图抖动高发字段，需肉眼复核",
    "coating_thickness": "识图抖动高发字段，需肉眼复核",
}

# 「未拍摄（用户声明正常）」占位检测（单一事实来源在 src/record.py）
from src.record import DECLARED_NORMAL_MARK  # noqa: F401

# 指标 → 页面中文短标签（与 web/design 设计稿一致）
INDICATOR_LABELS = {
    "body_color": "颜色", "body_luster": "光泽", "body_size": "形态",
    "petechiae": "瘀斑瘀点", "tooth_marks": "齿痕", "fissure": "裂纹",
    "prickles": "点刺", "body_dynamics": "动态",
    "coating_color": "苔色", "coating_thickness": "厚薄",
    "coating_moisture": "润燥", "coating_greasy": "腻腐",
    "coating_peeling": "剥落", "coating_distribution": "分布",
    "sublingual_color": "颜色", "sublingual_thickness": "粗细",
    "sublingual_varicosity": "迂曲", "sublingual_petechiae": "瘀点",
    "face_color": "面色", "face_edema": "浮肿", "face_luster": "光泽",
    "lip_color": "唇色", "lip_moisture": "润燥", "lip_around": "口周",
    "nose_color": "鼻色", "nose_flare": "煽动", "nose_bleeding": "出血",
    "redness": "目赤", "jaundice": "巩膜黄染", "edema": "浮肿",
    "dark_orbit": "目眶黯黑", "sclera_color": "巩膜颜色",
    "lower_lid": "下睑颜色",
    "color": "颜色/肤色", "helix": "耳轮",
    "palm_color": "手掌颜色", "palm_temp": "手掌温度",
    "nail_color": "甲床颜色", "nail_shape": "甲床形态",
    "ecchymosis": "瘀斑",
    "cuo": "甲错", "yellow_sweat": "黄汗", "dryness": "干燥",
}

# 维度 → 展示分组（舌诊按 舌质/舌苔/舌下络脉，头面按 面/唇/鼻，其余单组）
DIM_GROUPS = {
    "tongue": [
        ("舌质", ["body_color", "body_luster", "body_size", "petechiae",
                  "tooth_marks", "fissure", "prickles", "body_dynamics"]),
        ("舌苔", ["coating_color", "coating_thickness", "coating_moisture",
                  "coating_greasy", "coating_peeling", "coating_distribution"]),
        ("舌下络脉", ["sublingual_color", "sublingual_thickness",
                     "sublingual_varicosity", "sublingual_petechiae"]),
    ],
    "head_face": [
        ("面域", ["face_color", "face_edema", "face_luster"]),
        ("唇域", ["lip_color", "lip_moisture", "lip_around"]),
        ("鼻域", ["nose_color", "nose_flare", "nose_bleeding"]),
    ],
    "eye": [("目", ["redness", "jaundice", "edema", "dark_orbit", "sclera_color",
                    "lower_lid"])],
    "ear": [("耳", ["color", "helix"])],
    "hand": [("手", ["palm_color", "palm_temp", "nail_color", "nail_shape",
                     "ecchymosis"])],
    "skin": [("皮肤", ["color", "cuo", "yellow_sweat", "edema", "dryness"])],
}

# 危险信号字典（键对齐 templates/multi_dim_record_template.json，
# 中文名对齐 templates/adaptive_analysis_prompt.md §4.5；
# sign = 体征，拦截弹层与红线横幅展示用。
# 注明：镜面舌/焦黑苔/舌体短缩「中风先兆」为通用诊断学概念，
# 非《经方探源》本文（该书「舌强不能语」为中风已病，小续命汤证 L946）
DANGER_FLAGS = {
    "daiyang":         {"name": "戴阳证",
                        "sign": "面红如妆 + 手足厥逆（可兼身反不恶寒、掀衣揭被、脉暴出）",
                        "note": "真阳欲脱，严禁解表发汗，立即就医（原著救治方向：通脉四逆加猪胆汤，须医师面诊）"},
    "skin_cold":       {"name": "肤冷脉微", "sign": "皮肤触之冰冷 + 脉微",
                        "note": "真阳衰竭，立即就医"},
    "flesh_wasted":    {"name": "大肉已脱", "sign": "大肉已脱 + 大骨陷下",
                        "note": "精血枯竭，预后不良，建议就医"},
    "tongue_rigid":    {"name": "舌体强硬", "sign": "舌体短缩强硬 + 言语不利",
                        "note": "中风先兆（通用诊断学说法），立即就医"},
    "tongue_critical": {"name": "舌象危重", "sign": "舌质紫暗 + 苔焦黑干裂",
                        "note": "危重症（通用诊断学说法），立即就医"},
    "mirror_tongue":   {"name": "镜面舌",   "sign": "舌面光剥无苔（镜面舌）+ 极度消瘦",
                        "note": "重症消耗（通用诊断学说法），立即就医"},
    "acute_jaundice":  {"name": "急性黄疸", "sign": "巩膜黄染 + 皮肤黄如橘皮",
                        "note": "急性肝胆重症，紧急就医"},
    "wind_stroke":     {"name": "中风重症", "sign": "口不能言 + 身体不收",
                        "note": "中风重症（风痱），立即就医"},
    "throat_erosion":  {"name": "狐惑重症",
                        "sign": "默默欲眠、恶闻食臭、面目乍赤乍黑乍白、蚀喉声嗄",
                        "note": "狐惑（厥阴本病，原著有甘草泻心汤方向），建议尽快就医"},
    "yangming_critical": {"name": "阳明危重", "sign": "神昏谵语、循衣摸床、微喘直视",
                        "note": "阳明病危重证（212条），紧急就医"},
    "collapse_yang":   {"name": "脱阳前兆", "sign": "神识昏昧 + 冷汗如油",
                        "note": "真阳外脱前兆，紧急就医"},
}

_WEEKDAYS = "一二三四五六日"


def sev_class(value):
    """分数 → 等级 class：0 正常 / 1-3 轻 / 4-6 中 / 7-10 重 / None 未覆盖。"""
    if value is None:
        return "sev-none"
    if value == 0:
        return "sev-0"
    if value <= 3:
        return "sev-1"
    if value <= 6:
        return "sev-4"
    return "sev-7"


def weekday_cn(date_str: str) -> str:
    d = datetime.date.fromisoformat(date_str)
    return "周" + _WEEKDAYS[d.weekday()]


def _select_daily_file(daily_dir: str, date_str: str):
    """三级选档（与周报脚本同口径）。无候选返回 None。"""
    exact = os.path.join(daily_dir, f"{date_str}_analysis.json")
    if os.path.exists(exact):
        return exact
    matches = [m for m in glob.glob(os.path.join(daily_dir, f"{date_str}*analysis*.json"))
               if not _SUSPECT_ARCHIVE_RE.search(os.path.basename(m))]
    if not matches:
        return None
    filepath = max(matches, key=os.path.getmtime)
    if len(matches) > 1:
        print(f"⚠️ 警告: {date_str} 有多份非规范命名的 analysis 候选: "
              f"{sorted(os.path.basename(m) for m in matches)}；"
              f"选用 mtime 最新者 {os.path.basename(filepath)}", file=sys.stderr)
    return filepath


# 公开别名：跨模块调用不走私有名
select_daily_file = _select_daily_file


def validate_candidate(raw: dict, workdir: str):
    """候选记录先写临时档过 input_validator；返回 (errors, warnings)。

    ❌ 级由调用方决定是否拦截；⚠️/ℹ️ 仅展示。临时档即写即删。
    """
    from input_validator import validate_record
    os.makedirs(workdir, exist_ok=True)
    tmp = os.path.join(workdir, ".validate-candidate.json")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(raw, f, ensure_ascii=False, indent=2)
        _, errors, warnings = validate_record(tmp)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return errors, warnings


def backup_file(filepath: str, backup_dir: str) -> str:
    """把 filepath 复制到 backup_dir（原名 + 时间戳 .bak），返回备份路径。"""
    os.makedirs(backup_dir, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = os.path.join(backup_dir, f"{os.path.basename(filepath)}.{stamp}.bak")
    shutil.copyfile(filepath, backup)
    return backup


def list_dates(daily_dir: str):
    """扫描 records/daily，返回有记录的日期列表（降序）。"""
    dates = set()
    for f in glob.glob(os.path.join(daily_dir, "*analysis*.json")):
        m = _DATE_RE.match(os.path.basename(f))
        if m:
            dates.add(m.group(1))
    return sorted(dates, reverse=True)


def load_record(daily_dir: str, date_str: str):
    """选档并解析为 DailyRecord；无记录或解析失败返回 None。"""
    filepath = _select_daily_file(daily_dir, date_str)
    if not filepath:
        return None
    try:
        with open(filepath, encoding="utf-8") as f:
            return DailyRecord(json.load(f))
    except (OSError, json.JSONDecodeError) as e:
        print(f"⚠️ 警告: 记录 {filepath} 解析失败: {e}", file=sys.stderr)
        return None


def _is_declared_normal(obs: dict) -> bool:
    """该维度是否只有「未拍摄（用户声明正常）」占位（P1：不计覆盖）。"""
    return any(v == DECLARED_NORMAL_MARK for v in obs.values())


def _dim_scores(rec: DailyRecord):
    """每维 (score 或 None, 是否覆盖)。未覆盖维度 score 为 None（与 0 分区分）；
    声明正常占位维度同样按未覆盖处理（P1 原著审查：占位≠亲眼所见）。"""
    out = {}
    for dim in DIMENSIONS:
        obs = rec.get_observation(dim)
        if dim.is_covered(obs) and not _is_declared_normal(obs):
            out[dim.chinese_name] = round(score(dim, obs), 1)
        else:
            out[dim.chinese_name] = None
    return out


def record_summary(rec: DailyRecord) -> dict:
    """列表/日历用的单日摘要。"""
    dims = _dim_scores(rec)
    covered = sum(1 for v in dims.values() if v is not None)
    total = round(sum(v for v in dims.values() if v is not None), 1)
    return {
        "date": rec.date,
        "weekday": weekday_cn(rec.date) if rec.date else "",
        "coverage": covered,
        "coverage_total": len(DIMENSIONS),
        "dims": dims,
        "total": total,
        "total_sev": sev_class(total / len(DIMENSIONS) if covered else None),
    }


def list_summaries(daily_dir: str):
    """全部记录的摘要（按日期降序）；解析失败/无 date 的跳过。"""
    out = []
    for date_str in list_dates(daily_dir):
        rec = load_record(daily_dir, date_str)
        if rec and rec.date:
            out.append(record_summary(rec))
    return out


def calendar_month(daily_dir: str, month: str, today: str):
    """一个月的历网格（周一开头），供模板直接渲染。

    返回 {"month": "2026-06", "label": "2026 年 6 月", "weeks": [[cell,...]]}，
    cell = {"day": int|None, "date", "has", "today", "dots": [sev...], "total", "sev"}。
    """
    year, mon = int(month[:4]), int(month[5:7])
    by_date = {}
    for date_str in list_dates(daily_dir):
        if date_str.startswith(month):
            rec = load_record(daily_dir, date_str)
            if rec and rec.date:
                by_date[date_str] = record_summary(rec)

    first = datetime.date(year, mon, 1)
    days = (datetime.date(year + (mon == 12), mon % 12 + 1, 1)
            - datetime.timedelta(days=1)).day
    cells = [{"day": None}] * first.weekday()
    for d in range(1, days + 1):
        date_str = f"{year:04d}-{mon:02d}-{d:02d}"
        s = by_date.get(date_str)
        cell = {"day": d, "date": date_str, "has": bool(s), "today": date_str == today}
        if s:
            cell["dots"] = [sev_class(v) for v in s["dims"].values()]
            cell["total"] = f'{s["total"]:.1f}'
            cell["sev"] = s["total_sev"]
        cells.append(cell)
    weeks = [cells[i:i + 7] for i in range(0, len(cells), 7)]
    prev_m = (first - datetime.timedelta(days=1)).strftime("%Y-%m")
    next_first = datetime.date(year + (mon == 12), mon % 12 + 1, 1)
    return {"month": month, "label": f"{year} 年 {mon} 月", "weeks": weeks,
            "prev": prev_m, "next": next_first.strftime("%Y-%m")}


def week_stats(summaries, today: str):
    """本周记录天数 / 连续记录天数 / 本周平均总偏离度。"""
    today_d = datetime.date.fromisoformat(today)
    week_start = today_d - datetime.timedelta(days=today_d.weekday())
    by_date = {s["date"]: s for s in summaries}
    this_week = [by_date.get((week_start + datetime.timedelta(days=i)).isoformat())
                 for i in range(7)]
    this_week = [s for s in this_week if s]
    # 连续天数：从最近一条记录日往前逐日回数
    streak = 0
    if summaries:
        cur = datetime.date.fromisoformat(summaries[0]["date"])
        while cur.isoformat() in by_date:
            streak += 1
            cur -= datetime.timedelta(days=1)
    avg = round(sum(s["total"] for s in this_week) / len(this_week), 1) if this_week else None
    return {"week_days": len(this_week), "streak": streak, "week_avg": avg}


def load_demo(daily_dir: str) -> str:
    """把合成示例记录拷入 records/daily（空库引导用）。返回日期。"""
    src = os.path.join(paths.REPO_ROOT, "tests", "fixtures",
                       "2026-06-25_analysis.json")
    os.makedirs(daily_dir, exist_ok=True)
    shutil.copyfile(src, os.path.join(daily_dir, "2026-06-25_analysis.json"))
    return "2026-06-25"


# ============================================================
# 修正流（切片 3）：形状感知写回 + 校验拦截 + 备份 + 打标
# ============================================================

def _write_path(rec: DailyRecord, dim, indicator: str):
    """指标在当前记录形状下的写入路径（容器链 + 键路径）。

    返回 (container, path)；调用方负责逐层 setdefault 后写入叶子。
    """
    from src.record import _DIMENSION_INDICATORS, _A_VISION_KEYS, _C_KEY_ALIASES
    paths_map = _DIMENSION_INDICATORS[dim][indicator]
    shape = rec.shape
    if shape == "B":
        container = rec.raw.setdefault("observations", {})
        node = container.setdefault(dim.english_name, {})
        return node, paths_map["B"]
    if shape == "C":
        key = dim.english_name
        if key not in rec.raw:
            for alias, canonical in _C_KEY_ALIASES.items():
                if canonical == key and alias in rec.raw:
                    key = alias
                    break
        return rec.raw.setdefault(key, {}), paths_map["C"]
    # 形状 A：容器新名优先，旧名永久兼容（与读取同序）
    container_key = next((k for k in _A_VISION_KEYS if k in rec.raw),
                         _A_VISION_KEYS[0])
    container = rec.raw.setdefault(container_key, {})
    return container.setdefault(dim.chinese_name, {}), paths_map["A"]


def update_observation(daily_dir: str, backup_dir: str, date_str: str,
                       dim_key: str, indicator: str, value: str) -> dict:
    """修正一个观察值：校验 → 备份 → 形状感知写回 → 打标 → 重评分。

    返回 {"ok", "errors", "warnings", ...}。validator 的 ❌ 级错误拦截保存
    （不留半成品），⚠️ 级仅回传展示。文件替换用「临时文件 + os.replace」，
    中途崩溃不损坏原档。
    """
    from src.dimensions import from_english
    from src.record import _DIMENSION_INDICATORS

    dim = from_english(dim_key)
    if dim is None or indicator not in _DIMENSION_INDICATORS.get(dim, {}):
        return {"ok": False, "errors": [f"未知的维度或指标: {dim_key}/{indicator}"],
                "warnings": []}
    filepath = _select_daily_file(daily_dir, date_str)
    if not filepath:
        return {"ok": False, "errors": [f"{date_str} 无记录"], "warnings": []}
    try:
        with open(filepath, encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        return {"ok": False, "errors": [f"记录读取失败: {e}"], "warnings": []}

    rec = DailyRecord(raw)
    node, path = _write_path(rec, dim, indicator)
    if not isinstance(node, dict):
        return {"ok": False, "errors": ["记录结构异常：维度节点不是对象"],
                "warnings": []}
    for key in path[:-1]:
        node = node.setdefault(key, {})
        if not isinstance(node, dict):
            return {"ok": False, "errors": [f"记录结构异常：{key} 不是对象"],
                    "warnings": []}
    node[path[-1]] = value.strip()
    raw["manually_corrected"] = True
    raw["corrected_at"] = datetime.datetime.now().isoformat(timespec="seconds")

    # 临时档先校验，❌ 拦截（原档不动）；通过则备份旧版 → 原子替换
    tmp = filepath + ".validate-tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(raw, f, ensure_ascii=False, indent=2)
        from input_validator import validate_record
        _, errors, warnings = validate_record(tmp)
        blocking = [e for e in errors if e.startswith("❌")]
        if blocking:
            return {"ok": False, "errors": blocking, "warnings": warnings}
        backup = backup_file(filepath, backup_dir)
        os.replace(tmp, filepath)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)

    new_rec = DailyRecord(raw)
    obs = new_rec.get_observation(dim)
    scored = score_indicators(dim, obs)
    return {
        "ok": True,
        "errors": [],
        "warnings": warnings,
        "backup": os.path.basename(backup),
        "field_score": scored.get(indicator),
        "dim_score": round(score(dim, obs), 1) if dim.is_covered(obs) else None,
        "summary": record_summary(new_rec),
    }


def list_photos(photos_dir: str, date_str: str):
    """records/photos/<date>/ 下的照片文件名列表（排序）。"""
    d = os.path.join(photos_dir, date_str)
    if not os.path.isdir(d):
        return []
    ok = (".jpg", ".jpeg", ".png", ".webp")
    return sorted(f for f in os.listdir(d) if f.lower().endswith(ok))


def record_detail(rec: DailyRecord) -> dict:
    """单日详情页的完整视图模型。"""
    dims = []
    for dim in DIMENSIONS:
        obs = rec.get_observation(dim)
        covered = dim.is_covered(obs)
        declared_normal = covered and _is_declared_normal(obs)
        scored = score_indicators(dim, obs) if covered and not declared_normal else {}
        groups = []
        for gname, indicators in DIM_GROUPS[dim.english_name]:
            fields = []
            for ind in indicators:
                v = obs.get(ind, "")
                base = {"k": INDICATOR_LABELS.get(ind, ind), "v": v, "ind": ind,
                        "opts": _field_options(dim, ind)}
                if ind in REF_FIELDS:
                    fields.append({**base, "s": None, "ref": REF_FIELDS[ind]})
                elif ind in scored:
                    fields.append({**base, "s": scored[ind],
                                   "review": REVIEW_FIELDS.get(ind)})
                else:
                    # 有规则集之外的指标（如舌体动态/舌苔分布）：设计稿口径按 0 展示
                    fields.append({**base, "s": 0})
            # 空组不展示（该维度未覆盖时整组无值）
            if any(f["v"] for f in fields):
                groups.append({"name": gname, "fields": fields})
        positives = [v for v in scored.values() if v > 0]
        dims.append({
            "key": dim.english_name, "name": dim.chinese_name,
            "covered": covered and not declared_normal,
            "declared_normal": declared_normal,
            "score": round(score(dim, obs), 1) if scored else None,
            "max_indicator": max(positives) if positives else None,
            "groups": groups,
        })

    total = round(sum(d["score"] for d in dims if d["score"] is not None), 1)
    covered_n = sum(1 for d in dims if d["covered"])

    # 辨证与方剂（形状 A/B/C 已由 DailyRecord 归一）
    pattern = rec.get_pattern_differentiation()
    formula = rec.get_formula()
    diagnosis = None
    if pattern or formula:
        tv = pattern.get("three_views") or pattern.get("三观") or {}
        fp = pattern.get("four_patterns") or pattern.get("四证") or {}
        ingredients = []
        if isinstance(formula, dict):
            for item in formula.get("ingredients") or []:
                if isinstance(item, dict):
                    ingredients.append({"herb": item.get("herb", ""),
                                        "dosage": item.get("dosage", "")})
                elif isinstance(item, (list, tuple)) and len(item) >= 2:
                    ingredients.append({"herb": item[0], "dosage": item[1]})
        diagnosis = {
            "three_views": [{"k": k, "v": v} for k, v in tv.items()],
            "four_patterns": [{"k": k, "v": v} for k, v in fp.items()],
            "six_diseases": pattern.get("six_diseases", ""),
            "pathomechanism": pattern.get("core_pathomechanism", ""),
            "formula": {
                "name": formula.get("name", "") if isinstance(formula, dict) else "",
                "ingredients": ingredients,
                "rationale": formula.get("rationale", "") if isinstance(formula, dict) else "",
                "note": formula.get("note", "") if isinstance(formula, dict) else "",
            } if formula else None,
        }

    triggered = rec.get_triggered_danger_flags()
    return {
        "date": rec.date,
        "weekday": weekday_cn(rec.date) if rec.date else "",
        "coverage": covered_n,
        "coverage_total": len(DIMENSIONS),
        "confidence": rec.get_confidence(),
        "version": rec.get_version(),
        "corrected": bool(rec.raw.get("manually_corrected")),
        "dims": dims,
        "total": total,
        "total_sev": sev_class(total / len(DIMENSIONS) if covered_n else None),
        "danger_triggered": [
            {"key": k, **DANGER_FLAGS.get(k, {"name": k, "note": ""})}
            for k in triggered],
        "danger_all": [v["name"] for v in DANGER_FLAGS.values()],
        "diagnosis": diagnosis,
        "template_version": rec.raw.get("prompt_template_version")
            or rec.get_version(),
    }
