"""趋势页数据装配 + 辨证报告生成。

趋势页数据全部来自 scripts/generate_weekly_report.py 的纯函数 dict
（禁止服务端 matplotlib，AGENTS.md 锁定）；报告生成走 web/llm_client。
"""
from __future__ import annotations

import datetime
import json
import os

import generate_weekly_report as gwr
from src.dimensions import DIMENSIONS

import records_store


def week_payload(daily_dir: str, target: str) -> dict | None:
    """target 日起往前 7 天的周报数据（ECharts 直接可消费的结构）。

    x 轴为连续 7 天（无记录的日期留 None，不断列——对应「正常 0 分与
    无数据可区分」原则）。无记录返回 None。
    """
    target_d = datetime.date.fromisoformat(target)
    dates = [(target_d - datetime.timedelta(days=i)).isoformat()
             for i in range(6, -1, -1)]
    rec_by_date = {}
    for d in dates:
        rec = records_store.load_record(daily_dir, d)
        if rec and rec.date:
            rec_by_date[d] = rec.raw
    if not rec_by_date:
        return None

    recs = [rec_by_date[d] for d in dates if d in rec_by_date]
    data = gwr.generate_weekly_report_data(recs)

    # 连续 7 天轴：无记录日 None（折线 connectNulls:false 断线、热力留空）；
    # 声明正常占位维度同样为 None（占位≠已观测，副作用修复）
    dev_by_date = {}
    for d in rec_by_date:
        rec = records_store.DailyRecord(rec_by_date[d])
        devs = gwr.compute_dimension_deviation(rec_by_date[d])
        for dim in DIMENSIONS:
            if records_store._is_declared_normal(rec.get_observation(dim)):
                devs[dim.chinese_name] = None
        dev_by_date[d] = devs
    dim_series = {}
    for dim in DIMENSIONS:
        cn = dim.chinese_name
        dim_series[cn] = [dev_by_date[d].get(cn) if d in dev_by_date else None
                          for d in dates]

    tm_by_date = {d: gwr.extract_tongue_metrics(rec_by_date[d]) for d in rec_by_date}
    flag_by_date = {d: gwr.extract_tongue_observation_flags(rec_by_date[d])
                    for d in rec_by_date}
    tongue_declared = {d: records_store._is_declared_normal(
            records_store.DailyRecord(rec_by_date[d]).get_observation("tongue"))
        for d in rec_by_date}
    axes = list(next(iter(tm_by_date.values())).keys()) if tm_by_date else []
    heat_rows = []
    for d in dates:
        if d in tm_by_date and not tongue_declared[d]:
            tm, fl = tm_by_date[d], flag_by_date[d]
            heat_rows.append([tm.get(a) if fl.get(a) else None for a in axes])
        else:
            heat_rows.append([None] * len(axes))

    first_d, last_d = recs[0]["date"], recs[-1]["date"]
    return {
        "week_id": data["week_id"],
        "start_date": dates[0],
        "end_date": dates[-1],
        "count": len(recs),
        "dates": [d[5:] for d in dates],
        "dim_series": dim_series,
        "radar": {"axes": axes,
                  "first": [tm_by_date[first_d].get(a) for a in axes],
                  "last": [tm_by_date[last_d].get(a) for a in axes]},
        "heat": {"axes": axes, "rows": heat_rows},
        "trend_rows": [{"k": _TREND_LABELS.get(k, k), "v": v}
                       for k, v in data["trend_analysis"].items() if v],
        "weekly_comparison": data["weekly_comparison"],
        "summary": data["summary"],
        "next_week_suggestion": data["next_week_suggestion"],
    }


# 趋势解读标签（与 web/design/pages/trends.html 的 labels 锁定表一致）
_TREND_LABELS = {
    "舌质变化": "舌质", "舌苔变化": "舌苔", "舌形变化": "舌形",
    "舌下络脉变化": "舌下络脉", "head_face_trend": "头面诊",
    "eye_trend": "目诊", "ear_trend": "耳诊", "hand_trend": "手诊",
    "skin_trend": "皮肤诊", "体质变化趋势": "体质总览",
}


def _all_obs_values(rec):
    """全部维度的观察值文本（禁忌核对扫描用）。"""
    for dim in DIMENSIONS:
        yield from rec.get_observation(dim).values()


def _all_evidence_values(rec):
    """观察值 + 问诊答案（禁忌核对扫描面：戴阳「厥冷」等在问诊里）。"""
    yield from _all_obs_values(rec)
    inquiry = rec.raw.get("inquiry") or {}
    for v in inquiry.values():
        if isinstance(v, dict):
            yield str(v.get("answer", ""))


