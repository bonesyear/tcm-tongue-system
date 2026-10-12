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
    """target 日起往前 7 天的周报数据（ECharts 直接可消费的结构）。"""
    target_d = datetime.date.fromisoformat(target)
    dates = [(target_d - datetime.timedelta(days=i)).isoformat()
             for i in range(6, -1, -1)]
    recs = []
    kept_dates = []
    for d in dates:
        rec = records_store.load_record(daily_dir, d)
        if rec and rec.date:
            recs.append(rec.raw)
            kept_dates.append(rec.date)
    if not recs:
        return None

    data = gwr.generate_weekly_report_data(recs)
    devs = [gwr.compute_dimension_deviation(r) for r in recs]
    dim_series = {}
    for dim in DIMENSIONS:
        cn = dim.chinese_name
        dim_series[cn] = [d.get(cn) for d in devs]

    tms = [gwr.extract_tongue_metrics(r) for r in recs]
    flags = [gwr.extract_tongue_observation_flags(r) for r in recs]
    axes = list(tms[0].keys()) if tms else []
    heat_rows = []
    for tm, fl in zip(tms, flags):
        heat_rows.append([tm.get(a) if fl.get(a) else None for a in axes])

    return {
        "week_id": data["week_id"],
        "start_date": data["start_date"],
        "end_date": data["end_date"],
        "count": len(recs),
        "dates": [d[5:] for d in kept_dates],
        "dim_series": dim_series,
        "radar": {"axes": axes,
                  "first": [tms[0].get(a) for a in axes],
                  "last": [tms[-1].get(a) for a in axes]},
        "heat": {"axes": axes, "rows": heat_rows},
        "trend_analysis": data["trend_analysis"],
        "weekly_comparison": data["weekly_comparison"],
        "summary": data["summary"],
        "next_week_suggestion": data["next_week_suggestion"],
    }


def build_report_input(rec) -> str:
    """辨证 LLM 的用户输入：观察值 + 评分 + 危险信号 + 置信度。"""
    from src.scoring import score, score_indicators
    lines = [f"日期：{rec.date}", ""]
    for dim in DIMENSIONS:
        obs = rec.get_observation(dim)
        if not dim.is_covered(obs):
            lines.append(f"【{dim.chinese_name}】今日未覆盖")
            continue
        s = score(dim, obs)
        lines.append(f"【{dim.chinese_name}】偏离度 {s:.1f}/10")
        for ind, v in score_indicators(dim, obs).items():
            lines.append(f"  - {ind}: {obs.get(ind, '')}（{v} 分）")
        for ind, v in obs.items():
            if ind not in score_indicators(dim, obs) and v:
                lines.append(f"  - {ind}: {v}（参考项，不参与评分）")
    triggered = rec.get_triggered_danger_flags()
    lines.append("")
    lines.append("危险信号：" + ("、".join(triggered) if triggered else "九项均未触发"))
    lines.append(f"置信度：{rec.get_confidence() or '未知'}")
    asked, total = rec.get_inquiry_coverage()
    lines.append(f"问诊覆盖：{asked}/{total}")
    return "\n".join(lines)


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

    with open(os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "templates",
            "adaptive_analysis_prompt.md"), encoding="utf-8") as f:
        system_prompt = f.read()
    with open(os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "VERSION"), encoding="utf-8") as f:
        version = f.read().strip()

    model, base_url, api_key = llm_cfg()
    try:
        md = llm_client.chat(build_report_input(rec), system_prompt,
                             model, base_url, api_key)
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}

    rec.raw["diagnosis_report"] = {
        "markdown": md,
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "prompt_template_version": version,
    }
    errors, _ = records_store.validate_candidate(rec.raw, daily_dir)
    blocking = [e for e in errors if e.startswith("❌")]
    if blocking:
        return {"ok": False, "error": "；".join(blocking)}
    records_store.backup_file(filepath, backup_dir)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(rec.raw, f, ensure_ascii=False, indent=2)
    return {"ok": True, "date": date_str}
