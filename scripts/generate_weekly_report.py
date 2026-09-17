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
import re
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
        # Linux：Noto CJK 的 .ttc 集合常只注册 "JP" 名（"SC" 名在
        # font_manager 里不可见，实测本机只有 "Noto Sans CJK JP"），
        # 故 JP 必须列入；"Droid Sans Fallback" 名字含 Fallback 但实测
        # 其部分版本缺 ASCII/数字字形（l/p/2/(/— 渲染成方块），排到后面。
        "Noto Sans CJK SC", "Noto Sans CJK JP", "Source Han Sans SC",
        "WenQuanYi Micro Hei", "WenQuanYi Zen Hei",
        "Droid Sans Fallback",                                       # 末位兜底
        "Microsoft YaHei", "SimHei",                                 # 其他
    ]
    from matplotlib import font_manager
    installed = {f.name for f in font_manager.fontManager.ttflist}
    for name in candidates:
        if name in installed:
            # 回退链：DejaVu Sans 兜底 ASCII/数字/标点。matplotlib ≥3.6
            # 会逐字体补缺字形，避免 CJK 字体缺 ASCII 时渲染成方块。
            matplotlib.rcParams["font.sans-serif"] = [name, "DejaVu Sans"]
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


# 雷达图轴的展示标签（口径提示）；轴集合以 TONGUE_RADAR_METRIC_KEYS 为准，
# 新轴未在此配置时退回轴名本身（见 generate_radar_chart）
_RADAR_AXIS_LABELS = {
    "舌质颜色": "舌质颜色\n(偏离)",
    "舌苔厚度": "舌苔厚度\n(厚腻)",
    "舌苔润燥": "舌苔润燥\n(燥/滑)",
    "齿痕": "齿痕",
    "瘀斑": "瘀斑",
    "舌下络脉": "舌下络脉\n(迂曲)",
    "裂纹": "裂纹",
    "舌体胖瘦": "舌体胖瘦\n(偏离)",
    "舌苔剥落": "舌苔剥落\n(剥落/地图)",
}

# 同日期档案竞争排除模式：备份/副本/临时/旧格式快照不参与档案选择——
# 它们是历史快照，选上会读到旧口径数据（实测：08-28 的 .bak 曾让周报
# 偏离度静默变 0.0）
_SUSPECT_ARCHIVE_RE = re.compile(r"\.bak|copy|tmp|_旧格式", re.IGNORECASE)


def _select_daily_file(date_str: str) -> Optional[str]:
    """为某一天选出唯一的 analysis JSON 档案（三级规则）。

    ① 规范名 {date}_analysis.json 精确存在即选用——系统唯一认可的命名，
       存在即无歧义，同日副本再多也不参与竞争；
    ② 无规范名时，排除文件名含 .bak/copy/tmp/_旧格式 的备份/临时快照后，
       取剩余候选中 mtime 最新者（"字典序最新"启发式不可靠：07-15 曾
       静默选中 _b 副本而丢弃正档）；
    ③ 排除后仍有多份候选时向 stderr 打印 warning（列出全部候选与实际
       选用者），再取 mtime 最新——多份候选必须可见，不得静默选一。
    无候选（或排除后为空）时返回 None，该日静默跳过。
    """
    exact = os.path.join(RECORDS_DIR, f"{date_str}_analysis.json")
    if os.path.exists(exact):
        return exact
    pattern = os.path.join(RECORDS_DIR, f"{date_str}*analysis*.json")
    matches = [m for m in glob.glob(pattern)
               if not _SUSPECT_ARCHIVE_RE.search(os.path.basename(m))]
    if not matches:
        return None
    filepath = max(matches, key=os.path.getmtime)
    if len(matches) > 1:
        print(
            f"⚠️ 警告: {date_str} 有多份非规范命名的 analysis 候选: "
            f"{sorted(os.path.basename(m) for m in matches)}；"
            f"选用 mtime 最新者 {os.path.basename(filepath)}",
            file=sys.stderr,
        )
    return filepath


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

        # 三级规则选出该日唯一档案（见 _select_daily_file）
        filepath = _select_daily_file(date_str)

        if filepath is None:
            # 该日无记录，静默跳过
            continue

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

    # 雷达图指标名 → Scoring 规范指标 key（轴集合由 TONGUE_RADAR_METRIC_KEYS
    # 单一来源决定；轮次 3 起为 9 轴，含「舌苔剥落」）
    return {
        metric_name: float(indicators.get(ind_key, 0))
        for metric_name, ind_key in TONGUE_RADAR_METRIC_KEYS.items()
    }


