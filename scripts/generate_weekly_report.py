#!/usr/bin/env python3
"""
周报生成器 —— 多维度中医望诊趋势分析
===========================================
功能：
  1. 加载指定日期范围内的每日诊断 JSON 记录
  2. 生成舌象指标雷达图（Radar Chart）
  3. 生成多维度趋势线图（Trend Line Chart）
  4. 输出图表到 <DATA_ROOT>/charts/、周报 JSON 到 <DATA_ROOT>/records/weekly/
     （DATA_ROOT 默认为仓库根，可用环境变量 TCM_DATA_ROOT 覆盖）

依赖：
  - matplotlib >= 3.7
  - numpy >= 1.24

用法：
  python3 scripts/generate_weekly_report.py [YYYY-MM-DD]
  不带参数则使用当前日期。

约束：本模块 import 零副作用（不创建目录）——目录创建在 main() 里做，
避免"import 即在只读路径 makedirs"导致测试收集崩溃（历史 Bug 1）。
"""

import json
import os
import sys
import glob
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any, Union

# 让仓库根可被导入（src 为包）
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from src.record import DailyRecord, has_formula_content  # noqa: E402
from src.dimensions import DIMENSIONS, VisionDimension  # noqa: E402
from src.scoring import score as score_dimension, score_indicators, TONGUE_RADAR_METRIC_KEYS  # noqa: E402
from src import confidence as confidence_mod  # noqa: E402
from src.paths import (  # noqa: E402
    RECORDS_DAILY_DIR as RECORDS_DIR,
    RECORDS_WEEKLY_DIR as WEEKLY_DIR,
    CHARTS_DIR,
    ensure_data_dirs,
)

def _configure_cjk_font(matplotlib) -> Optional[str]:
    """为 matplotlib 配置 CJK 字体（按平台依次尝试已安装字体）。

    不配置时 macOS/裸 Linux 默认 DejaVu Sans 无中文字形，图表标签全为方框。
    找不到候选字体时返回 None（图表仍可生成，仅中文显示降级）。
    """
    candidates = [
        "PingFang SC", "Hiragino Sans GB", "Heiti SC", "STHeiti",   # macOS
        "Noto Sans CJK SC", "Droid Sans Fallback",                   # Linux
        "WenQuanYi Micro Hei", "Microsoft YaHei", "SimHei",          # 其他
    ]
    from matplotlib import font_manager
    installed = {f.name for f in font_manager.fontManager.ttflist}
    for name in candidates:
        if name in installed:
            matplotlib.rcParams["font.sans-serif"] = [name]
            matplotlib.rcParams["axes.unicode_minus"] = False
            return name
    return None


# 维度 → 趋势线配色（顺序与 DIMENSIONS 一致：舌/头面/目/耳/手/皮肤）
_DIMENSION_STYLE = {
    VisionDimension.TONGUE:     ("o-", "#C41E3A", "舌诊综合偏离度"),
    VisionDimension.HEAD_FACE:  ("s--", "#D4770A", "头面诊偏离度"),
    VisionDimension.EYE:        ("^-.", "#2D5016", "目诊偏离度"),
    VisionDimension.EAR:        ("p--", "#8B6914", "耳诊偏离度"),
    VisionDimension.HAND:       ("D:", "#1A6B8A", "手诊偏离度"),
    VisionDimension.SKIN:       ("v-.", "#6B2D8A", "皮肤诊偏离度"),
}

# ============================================================
# 舌象指标 → 数值分数 映射表
# 将中医望诊定性描述转化为 0-10 的定量分数
# ------------------------------------------------------------
# 注：所有映射表与匹配策略已下沉至 Scoring module（src/scoring.py），
# 本脚本仅作为 Record + Scoring 的 adapter，不再持有评分逻辑。
# ============================================================