def build_report_input(rec) -> str:
    """辨证 LLM 的用户输入：观察值 + 评分 + 危险信号 + 置信度。"""
    from src.scoring import score, score_indicators
    lines = [f"日期：{rec.date}", ""]
    for dim in DIMENSIONS:
        obs = rec.get_observation(dim)
        if records_store._is_declared_normal(obs):
            lines.append(f"【{dim.chinese_name}】今日未拍摄（用户声明正常）——"
                         f"按未覆盖处理，不得引为该维度证据")
            continue
        if not dim.is_covered(obs):
            lines.append(f"【{dim.chinese_name}】今日未覆盖")
            continue
        s = score(dim, obs)
        scored = score_indicators(dim, obs)
        lines.append(f"【{dim.chinese_name}】偏离度 {s:.1f}/10")
        for ind, v in scored.items():
            lines.append(f"  - {ind}: {obs.get(ind, '')}（{v} 分）")
        for ind, v in obs.items():
            if ind not in scored and v:
                lines.append(f"  - {ind}: {v}（参考项，不参与评分）")
    triggered = rec.get_triggered_danger_flags()
    lines.append("")
    lines.append("危险信号：" + ("、".join(triggered) if triggered
                                     else f"{len(records_store.DANGER_FLAGS)} 项均未触发"))
    # 禁忌反向核对（P0 原著审查）：把出方禁忌的关键体征显式列给 LLM，
    # 避免「未观测」被误读为「已排除」
    lines.append("禁忌反向核对（出辛温解表剂前必须逐项回应）：")
    for label, keys in [
        ("戴阳/真寒假热（面红如妆、厥逆不温、脉暴出）",
         ["面红如妆", "厥逆", "厥冷", "脉暴"]),
        ("阳明热盛（大热、大汗、大渴、燥矢内结）",
         ["大热", "洪大", "燥矢", "大渴"]),
        ("亡血/伤精（苍白㿠白、唇甲淡白、肌肤甲错）",
         ["苍白", "㿠白", "甲错"]),
        ("黄疸（巩膜黄染、黄如橘皮）", ["黄染", "橘皮"]),
    ]:
        hits = [k for k in keys if any(k in (v or "") for v in _all_evidence_values(rec))]
        lines.append(f"  - {label}：" + ("已观测：" + "、".join(hits)
                                      if hits else "未观测（≠已排除）"))
    lines.append(f"置信度：{rec.get_confidence() or '未知'}")
    # 问诊答案全量进入辨证输入（副作用修复：此前只输出覆盖计数，答案从不进 LLM）
    inquiry = rec.raw.get("inquiry") or {}
    answered = {q: v for q, v in inquiry.items()
                if isinstance(v, dict) and v.get("asked") and v.get("answer")}
    lines.append(f"问诊覆盖：{len(answered)}/16（含手足温凉；未答项 = 未提供，"
                 f"不得推测）")
    for q, v in answered.items():
        lines.append(f"  - {q} {v['answer']}")
    return "\n".join(lines)


def _template_version(template_path: str) -> str:
    """prompt 模板版本 = 文件名 + 内容短哈希（模板无内嵌版本号，哈希可溯源）。"""
    import hashlib
    with open(template_path, "rb") as f:
        digest = hashlib.sha1(f.read()).hexdigest()[:8]
    return f"adaptive_analysis_prompt.md@{digest}"


def generate_and_store_report(daily_dir: str, backup_dir: str, date_str: str,
                              llm_cfg) -> dict:
    """调辨证 LLM 生成 Markdown 报告并写回记录 JSON。

    llm_cfg: 返回 (model, base_url, api_key) 的可调用对象。
    返回 {"ok", "error"|...}；写回前备份旧版，写回后过 validator。
    """
    import llm_client

    filepath = records_store.select_daily_file(daily_dir, date_str)
    if not filepath:
        return {"ok": False, "error": f"{date_str} 无记录"}
    rec = records_store.load_record(daily_dir, date_str)
    if rec is None:
        return {"ok": False, "error": "记录解析失败"}

    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    template_path = os.path.join(repo_root, "templates",
                                 "adaptive_analysis_prompt.md")
    with open(template_path, encoding="utf-8") as f:
        system_prompt = f.read()

    model, base_url, api_key = llm_cfg()
    try:
        md = llm_client.chat(build_report_input(rec), system_prompt,
                             model, base_url, api_key)
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}

    # 存储约定：形状 A 的 diagnosis 容器（任务书 §3），报告为其下的 report 子键；
    # 形状 B 记录新增 diagnosis 键不影响形状探测（探测只认 observations）。
    diag = rec.raw.setdefault("diagnosis", {})
    if not isinstance(diag, dict):
        return {"ok": False, "error": "记录的 diagnosis 字段不是对象，写回中止"}
    diag["report"] = {
        "markdown": md,
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "prompt_template_version": _template_version(template_path),
    }
    errors, _ = records_store.validate_candidate(rec.raw, daily_dir)
    blocking = [e for e in errors if e.startswith("❌")]
    if blocking:
        return {"ok": False, "error": "；".join(blocking)}
    records_store.backup_file(filepath, backup_dir)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(rec.raw, f, ensure_ascii=False, indent=2)
    return {"ok": True, "date": date_str}