def extract_tongue_observation_flags(record: Dict[str, Any]) -> Dict[str, bool]:
    """雷达轴名 → 该轴规范指标是否有观测文本。

    score_indicators 对"无观测"与"正常 0"返回相同分值，无法靠分值区分；
    get_observation 对缺失指标以空串占位（键数恒定），故判据为观测文本
    非空。供逐指标趋势与雷达图区分"正常 0 分"与"无数据"。

    参数:
        record: 单日诊断 JSON 记录（dict 或 DailyRecord）

    返回:
        dict: 雷达轴名 → 是否有观测（True=有观测文本）
    """
    rec = record if isinstance(record, DailyRecord) else DailyRecord(record)
    obs = rec.get_observation(VisionDimension.TONGUE)
    return {
        metric_name: bool(obs.get(ind_key, "").strip())
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


def compute_dimension_deviation_detail(record: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """
    计算单条记录各望诊维度的偏离度多维信息：mean / max / n。

    - mean：与 compute_dimension_deviation 完全同口径（score() 公开语义不变：
      舌诊为有分指标 sparse 均值，其余维度为累加封顶 10）；
    - max：该维度内最高单项分（无异常指标时为 0.0）——均值会被新增轻度异常
      稀释，max 不会，趋势判定需要它做第二道门槛；
    - n：有分（>0）指标数，即异常负荷；n=0 表示"无有效观测"
      （没拍到/解析不到与真正常在旧口径下同写 0.0，靠 n 区分）。

    参数:
        record: 单日诊断 JSON 记录（dict 或 DailyRecord）

    返回:
        dict: 维度中文名 → {"mean": float, "max": float, "n": int}
    """
    rec = record if isinstance(record, DailyRecord) else DailyRecord(record)
    detail: Dict[str, Dict[str, Any]] = {}
    for dim in DIMENSIONS:
        obs = rec.get_observation(dim)
        indicators = score_indicators(dim, obs)
        positives = [float(v) for v in indicators.values() if v > 0]
        detail[dim.chinese_name] = {
            "mean": score_dimension(dim, obs),
            "max": max(positives) if positives else 0.0,
            "n": len(positives),
        }
    return detail


def describe_trend(name: str, first_val: float, last_val: float,
                   higher_is_worse: bool = True,
                   first_max: Optional[float] = None,
                   last_max: Optional[float] = None,
                   first_n: Optional[int] = None,
                   last_n: Optional[int] = None) -> str:
    """
    根据首末两次数值生成中文趋势描述。

    口径说明：只比较周初与周末两天，不反映周中波动。

    双门槛（仅在调用方提供 first/last 的 max 与 n 时启用）：
    均值的分母是有分指标数 n，新增轻度异常会稀释均值造成"假好转"
    （实测 08-28：新增 3 项异常，均值反而 6.0 → 5.3）。因此仅当
    最重单项 max 同步下降 ≥0.5 且异常项数 n 不增（last_n <= first_n）
    时才允许输出"异常程度减轻"；max 降但 n 增、或 max 未同步下降时，
    输出中性描述，不得把分母变化叙述为改善。
    加重方向不设门槛：均值升高本身就是异常信号，从严叙述。
    """
    has_detail = (first_max is not None and last_max is not None
                  and first_n is not None and last_n is not None)

    # n=0 = 无有效观测（没拍到/解析不到），与"正常 0 分"必须区分开
    if has_detail and (first_n == 0 or last_n == 0):
        if first_n == 0 and last_n == 0:
            return f"{name}本周无有效观测（未拍到或未解析到有分指标），不作趋势判定"
        return (f"{name}仅一端有有效观测（周初 {first_n} 项 / 周末 {last_n} 项"
                f"有分指标），不作趋势判定")

    delta = round(last_val - first_val, 1)
    if abs(delta) < 0.5:
        return f"{name}整体稳定（{first_val:.1f} → {last_val:.1f}）"

    direction = "升高" if delta > 0 else "降低"
    worsening = (delta > 0 and higher_is_worse) or (delta < 0 and not higher_is_worse)
    if worsening:
        return (f"{name}较周初{direction}{abs(delta):.1f}分，异常程度加重，"
                f"需持续关注（{first_val:.1f} → {last_val:.1f}）")

    # 改善方向：启用双门槛（理由见 docstring）
    if has_detail:
        max_drop = round(first_max - last_max, 1)
        if max_drop >= 0.5 and last_n <= first_n:
            return (f"{name}较周初{direction}{abs(delta):.1f}分，异常程度减轻"
                    f"（{first_val:.1f} → {last_val:.1f}）")
        if max_drop >= 0.5:
            return (f"{name}均值较周初降低{abs(delta):.1f}分，最重单项减轻但"
                    f"异常项增多（{first_n}→{last_n} 项），暂不判为好转"
                    f"（{first_val:.1f} → {last_val:.1f}）")
        return (f"{name}均值较周初降低{abs(delta):.1f}分，但最重单项未同步减轻"
                f"（{first_max:g} → {last_max:g} 分），暂不判为好转"
                f"（{first_val:.1f} → {last_val:.1f}）")

    # 未提供 max/n 的旧调用方式（逐指标标量）：分母恒为 1，无稀释问题，保持原口径
    return (f"{name}较周初{direction}{abs(delta):.1f}分，异常程度减轻"
            f"（{first_val:.1f} → {last_val:.1f}）")


def generate_radar_chart(metrics_list: List[Dict[str, float]],
                         dates: List[str],
                         obs_flags_list: Optional[List[Dict[str, bool]]] = None
                         ) -> Optional[str]:
    """
    生成舌象指标雷达图。

    参数:
        metrics_list: 多日的舌象指标列表
        dates: 对应的日期标签
        obs_flags_list: 可选，逐日各雷达轴"是否有观测"（见
            extract_tongue_observation_flags）。某日全部轴无观测时不绘制
            该日多边形（全零多边形视觉上等同"一切正常"，是最强误导），
            并在图下加注。不传则保持旧行为（全部绘制）。

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

    # 雷达图轴集合直接取自 TONGUE_RADAR_METRIC_KEYS（单一来源，避免
    # 硬编码轴数假设——轮次 3 新增「舌苔剥落」后为 9 轴）；
    # category_labels 为带口径提示的展示名，未配置时退回轴名本身
    categories = list(TONGUE_RADAR_METRIC_KEYS.keys())
    category_labels = [_RADAR_AXIS_LABELS.get(c, c) for c in categories]

    N = len(categories)
    angles = np.linspace(0, 2 * np.pi, N, endpoint=False).tolist()
    angles += angles[:1]  # 闭合多边形

    fig, ax = plt.subplots(figsize=(9, 9), subplot_kw=dict(polar=True))
    ax.set_title("舌象指标雷达图 — 周趋势对比", pad=25, fontsize=16,
                 fontweight="bold", color="#2C1810")

    # 配色方案（最多 7 天）
    colors = ["#C41E3A", "#D4770A", "#2D5016", "#1A6B8A",
              "#6B2D8A", "#8B1A1A", "#B8860B"]

    skipped_dates: List[str] = []
    for idx, metrics in enumerate(metrics_list):
        label = dates[idx] if idx < len(dates) else f"Day {idx + 1}"

        # 全部轴无观测的日期不绘制多边形（全零多边形 = 圆心一点，
        # 视觉上会被误读为"一切正常"）
        if (obs_flags_list is not None and idx < len(obs_flags_list)
                and not any(obs_flags_list[idx].values())):
            skipped_dates.append(label)
            print(f"ℹ️ 雷达图: {label} 全部轴无有效观测，未绘制该日多边形",
                  file=sys.stderr)
            continue

        values = [metrics.get(cat, 0) for cat in categories]
        values += values[:1]  # 闭合

        color = colors[idx % len(colors)]

        ax.fill(angles, values, alpha=0.08, color=color)
        ax.plot(angles, values, "o-", linewidth=2, color=color,
                label=label, markersize=5)

    if skipped_dates:
        fig.text(0.5, 0.02,
                 f"注：以下日期无有效观测，未绘制多边形：{'、'.join(skipped_dates)}",
                 ha="center", fontsize=10, color="#8B1A1A")

    ax.set_xticks(angles[:-1])
    ax.set_xticklabels(category_labels, fontsize=10, color="#2C1810")
    ax.set_ylim(0, 10)
    ax.set_yticks([2, 4, 6, 8, 10])
    ax.set_yticklabels(["2", "4", "6", "8", "10"], fontsize=8, color="#666666")
    # 全部日期均无观测时没有可图例化的多边形，空图例只剩一个空框
    if len(skipped_dates) < len(metrics_list):
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

    # 计算各维度偏离度（按 Dimension 规范六维遍历，不再硬编码中文名）；
    # 多维信息（mean/max/n）用于区分"正常 0 分"与"无有效观测"（n=0）
    details = [compute_dimension_deviation_detail(r) for r in records]

    # ---- 绘制多维度趋势线 ----
    fig, ax = plt.subplots(figsize=(12, 6))
    fig.patch.set_facecolor("#FFFDF7")
    ax.set_facecolor("#FFFDF7")

    for dim in DIMENSIONS:
        # n=0（无有效观测）的点置 NaN 断线，不再画成 0.0 假"正常"
        series = [
            d[dim.chinese_name]["mean"] if d[dim.chinese_name]["n"] > 0 else float("nan")
            for d in details
        ]
        marker, color, label = _DIMENSION_STYLE[dim]
        ax.plot(x, series, marker, linewidth=2, markersize=7,
                color=color, label=label)

    # 任一维度 n=0 的日期在图底显式标注"无有效观测"（同一日期只标一次）
    for i, d in enumerate(details):
        if any(d[dim.chinese_name]["n"] == 0 for dim in DIMENSIONS):
            ax.text(i, 0.15, "无有效观测", fontsize=7, color="#999999",
                    ha="center", va="bottom", rotation=90)

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
            "dimension_deviation_detail": {},
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

    # 提取舌象与维度偏离度序列（deviations 保留旧结构供 max_dim 分支等使用；
    # details 为多维输出 mean/max/n，供趋势双门槛与"无有效观测"判定）
    tongue_metrics = [extract_tongue_metrics(r) for r in recs]
    deviations = [compute_dimension_deviation(r) for r in recs]
    details = [compute_dimension_deviation_detail(r) for r in recs]

    first_tm = tongue_metrics[0]
    last_tm = tongue_metrics[-1]
    first_dev = deviations[0]
    last_dev = deviations[-1]
    first_detail = details[0]
    last_detail = details[-1]

    # 逐指标"有无观测"判据：观测文本非空（score 无法区分"正常 0"与"无数据"）
    first_flags = extract_tongue_observation_flags(recs[0])
    last_flags = extract_tongue_observation_flags(recs[-1])

    def _dim_trend(name: str, dim_cn: str) -> str:
        """维度级趋势描述：携带 max/n 启用双门槛与无有效观测判定。"""
        return describe_trend(
            name, first_dev[dim_cn], last_dev[dim_cn],
            first_max=first_detail[dim_cn]["max"],
            last_max=last_detail[dim_cn]["max"],
            first_n=first_detail[dim_cn]["n"],
            last_n=last_detail[dim_cn]["n"],
        )

    def _metric_trend(name: str, axis: str) -> str:
        """逐指标趋势：观测 flag 作为 n（0/1）传入 describe_trend，
        无观测走其既有 n=0 分支，不再把"未解析到"写成"整体稳定（0.0 → 0.0）"；
        两端都有观测时退化为与旧标量调用逐字一致的输出。"""
        return describe_trend(
            name, first_tm[axis], last_tm[axis],
            first_max=first_tm[axis], last_max=last_tm[axis],
            first_n=int(first_flags[axis]), last_n=int(last_flags[axis]),
        )

    def _metric_group_trend(axes: List[Any]) -> str:
        """分组短路：组内全部轴两端均无观测时只输出一句，避免整组刷长文案。"""
        if all(not first_flags[axis] and not last_flags[axis]
               for _, axis in axes):
            names = "/".join(axis for _, axis in axes)
            suffix = "均未解析到" if len(axes) > 1 else "未解析到"
            return f"本周无有效观测（{names}{suffix}）"
        return "；".join(_metric_trend(name, axis) for name, axis in axes)

    trend_analysis = {
        "舌质变化": _metric_group_trend([("舌质颜色偏离度", "舌质颜色")]),
        # 轮次 3 起剥落进入雷达图与评分；文字趋势同步纳入，
        # 否则核心观察点（花剥苔/地图舌）在摘要里看不到
        "舌苔变化": _metric_group_trend([
            ("舌苔厚度", "舌苔厚度"),
            ("舌苔润燥", "舌苔润燥"),
            ("舌苔剥落", "舌苔剥落"),
        ]),
        "舌形变化": _metric_group_trend([
            ("齿痕程度", "齿痕"),
            ("舌体胖瘦偏离度", "舌体胖瘦"),
            ("裂纹程度", "裂纹"),
        ]),
        "舌下络脉变化": _metric_group_trend([("舌下络脉迂曲度", "舌下络脉")]),
        "head_face_trend": _dim_trend("头面诊偏离度", "头面诊"),
        "eye_trend": _dim_trend("目诊偏离度", "目诊"),
        "ear_trend": _dim_trend("耳诊偏离度", "耳诊"),
        "hand_trend": _dim_trend("手诊偏离度", "手诊"),
        "skin_trend": _dim_trend("皮肤诊偏离度", "皮肤诊"),
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

    # 全维度周末 n=0 = 本周未解析到任何有效观测：不作偏离度排名，
    # 也不得落入"偏离度总体较低"建议分支（会把"无数据"误述为"状况良好"）
    all_dims_unobserved = all(d["n"] == 0 for d in last_detail.values())

    # 舌诊偏离度多维呈现：均值 + 最重单项 + 异常项数；n=0 时显式标注
    # "无有效观测"，不再把"没拍到/解析不到"写成 0.0 假"正常"
    first_td = first_detail["舌诊"]
    last_td = last_detail["舌诊"]
    if first_td["n"] == 0 and last_td["n"] == 0:
        tongue_phrase = "舌诊本周无有效观测（未拍到或未解析到有分指标），偏离度不予计值"
    elif last_td["n"] == 0:
        tongue_phrase = (
            f"舌诊综合偏离度均值周初为 {first_td['mean']:.1f}"
            f"（共 {first_td['n']} 项异常），周末无有效观测"
        )
    elif first_td["n"] == 0:
        tongue_phrase = (
            f"舌诊综合偏离度均值周初无有效观测，周末为 {last_td['mean']:.1f}"
            f"（最重单项 {last_td['max']:g} 分，共 {last_td['n']} 项异常）"
        )
    else:
        tongue_phrase = (
            f"舌诊综合偏离度均值由 {first_td['mean']:.1f} 变化至 {last_td['mean']:.1f}"
            f"（最重单项 {last_td['max']:g} 分，共 {last_td['n']} 项异常）"
        )

    if all_dims_unobserved:
        ranking_phrase = "本周各维度均无有效观测，不作偏离度排名。"
    else:
        ranking_phrase = f"当前偏离度最高的维度为「{max_dim}」（{max_score:.1f} 分）。"
    summary = (
        f"本周（{first_date} 至 {last_date}）共 {len(records)} 条日分析记录。"
        f"{tongue_phrase}；"
        f"{ranking_phrase}"
        f"{trend_analysis['舌质变化']} "
        f"{trend_analysis['head_face_trend']}。"
    )

    if all_dims_unobserved:
        next_week_suggestion = (
            "本周未解析到有效观测，请按规范形状（形状 C）核对档案或重传照片。"
        )
    elif max_score < 3.0:
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
        # 纯增量键（向后兼容）：各维度周初/周末的 mean/max/n 多维信息，
        # 供趋势双门槛复核与"无有效观测"（n=0）识别；旧键一律不动
        "dimension_deviation_detail": {
            dim_cn: {"first": first_detail[dim_cn], "last": last_detail[dim_cn]}
            for dim_cn in first_detail
        },
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
    obs_flags_list = []
    for record in records:
        m = extract_tongue_metrics(record)
        metrics_list.append(m)
        dates_labels.append(record.get("date", "?"))
        obs_flags_list.append(extract_tongue_observation_flags(record))

    radar_path = generate_radar_chart(metrics_list, dates_labels,
                                      obs_flags_list=obs_flags_list)
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
