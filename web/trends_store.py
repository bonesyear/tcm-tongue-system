"""趋势页数据装配；报告相关实现由 report_store/kb_evidence 提供，保留兼容转发。"""
from __future__ import annotations

import generate_weekly_report as gwr
from src.dimensions import DIMENSIONS
import kb_evidence
import records_store
import report_store

MAX_KB_EXCERPT_CHARS = kb_evidence.MAX_KB_EXCERPT_CHARS
MAX_KB_TOTAL_CHARS = kb_evidence.MAX_KB_TOTAL_CHARS
_REPORT_LOCKS = report_store._REPORT_LOCKS
_deduplicate_report = report_store._deduplicate_report


def week_payload(daily_dir: str, target: str) -> dict | None:
    """target 日起往前 7 天的周报数据（ECharts 直接可消费的结构）。

    x 轴为连续 7 天（无记录的日期留 None，不断列——对应「正常 0 分与
    无数据可区分」原则）。无记录返回 None。
    """
    from date_utils import add_days, parse_date
    target_d = parse_date(target)
    if target_d is None:
        return None
    dates = []
    for offset in range(6, -1, -1):
        day = add_days(target_d, -offset)
        if day is not None:
            dates.append(day.isoformat())
    rec_by_date = {}
    for d in dates:
        rec = records_store.load_record(daily_dir, d)
        if rec and rec.date:
            raw = rec.raw
            if rec.date != d:
                import sys
                print(f"⚠️ 警告: 记录文件日期 {d} 与内部 date {rec.date} 不一致；"
                      "趋势按文件名日期处理", file=sys.stderr)
                raw = dict(raw)
                raw["date"] = d
            rec_by_date[d] = raw
    if not rec_by_date:
        return None

    recs = [rec_by_date[d] for d in dates if d in rec_by_date]
    data = gwr.generate_weekly_report_data(recs)

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

    first_d = next(iter(rec_by_date))
    last_d = next(reversed(rec_by_date))
    return {
        "week_id": data["week_id"],
        "start_date": dates[0],
        "end_date": dates[-1],
        "count": len(recs),
        "unknown_count": data["unknown_counts"]["total"],
        "rule_versions": data["rule_versions"],
        "mixed_rule_versions": data["mixed_rule_versions"],
        "scoring_ruleset_version": data["scoring_ruleset_version"],
        "dates": [d[5:] for d in dates],
        "dim_series": dim_series,
        "radar": {"axes": axes,
                  "first_date": first_d, "last_date": last_d,
                  "first": [tm_by_date[first_d].get(a) for a in axes],
                  "last": [tm_by_date[last_d].get(a) for a in axes]},
        "heat": {"axes": axes, "rows": heat_rows},
        "trend_rows": [{"k": _TREND_LABELS.get(k, k), "v": v}
                       for k, v in data["trend_analysis"].items() if v],
        "weekly_comparison": data["weekly_comparison"],
        "summary": data["summary"],
        "next_week_suggestion": data["next_week_suggestion"],
    }


_TREND_LABELS = {
    "舌质变化": "舌质", "舌苔变化": "舌苔", "舌形变化": "舌形",
    "舌下络脉变化": "舌下络脉", "head_face_trend": "头面诊",
    "eye_trend": "目诊", "ear_trend": "耳诊", "hand_trend": "手诊",
    "skin_trend": "皮肤诊", "体质变化趋势": "体质总览",
}


def _all_obs_values(rec):
    return report_store._all_obs_values(rec)


def _all_evidence_values(rec):
    return report_store._all_evidence_values(rec)


def report_state(rec, kb_info=None, kb_categories=None) -> dict:
    return report_store.report_state(rec, kb_info=kb_info, kb_categories=kb_categories)


def build_report_input(rec, kb_refs: list | None = None,
                       kb_status: str | None = None) -> str:
    return report_store.build_report_input(rec, kb_refs=kb_refs, kb_status=kb_status)


def _kb_references(rec, kb_root=None, max_hits: int = 10,
                   anchor_terms=None, category=None) -> list:
    return kb_evidence._kb_references(rec, kb_root=kb_root, max_hits=max_hits,
                                      anchor_terms=anchor_terms, category=category)


def _template_version(template_path: str) -> str:
    return report_store._template_version(template_path)


def _llm_positive_int(key, value, default):
    return report_store._llm_positive_int(key, value, default)


def _report_lock(daily_dir, date_str):
    return report_store._report_lock(daily_dir, date_str)


def generate_and_store_report(daily_dir: str, backup_dir: str, date_str: str,
                              llm_cfg, timezone_name=None, kb_references=None) -> dict:
    return report_store.generate_and_store_report(
        daily_dir, backup_dir, date_str, llm_cfg, timezone_name,
        kb_references=kb_references)