def load_week_records(target_date: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """
    加载指定日期之前 7 天的所有 daily analysis JSON 记录。

    参数:
        target_date: 目标日期（datetime 对象），默认为当天

    返回:
        list[dict]: 已加载的记录列表，按日期升序排列

    错误处理:
        - JSON 解析失败：跳过该文件并打印警告
        - 目录为空：返回空列表，不报错
        - 文件不存在：静默跳过
    """
    if target_date is None:
        target_date = datetime.now()

    records = []

    for i in range(6, -1, -1):
        day = target_date - timedelta(days=i)
        date_str = day.strftime("%Y-%m-%d")

        # 查找该日期的所有 analysis JSON 文件
        pattern = os.path.join(RECORDS_DIR, f"{date_str}*analysis*.json")
        matches = glob.glob(pattern)

        if not matches:
            # 该日无记录，静默跳过
            continue

        # 同日多份记录时取字典序最新的一份（glob 返回顺序依赖文件系统，
        # 不排序会导致选择不可复现）
        filepath = sorted(matches)[-1]
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                record = json.load(f)
                records.append(record)
        except json.JSONDecodeError as e:
            print(f"⚠️ 警告: 文件 {filepath} JSON 解析失败: {e}", file=sys.stderr)
            continue
        except Exception as e:
            print(f"⚠️ 警告: 读取文件 {filepath} 时出错: {e}", file=sys.stderr)
            continue

    # 按日期排序（确保升序）。key 强制转 str：某条记录的 date 若为数值
    # （如 20260624），str/int 混排比较会抛 TypeError 让整周周报崩溃，
    # 与本函数"坏记录跳过、容错加载"的契约相悖
    records.sort(key=lambda r: str(r.get("date", "")))

    return records


def extract_tongue_metrics(record: Dict[str, Any]) -> Dict[str, float]:
    """
    从单条 daily record 中提取舌象定量指标分数。

    通过 Record module 按维度取观测，再交由 Scoring module 按规范指标打分，
    不再硬编码 doubao_vision_analysis / 舌诊 字段路径。

    参数:
        record: 单日诊断 JSON 记录（dict 或 DailyRecord）

    返回:
        dict: 指标名 → 分数（0-10）
    """
    rec = record if isinstance(record, DailyRecord) else DailyRecord(record)
    obs = rec.get_observation(VisionDimension.TONGUE)
    indicators = score_indicators(VisionDimension.TONGUE, obs)

    # 雷达图 8 指标名 → Scoring 规范指标 key
    return {
        metric_name: float(indicators.get(ind_key, 0))
        for metric_name, ind_key in TONGUE_RADAR_METRIC_KEYS.items()
    }


def compute_dimension_deviation(record: Dict[str, Any]) -> Dict[str, float]:
    """
    计算单条记录各望诊维度的综合偏离度分数（0-10）。

    遍历 Dimension module 的规范六维，Record 取观测 → Scoring 打分，
    不再硬编码中文名 ×48。

    参数:
        record: 单日诊断 JSON 记录（dict 或 DailyRecord）

    返回:
        dict: 维度中文名 → 偏离度分数
    """
    rec = record if isinstance(record, DailyRecord) else DailyRecord(record)
    return {
        dim.chinese_name: score_dimension(dim, rec.get_observation(dim))
        for dim in DIMENSIONS
    }


def describe_trend(name: str, first_val: float, last_val: float,
                   higher_is_worse: bool = True) -> str:
    """
    根据首末两次数值生成中文趋势描述。

    口径说明：只比较周初与周末两天，不反映周中波动。
    """
    delta = round(last_val - first_val, 1)
    if abs(delta) < 0.5:
        return f"{name}整体稳定（{first_val:.1f} → {last_val:.1f}）"

    direction = "升高" if delta > 0 else "降低"
    if (delta > 0 and higher_is_worse) or (delta < 0 and not higher_is_worse):
        implication = "异常程度加重，需持续关注"
    else:
        implication = "异常程度减轻"

    return f"{name}较周初{direction}{abs(delta):.1f}分，{implication}（{first_val:.1f} → {last_val:.1f}）"


def generate_radar_chart(metrics_list: List[Dict[str, float]],
                         dates: List[str]) -> Optional[str]:
    """
    生成舌象指标雷达图。

    参数:
        metrics_list: 多日的舌象指标列表
        dates: 对应的日期标签

    返回:
        str: 图表文件路径，失败返回 None
    """
    try:
        import matplotlib
        matplotlib.use("Agg")  # 非交互后端，无需 GUI
        _configure_cjk_font(matplotlib)
        import matplotlib.pyplot as plt
        import numpy as np
    except ImportError as e:
        print(f"⚠️ 无法导入 matplotlib: {e}", file=sys.stderr)
        return None

    # 雷达图指标（8 个维度）
    categories = [
        "舌质颜色",
        "舌苔厚度",
        "舌苔润燥",
        "齿痕",
        "瘀斑",
        "舌下络脉",
        "裂纹",
        "舌体胖瘦",
    ]
    category_labels = [
        "舌质颜色\n(偏离)",
        "舌苔厚度\n(厚腻)",
        "舌苔润燥\n(燥/滑)",
        "齿痕",
        "瘀斑",
        "舌下络脉\n(迂曲)",
        "裂纹",
        "舌体胖瘦\n(偏离)",
    ]

    N = len(categories)
    angles = np.linspace(0, 2 * np.pi, N, endpoint=False).tolist()
    angles += angles[:1]  # 闭合多边形

    fig, ax = plt.subplots(figsize=(9, 9), subplot_kw=dict(polar=True))
    ax.set_title("舌象指标雷达图 — 周趋势对比", pad=25, fontsize=16,
                 fontweight="bold", color="#2C1810")

    # 配色方案（最多 7 天）
    colors = ["#C41E3A", "#D4770A", "#2D5016", "#1A6B8A",
              "#6B2D8A", "#8B1A1A", "#B8860B"]

    for idx, metrics in enumerate(metrics_list):
        values = [metrics.get(cat, 0) for cat in categories]
        values += values[:1]  # 闭合

        label = dates[idx] if idx < len(dates) else f"Day {idx + 1}"
        color = colors[idx % len(colors)]

        ax.fill(angles, values, alpha=0.08, color=color)
        ax.plot(angles, values, "o-", linewidth=2, color=color,
                label=label, markersize=5)

    ax.set_xticks(angles[:-1])
    ax.set_xticklabels(category_labels, fontsize=10, color="#2C1810")
    ax.set_ylim(0, 10)
    ax.set_yticks([2, 4, 6, 8, 10])
    ax.set_yticklabels(["2", "4", "6", "8", "10"], fontsize=8, color="#666666")
    ax.legend(loc="upper right", bbox_to_anchor=(1.35, 1.1),
              fontsize=9, framealpha=0.9)

    # 保存
    date_tag = dates[-1] if dates else datetime.now().strftime("%Y-%m-%d")
    chart_path = os.path.join(CHARTS_DIR, f"radar_weekly_{date_tag}.png")
    plt.savefig(chart_path, dpi=150, bbox_inches="tight",
                facecolor="#FFFDF7", edgecolor="none")
    plt.close()
    print(f"✅ 雷达图已保存: {chart_path}")
    return chart_path


def generate_trend_chart(records: List[Dict[str, Any]]) -> Optional[str]:
    """
    生成多维度趋势线图（舌诊 + 头面诊 + 目诊 + 耳诊 + 手诊 + 皮肤诊）。

    参数:
        records: 本周的 daily 记录列表

    返回:
        str: 图表文件路径，失败返回 None
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        _configure_cjk_font(matplotlib)
        import matplotlib.pyplot as plt
        import numpy as np
    except ImportError as e:
        print(f"⚠️ 无法导入 matplotlib: {e}", file=sys.stderr)
        return None

    if not records:
        print("⚠️ 无记录，跳过趋势图生成")
        return None

    # 提取日期标签
    dates = [r.get("date", f"Day {i+1}") for i, r in enumerate(records)]
    # 简化日期标签（只取月-日）
    date_labels = [d[-5:] if len(d) >= 10 else d for d in dates]
    x = np.arange(len(records))

    # 计算各维度偏离度（按 Dimension 规范六维遍历，不再硬编码中文名）
    deviations = [compute_dimension_deviation(r) for r in records]

    # ---- 绘制多维度趋势线 ----
    fig, ax = plt.subplots(figsize=(12, 6))
    fig.patch.set_facecolor("#FFFDF7")
    ax.set_facecolor("#FFFDF7")

    for dim in DIMENSIONS:
        series = [d[dim.chinese_name] for d in deviations]
        marker, color, label = _DIMENSION_STYLE[dim]
        ax.plot(x, series, marker, linewidth=2, markersize=7,
                color=color, label=label)

    ax.set_xticks(x)
    ax.set_xticklabels(date_labels, fontsize=10)
    ax.set_ylim(0, 10)
    ax.set_ylabel("偏离度 (0-10，越高越异常)", fontsize=11, color="#2C1810")
    ax.set_title("多维度望诊指标趋势线 — 本周变化", fontsize=15,
                 fontweight="bold", color="#2C1810", pad=15)
    ax.legend(loc="upper left", fontsize=9, framealpha=0.9,
              facecolor="#FFFDF7", edgecolor="#D4A574")
    ax.grid(True, alpha=0.3, linestyle="--", color="#D4A574")
    ax.set_axisbelow(True)

    # 添加辅助线 (5 = 警示线, 8 = 高危线)
    ax.axhline(y=5, color="#FFC107", linestyle=":", alpha=0.5, linewidth=1)
    ax.axhline(y=8, color="#C41E3A", linestyle=":", alpha=0.5, linewidth=1)
    ax.text(len(x) - 0.3, 5.1, "关注线", fontsize=7, color="#FFC107", va="bottom")
    ax.text(len(x) - 0.3, 8.1, "高危线", fontsize=7, color="#C41E3A", va="bottom")

    # 保存
    date_tag = dates[-1] if dates else datetime.now().strftime("%Y-%m-%d")
    chart_path = os.path.join(CHARTS_DIR, f"trend_weekly_{date_tag}.png")
    plt.savefig(chart_path, dpi=150, bbox_inches="tight",
                facecolor=fig.get_facecolor(), edgecolor="none")
    plt.close()
    print(f"✅ 趋势图已保存: {chart_path}")
    return chart_path


def generate_weekly_report_data(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    生成完整的周报数据结构，字段与 weekly_report_template.json 保持一致。

    参数:
        records: 本周记录列表

    返回:
        dict: 周报数据结构
    """
    if not records:
        return {
            "week_id": "",
            "start_date": "",
            "end_date": "",
            "daily_records_count": 0,
            "trend_analysis": {
                "舌质变化": "",
                "舌苔变化": "",
                "舌形变化": "",
                "舌下络脉变化": "",
                "head_face_trend": "",
                "eye_trend": "",
                "ear_trend": "",
                "hand_trend": "",
                "skin_trend": "",
                "体质变化趋势": "",
            },
            "weekly_comparison": {
                "与前一周对比": "",
                "好转指标": [],
                "恶化指标": [],
                "稳定指标": [],
            },
            "summary": "本周无记录",
            "next_week_suggestion": "请至少完成 1 天记录后再生成周报。",
            "confidence_checks": [],
        }

    # 每条记录只构造一次 DailyRecord，供指标提取/偏离度/置信度校验复用
    recs: List[DailyRecord] = [
        r if isinstance(r, DailyRecord) else DailyRecord(r) for r in records
    ]

    first_date = recs[0].date or "unknown"
    last_date = recs[-1].date or "unknown"

    # 计算 week_id（ISO 周：%G-W%V，避免 %U 周日起算导致的跨年错位）
    try:
        last_dt = datetime.strptime(last_date, "%Y-%m-%d")
        week_id = last_dt.strftime("%G-W%V")
    except ValueError:
        week_id = "YYYY-W00"

    # 提取舌象与维度偏离度序列
    tongue_metrics = [extract_tongue_metrics(r) for r in recs]
    deviations = [compute_dimension_deviation(r) for r in recs]

    first_tm = tongue_metrics[0]
    last_tm = tongue_metrics[-1]
    first_dev = deviations[0]
    last_dev = deviations[-1]

    trend_analysis = {
        "舌质变化": describe_trend(
            "舌质颜色偏离度", first_tm["舌质颜色"], last_tm["舌质颜色"]
        ),
        "舌苔变化": (
            describe_trend("舌苔厚度", first_tm["舌苔厚度"], last_tm["舌苔厚度"])
            + "；"
            + describe_trend("舌苔润燥", first_tm["舌苔润燥"], last_tm["舌苔润燥"])
        ),
        "舌形变化": (
            describe_trend("齿痕程度", first_tm["齿痕"], last_tm["齿痕"])
            + "；"
            + describe_trend(
                "舌体胖瘦偏离度", first_tm["舌体胖瘦"], last_tm["舌体胖瘦"]
            )
            + "；"
            + describe_trend("裂纹程度", first_tm["裂纹"], last_tm["裂纹"])
        ),
        "舌下络脉变化": describe_trend(
            "舌下络脉迂曲度", first_tm["舌下络脉"], last_tm["舌下络脉"]
        ),
        "head_face_trend": describe_trend(
            "头面诊偏离度", first_dev["头面诊"], last_dev["头面诊"]
        ),
        "eye_trend": describe_trend(
            "目诊偏离度", first_dev["目诊"], last_dev["目诊"]
        ),
        "ear_trend": describe_trend(
            "耳诊偏离度", first_dev["耳诊"], last_dev["耳诊"]
        ),
        "hand_trend": describe_trend(
            "手诊偏离度", first_dev["手诊"], last_dev["手诊"]
        ),
        "skin_trend": describe_trend(
            "皮肤诊偏离度", first_dev["皮肤诊"], last_dev["皮肤诊"]
        ),
        "体质变化趋势": (
            "体质方向判定需结合问诊与长期趋势；本周以舌/头面/目/耳/手/皮肤"
            "六维望诊证据为主，建议持续记录 2-4 周后再做稳定判定。"
        ),
    }

    # 周报与上周对比：当前无历史周报数据时给出空结构，保留扩展接口
    weekly_comparison = {
        "与前一周对比": "缺少上周周报数据，暂无法与上周进行量化对比",
        "好转指标": [],
        "恶化指标": [],
        "稳定指标": [],
    }

    # 找出本周偏离度最高的维度
    max_dim, max_score = max(last_dev.items(), key=lambda item: item[1])

    summary = (
        f"本周（{first_date} 至 {last_date}）共 {len(records)} 条日分析记录。"
        f"舌诊综合偏离度由 {first_dev['舌诊']:.1f} 变化至 {last_dev['舌诊']:.1f}；"
        f"当前偏离度最高的维度为「{max_dim}」（{max_score:.1f} 分）。"
        f"{trend_analysis['舌质变化']} "
        f"{trend_analysis['head_face_trend']}。"
    )

    if max_score < 3.0:
        next_week_suggestion = (
            "本周各维度偏离度总体较低，建议维持现有六维拍照套餐"
            "（舌+头面+目+耳+手+皮肤），保持规律记录即可。"
        )
    elif max_dim == "舌诊":
        next_week_suggestion = (
            "舌象偏离度最高，下周建议重点观察舌质、舌苔、舌下络脉变化，"
            "必要时补充舌底特写，并结合问诊二便、口渴情况。"
        )
    elif max_dim == "头面诊":
        next_week_suggestion = (
            "头面诊偏离度最高，建议补充目部特写以排除早期巩膜黄染，"
            "同时关注面色寒热、唇润燥及鼻翼煽动变化。"
        )
    elif max_dim == "目诊":
        next_week_suggestion = (
            "目诊偏离度最高，建议优先拍摄双眼特写（白睛、巩膜、眼睑），"
            "以精确判断目赤、黄染及水饮情况。"
        )
    elif max_dim == "耳诊":
        next_week_suggestion = (
            "耳诊偏离度最高，建议侧拍耳部照片，重点观察耳色、耳轮润燥，"
            "并结合听力问诊。"
        )
    elif max_dim == "手诊":
        next_week_suggestion = (
            "手诊偏离度最高，建议拍摄双手掌及甲床特写，重点观察掌温、"
            "甲床颜色与甲错变化。"
        )
    elif max_dim == "皮肤诊":
        next_week_suggestion = (
            "皮肤诊偏离度最高，建议拍摄前臂内侧及小腿皮肤照片，"
            "关注肤色、甲错、黄汗、水肿等指标。"
        )
    else:
        next_week_suggestion = (
            "建议维持六维拍照套餐，持续观察多维指标变化趋势。"
        )

    # ---- confidence 校验断言（调 Confidence module） ----
    # 复核每条记录自报的置信度与实际覆盖维度数是否一致；
    # LOW 不应给方剂（安全边界）。不一致记入 confidence_checks 并打警告。
    confidence_checks = _check_confidence_for_records(recs)

    # 安全边界违反必须在摘要里显式标注，不能只藏在 stderr（历史 Bug 7）
    violations = [c for c in confidence_checks if "safety_violation" in c]
    if violations:
        summary += (
            f"⚠️ 安全边界警示：{len(violations)} 条记录在 LOW 置信度下输出了方剂"
            f"（{', '.join(c['date'] or '未知日期' for c in violations)}），"
            f"详见 confidence_checks。"
        )

    return {
        "week_id": week_id,
        "start_date": first_date,
        "end_date": last_date,
        "daily_records_count": len(records),
        "trend_analysis": trend_analysis,
        "weekly_comparison": weekly_comparison,
        "summary": summary,
        "next_week_suggestion": next_week_suggestion,
        "confidence_checks": confidence_checks,
    }


def _check_confidence_for_records(
        records: List[Union[Dict[str, Any], DailyRecord]]) -> List[Dict[str, Any]]:
    """逐条复核记录的置信度一致性，返回校验结果列表。"""
    checks: List[Dict[str, Any]] = []
    for raw in records:
        rec = raw if isinstance(raw, DailyRecord) else DailyRecord(raw)
        claimed = rec.get_confidence()
        covered = rec.get_covered_dimension_count()
        expected = confidence_mod.from_coverage(covered)
        consistent = confidence_mod.is_consistent(claimed, covered)
        entry: Dict[str, Any] = {
            "date": rec.date,
            "claimed": claimed,
            "covered_dimensions": covered,
            "expected": expected.value,
            "consistent": consistent,
        }
        if not consistent:
            print(
                f"⚠️ 置信度校验: {rec.date} 声称 {claimed}，"
                f"实际覆盖 {covered}/6 维应为 {expected.value}",
                file=sys.stderr,
            )
        # 安全边界：LOW 不应给方剂。
        # 与 input_validator 同一口径：自报等级与覆盖度推断等级取更严格者——
        # 不自报/自报无法解析的记录按推断等级照样检查（防 fail-open）；
        # 方剂内容判定用 has_formula_content（无方名但带药材+剂量同样算方剂）
        claimed_level = confidence_mod.parse_level(claimed)
        check_levels = [lvl for lvl in (claimed_level, expected) if lvl is not None]
        if any(not confidence_mod.allows_formula(lvl) for lvl in check_levels):
            if has_formula_content(rec.get_formula()):
                entry["safety_violation"] = "LOW 置信度下不应输出方剂"
                shown = claimed if claimed is not None else f"推断 {expected.value}"
                print(
                    f"🚨 安全边界违反: {rec.date} confidence={shown} 不应给方剂",
                    file=sys.stderr,
                )
        checks.append(entry)
    return checks


def main():
    """
    主入口：解析命令行参数，执行周报生成流程。
    """
    # 解析命令行参数
    target_date = None
    if len(sys.argv) > 1:
        try:
            target_date = datetime.strptime(sys.argv[1], "%Y-%m-%d")
        except ValueError:
            print(f"❌ 日期格式错误: {sys.argv[1]}，请使用 YYYY-MM-DD 格式")
            sys.exit(1)
    else:
        target_date = datetime.now()

    # 目录创建集中在运行入口（import 时零副作用）
    ensure_data_dirs()

    print(f"📅 周报目标日期: {target_date.strftime('%Y-%m-%d')}")
    print(f"📂 记录目录: {RECORDS_DIR}")
    print(f"📊 图表输出目录: {CHARTS_DIR}")
    print()

    # Step 1: 加载本周记录
    records = load_week_records(target_date)
    print(f"📋 已加载 {len(records)} 条日记录")

    if not records:
        print("⚠️ 本周无任何日分析记录，无法生成图表。")
        print("提示: 请至少拍摄 1 天照片并完成分析后再生成周报。")
        return

    # 打印加载的日期列表
    loaded_dates = [r.get("date", "?") for r in records]
    print(f"📆 覆盖日期: {', '.join(loaded_dates)}")

    # Step 2: 提取舌象指标并生成雷达图
    print("\n--- 生成舌象雷达图 ---")
    metrics_list = []
    dates_labels = []
    for record in records:
        m = extract_tongue_metrics(record)
        metrics_list.append(m)
        dates_labels.append(record.get("date", "?"))

    radar_path = generate_radar_chart(metrics_list, dates_labels)
    if radar_path:
        print(f"   雷达图: {radar_path}")

    # Step 3: 生成多维度趋势图
    print("\n--- 生成多维度趋势图 ---")
    trend_path = generate_trend_chart(records)
    if trend_path:
        print(f"   趋势图: {trend_path}")

    # Step 4: 生成周报摘要
    print("\n--- 周报摘要 ---")
    weekly_report_data = generate_weekly_report_data(records)
    for k, v in weekly_report_data.items():
        if k == "trend_analysis":
            print(f"   {k}:")
            for tk, tv in v.items():
                print(f"      {tk}: {tv}")
        elif isinstance(v, (dict, list)):
            # dict/list 字段用 JSON 美化打印，避免 raw repr
            print(f"   {k}:")
            print(json.dumps(v, ensure_ascii=False, indent=2))
        else:
            print(f"   {k}: {v}")

    # Step 5: 保存周报 JSON（可选）
    week_id = weekly_report_data.get("week_id", "YYYY-W00")
    report_path = os.path.join(WEEKLY_DIR, f"{week_id}_report.json")

    # 构建完整周报数据结构
    chart_info = []
    if radar_path:
        chart_info.append({
            "path": radar_path,
            "type": "radar",
            "title": "舌象指标雷达图"
        })
    if trend_path:
        chart_info.append({
            "path": trend_path,
            "type": "trend_line",
            "title": "多维度望诊趋势线"
        })

    report_data = {
        **weekly_report_data,
        "charts": chart_info,
    }

    try:
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report_data, f, ensure_ascii=False, indent=2)
        print(f"\n✅ 周报 JSON 已保存: {report_path}")
    except Exception as e:
        print(f"⚠️ 保存周报 JSON 时出错: {e}", file=sys.stderr)

    print("\n🎉 周报生成完毕！")


if __name__ == "__main__":
    main()
