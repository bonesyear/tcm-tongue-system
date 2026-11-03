"""记录存取层：records/daily 的扫描、选档与页面视图模型。

把「文件 → DailyRecord → 页面所需 dict」的复杂度收敛在这里，
app.py 只负责路由。选档规则与 scripts/generate_weekly_report.py 的
_select_daily_file 同口径（规范名优先；否则排除备份/临时后取 mtime 最新，
多份候选打 stderr 警告）。
"""
from __future__ import annotations

import datetime
import json
import os
import sys
import threading

import time_utils
from src import paths
from src.daily_files import SUSPECT_ARCHIVE_RE as _SUSPECT_ARCHIVE_RE
from src.daily_files import daily_files, select_daily_file as _select_daily_file
from src.dimensions import DIMENSIONS
from src.indicators import (
    FIELD_OPTIONS, INDICATOR_LABELS, INDICATOR_REGISTRY,
    REFERENCE_FIELDS, REVIEW_FIELDS,
)
from src.record import DailyRecord
from src.observations import (
    UNKNOWN_OBSERVATION_MARK, SCHEMA_VERSION, capture_observation,
)
from src.scoring import DIMENSION_RULES, score, score_indicators

REF_FIELDS = REFERENCE_FIELDS

# 词表无 0 分基线词时给修正 UI 补的「正常」选项：措辞落在 validator 的
# 正常/否定语义豁免区（input_validator 对「未见」类描述不做词表覆盖告警），
# 且不命中任何评分关键词 → 0 分 = 正常，方向正确。
NORMAL_OPTION = "未见异常"

# 术语白话注解（修正选项悬浮提示用）：专业词汇对非专业用户是墙，
# 注解口径与《中医诊断学》定义句一致，只解释词义不做诊断结论。
GLOSSARY = {
    "㿠白": "面色虚浮发白，多属阳虚",
    "黧黑": "黑而晦暗，多属肾虚",
    "萎黄": "黄而枯槁无光，多属气血不足",
    "晦暗": "面色发暗无光泽",
    "红如妆": "颧部浮红像化了妆、游移不定——戴阳证，危重信号",
    "红绛": "比红舌更深的暗红色，主热甚",
    "紫暗": "紫而发暗，多主瘀血",
    "青紫": "青紫色，多主寒凝瘀血",
    "芒刺": "舌面红色刺状突起，如草莓，主热毒炽盛",
    "点刺": "舌面蕈状乳头红肿突起",
    "痿软": "舌软弱无力、伸缩困难",
    "强硬": "舌体僵硬不灵活——中风预警体征之一",
    "短缩": "舌体卷短紧缩、不能伸长——病情危重的表现",
    "吐弄": "舌伸出口外不回缩（吐）或微露即收（弄），主心脾积热/动风",
    "颤动": "舌体不自主抖动",
    "歪斜": "伸舌时偏向一侧——中风预警体征之一",
    "滑": "苔面水分多、摸之湿滑，主水饮痰湿",
    "燥": "苔干燥缺水，主津液亏虚",
    "干裂": "苔干到开裂，津亏较重",
    "厚腻": "苔厚且细腻致密如涂油，主湿浊痰食",
    "焦黑": "苔色发黑干枯，主热极",
    "无苔": "苔脱落露出舌面，主阴虚或胃气伤",
    "剥落": "舌苔部分脱落",
    "满布": "舌苔铺满整个舌面",
    "偏布一侧": "舌苔只分布在一侧",
    "甲错": "皮肤干枯粗糙、状如鱼鳞，主瘀血或津亏",
    "黄汗": "汗液发黄、可染黄衣色",
    "龟裂": "皮肤干裂如龟甲纹路",
    "厥冷": "手脚冰凉、冷过肘膝，主阳气衰",
    "不温": "手脚偏凉、不够暖和",
    "散在": "零星分布",
    "密集": "成片密集出现",
    "黄染": "眼白/皮肤发黄，黄疸信号",
    "无黄染": "没有发现眼白黄染",
    "赤丝": "眼白出现明显红丝（3 分，与「红血丝」同档；赤丝为古医书用语）",
    "卧蚕": "下眼睑微肿如蚕卧状",
    "少华": "光泽欠佳",
    "荣润": "润泽有光彩，正常表现",
    "枯槁": "干枯无光泽",
    "枯": "干枯无光泽",
    "鼻衄": "鼻出血",
    "煽动": "鼻翼煽动——呼吸时鼻翼一张一缩，多提示呼吸急促费力（肺热/哮喘/高热）；需动态观察",
    "怒张": "络脉粗胀凸起",
}

# 第二批：统一覆盖——所有选项词都有注解（2026-10-16 主人要求：
# 不让用户猜词义；程度词给功能性说明，自明词一句话带过）。
GLOSSARY.update({
    # 问诊选项词条（2026-10-20 INQUIRY_UX 任务①，措辞对齐原著/教材语义）
    "偏凉": "温度介于温与凉之间",
    "恶热": "怕热、喜凉，多主热证",
    "都不明显": "怕冷怕热都不突出",
    "有汗": "生病期间身上有汗",
    "没有外感不适": "没有感冒/外感的不适表现",
    "无汗": "生病期间无汗，恶寒发热时也不出汗",
    "头痛": "头部疼痛",
    "身痛": "肢体酸痛",
    "晨起口苦": "早晨醒来口苦，白天不明显",
    "全天口苦": "全天持续口苦",
    "咽干欲饮": "咽干且想喝水",
    "头晕": "头昏沉，视物不旋转",
    "目眩(天旋地转)": "天旋地转、站不稳的晕（比「头晕」更重一层）",
    "口不渴": "不口渴，不想喝水",
    "口渴欲饮": "口渴想喝水，且能喝下",
    "无不适": "该部位没有不舒服",
    "腹痛": "腹部疼痛",
    "听力下降": "听声音变模糊、不如以前",
    "鼻塞": "鼻子不通气",
    "无异常": "没有异常表现",
    "轻微": "程度轻微",
})

GLOSSARY.update({
    # 程度/频次词（跨字段通用）
    "无": "没有该项表现",
    "正常": "没有异常表现",
    "未见异常": "没有发现异常表现",
    "轻度": "程度较轻",
    "中度": "程度中等",
    "重度": "程度严重",
    "略厚": "比正常稍厚一点",
    "稍厚": "比正常稍厚一点",
    "偏厚": "明显偏厚但未达最重",
    "稍干": "稍微有点干",
    "偏干": "明显偏干",
    "偏胖": "比正常偏大",
    "偏瘦": "比正常偏小",
    "偏腻": "有些黏腻",
    "稍胖": "比正常稍大",
    "稍腻": "稍有黏腻",
    "略瘦": "比正常略瘦小",
    "略枯": "略有干枯、不够润泽",
    "微肿": "轻微肿胀",
    "微腻": "轻微黏腻",
    "少量": "数量较少",
    "较多": "数量较多",
    "明显": "汗色发黄明显易见（程度词，与「色正黄」同分但非经典句式）",
    "局部": "只出现在局部区域",
    "广泛": "分布范围广",
    "浅裂": "裂纹较浅",
    "深裂": "裂纹较深",
    "剥脱": "舌苔部分脱落",
    "苔少": "舌苔量偏少",
    "苔多": "舌苔量偏多",
    # 颜色词
    "淡红": "淡红色（多为正常基色）",
    "淡粉红": "淡淡的粉红色（正常唇色）",
    "红润": "红而润泽（正常表现）",
    "红": "偏红，多主热",
    "红赤": "眼白整体明显发红（4 分，比血丝/赤丝更重，为弥漫性发红）",
    "暗红": "红而发暗，多主瘀热",
    "淡白": "颜色浅淡少血色，多主血虚/阳虚",
    "苍白": "白而无血色，多主脱血/阳虚重证",
    "淡黄": "淡淡的黄色，多主血少",
    "暗黄": "黄而发暗，多主血少或湿",
    "淡紫": "色淡泛紫（舌下络脉淡紫属正常；舌质用此词已并入「紫暗」）",
    "暗紫": "紫而发暗，多主瘀血",
    "青灰": "青灰色，多为寒痛或惊风",
    "青黑": "青黑色，多主寒盛/剧痛",
    "白": "白色（苔色白多主表寒）",
    "黄": "黄色（苔色黄多主热）",
    "灰": "苔色浅黑",
    "灰黑": "苔色灰黑，寒热均属重证",
    "黑": "颜色发黑",
    "黯黑": "黑而晦暗",
    "蓝巩膜": "眼白发蓝，多见于先天性巩膜变薄",
    # 头面/目/耳/鼻/唇
    "充血": "眼白弥漫性明显充血、大片鲜红（最重档，6 分）",
    "血丝": "眼白有少量细微血丝（最轻档，2 分）",
    "红血丝": "较明显、成片的红色血丝（3 分，重于「血丝」，轻于「红赤」）",
    "明显浮肿": "肿胀明显可见",
    "轻度浮肿": "轻微肿胀",
    "浮肿": "肿起、按之可凹陷",
    "浮肿明显": "肿胀明显",
    "面目鲜泽": "面部浮肿且光亮，多为风水",
    "黑眼圈": "眼眶下发黑，多见于睡眠不足或肾虚",
    "黄染轻度": "轻度发黄",
    "黄染明显": "明显发黄",
    "黄如橘皮": "黄而鲜明像橘子皮——阳黄，急性黄疸信号",
    "橘皮": "黄而鲜明像橘子皮——阳黄，急性黄疸信号",
    "烟熏": "黄而晦暗像被烟熏过——阴黄",
    "干燥": "缺少水分、发干",
    "燥裂": "干燥到开裂",
    "干枯": "又干又枯、完全失去润泽",
    "润": "润泽有水分（正常表现）",
    "润泽": "滋润有光泽（正常表现）",
    # 舌象
    "薄": "透过舌苔能看到舌体（见底，正常）",
    "薄白": "薄而白的苔（正常舌苔）",
    "薄黄": "薄而淡黄的苔，热势轻浅",
    "白厚": "苔白且厚，遮到看不见舌体",
    "黄厚": "苔黄且厚，热邪入里",
    "腐苔": "苔粗松如豆腐渣、一刮就掉，主食积痰浊",
    "腻": "苔细腻致密如涂油、刮不下来，主湿浊痰食",
    "地图舌": "舌苔不规则剥落、边缘凸起像地图，会换位置",
    "花剥": "舌苔多处剥落、斑驳残存",
    "镜面": "舌苔全脱、舌面光亮如镜——胃气阴枯涸，重证",
    "肿胀": "舌体肿大满口，主湿热/热毒",
    "胖大": "舌体比正常大而厚，主水湿痰饮",
    "瘦小": "舌体比正常瘦小而薄，主气血两虚/阴虚火旺",
    "适中": "大小正常",
    "增粗": "络脉比正常粗",
    # 手/皮肤
    "全身浮肿": "全身上下都肿",
    "凹陷": "按压后皮肤凹陷、回弹慢，主水肿",
    "粗糙": "皮肤摸起来粗糙不滑",
    "色正黄": "汗液纯正鲜黄、可染衣——《金匮》黄汗病定名体征（「汗沾衣，色正黄如柏汁」）",
    "温": "手脚温度正常暖和",
    "凉": "手脚偏凉",
    # 问诊选项（向导步 chips 悬浮注解）
    "恶寒": "怕冷、添衣不减，多主表寒",
    "往来寒热": "忽冷忽热交替，少阳病特征",
    "头项强痛": "头痛连后颈僵硬，太阳表束",
    "目眩": "头晕眼花、天旋地转",
    "渴不欲饮": "口干但不想喝水",
    "口燥但欲漱水不欲咽": "口干想漱口却不想咽下——瘀血特征",
    "纳呆不食": "没胃口、不想吃饭",
    "饥不欲食": "肚子饿却吃不下，多主胃阴伤",
    "消谷善饥": "吃得多还老饿，多主胃热",
    "便溏": "大便稀软不成形，多主脾虚湿",
    "便硬": "大便干硬难下",
    "便燥": "大便干燥",
    "下利": "腹泻、大便稀水样",
    "小便清长": "小便量多色淡，多主寒",
    "小便黄赤": "小便黄少，多主热",
    "小便不利": "排尿不畅、尿量少",
    "小便白": "小便色白清稀，多主少阴虚寒",
    "失眠烦躁": "睡不着、心烦",
    "嗜睡多寐": "老想睡、精神萎靡",
    "胸胁苦满": "胸口和两胁胀满不舒，少阳柴胡证",
    "心下痞": "心窝部堵闷感",
    "腹满": "腹部胀满",
    "胸闷": "胸部憋闷",
    "耳鸣": "耳内鸣响",
    "耳无所闻": "听不到声音",
    "鼻鸣": "鼻塞呼吸有声",
    "自汗(白天易汗出)": "白天不动也出汗，多主阳虚/表虚",
    "盗汗(睡中汗出)": "睡着后出汗、醒则止，多主阴虚",
    "绝汗(大汗淋漓如油)": "大汗淋漓不止——脱阳前兆，危重",
    "厥冷（冰冷）": "手脚冰凉过肘膝——病在阴，警惕危重",
})


# 显示层去重（评分层双词兜底不动）：同义异形词只保留一个显示选项，
# 避免用户以为「剥落/剥脱」「紫暗/暗紫」是两种程度。
_DISPLAY_HIDE = {
    "coating_peeling": {"剥脱"},   # 剥落=剥脱（同分同义，保留「剥落」）
    "nail_color": {"暗紫"},        # 紫暗=暗紫（同分同义，保留「紫暗」）
    "color": {"橘皮"},             # 黄如橘皮=橘皮（同分同义，保留教材全句「黄如橘皮」）
}


def _field_options(dim, indicator: str):
    """修正 UI 的封闭选项；无词表且未人工指定时返回 None（回落自由文本）。"""
    spec = INDICATOR_REGISTRY.for_field(dim, indicator)
    if spec.options is None:
        return None
    opts = list(spec.options)
    rules = DIMENSION_RULES.get(dim, {}).get(indicator)
    if rules and not any(v == 0 for v in rules.values()):
        opts.insert(0, NORMAL_OPTION)
    hide = _DISPLAY_HIDE.get(indicator, set())
    return [o for o in opts if o not in hide]


def validate_field_value(dim, indicator, value, method="manual"):
    """所有观察写入共享的类型、长度、占位符与封闭选项校验。"""
    from src.observations import is_absolute_measurement
    from src.record import is_declared_normal_value
    from src.textnorm import canonical_option, has_line_breaks, normalize_text
    if not isinstance(value, str):
        raise ValueError("观察值必须为字符串")
    if not value.strip():
        raise ValueError("观察值不能为空；清空请使用显式清除动作")
    if len(value) > 64:
        raise ValueError("观察值不得超过 64 字")
    if has_line_breaks(value):
        raise ValueError("观察值不得包含换行")
    if is_declared_normal_value(value) or value == UNKNOWN_OBSERVATION_MARK:
        raise ValueError("声明或无法判读占位不能作为实测值写入")
    if indicator == "sublingual_thickness" and method in ("photo", "measurement") \
            and is_absolute_measurement(value):
        return normalize_text(value.strip())
    normalized = canonical_option(value)
    spec = INDICATOR_REGISTRY.for_field(dim, indicator)
    display_options = _field_options(dim, indicator)
    options = spec.prompt_options if spec.prompt_options is not None else display_options
    if options is not None:
        options = list(dict.fromkeys([*options, *(display_options or [])]))
    if options is not None:
        for option in options:
            if canonical_option(option) == normalized:
                return option
        raise ValueError(f"值不在封闭词表内: {value}")
    return normalize_text(value.strip())


# 形状 B 嵌套首段的展示前缀（修正/复核卡片分组用）
_B_GROUP_LABELS = {"body": "舌质", "coating": "舌苔", "sublingual": "舌下络脉",
                   "face": "面域", "lips": "唇域", "nose": "鼻域"}


def _glossary(dim, indicator: str, term: str):
    spec = INDICATOR_REGISTRY.for_field(dim, indicator)
    return INDICATOR_REGISTRY.glossary_for(spec.id, term, GLOSSARY.get(term))


def correction_meta() -> dict:
    """修正选项元数据（向导第 8 步复核卡片 + 详情页共用数据源）：
    {维度英文名: {点号 B 路径: {ind, label, opts, gloss}}}。
    label 同名指标（如舌诊三个「颜色」）带组前缀消歧。"""
    from src.record import _DIMENSION_INDICATORS
    meta = {}
    for dim in DIMENSIONS:
        fields = {}
        for ind, shapes in _DIMENSION_INDICATORS.get(dim, {}).items():
            spec = INDICATOR_REGISTRY.for_field(dim, ind)
            b_path = ".".join(shapes["B"])
            prefix = _B_GROUP_LABELS.get(shapes["B"][0], "") \
                if len(shapes["B"]) > 1 else ""
            label = (prefix + "·" if prefix else "") + spec.label
            opts = _field_options(dim, ind)
            fields[b_path] = {
                "ind": ind, "label": label, "opts": opts,
                "scored": spec.scoring,
                "gloss": {o: _glossary(dim, ind, o) for o in opts
                          if _glossary(dim, ind, o) is not None} if opts else None,
            }
        meta[dim.english_name] = fields
    return meta

# 「未拍摄（用户声明正常）」占位检测（单一事实来源在 src/record.py）
from src.record import DECLARED_NORMAL_MARK  # noqa: F401

# 维度 → 展示分组（舌诊按 舌质/舌苔/舌下络脉，头面按 面/唇/鼻，其余单组）
DIM_GROUPS = {
    "tongue": [
        ("舌质", ["body_color", "body_luster", "body_size", "petechiae",
                  "tooth_marks", "fissure", "prickles", "body_dynamics"]),
        ("舌苔", ["coating_color", "coating_thickness", "coating_moisture",
                  "coating_greasy", "coating_peeling", "coating_amount",
                  "coating_distribution"]),
        ("舌下络脉", ["sublingual_color", "sublingual_thickness",
                     "sublingual_varicosity", "sublingual_petechiae"]),
    ],
    "head_face": [
        ("面域", ["face_color", "face_edema", "face_luster"]),
        ("唇域", ["lip_color", "lip_moisture"]),
        ("鼻域", ["nose_color", "nose_flare", "nose_bleeding"]),
    ],
    "eye": [("目", ["redness", "jaundice", "edema", "dark_orbit", "sclera_color",
                    "lower_lid"])],
    "ear": [("耳", ["color", "helix"])],
    "hand": [("手", ["palm_color", "palm_temp", "nail_color", "nail_shape",
                     "ecchymosis"])],
    "skin": [("皮肤", ["color", "cuo", "yellow_sweat", "edema", "dryness"])],
}

# 危险信号字典已下沉至 src/danger.py（系统级单一事实来源，
# 2026-10-21 DANGER_FLAGS_FIX_PLAN B 批）；此处 re-export 保持既有引用兼容
from src.danger import DANGER_FLAGS, DANGER_PATTERNS, detect_danger  # noqa: F401

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
    from date_utils import parse_date
    parsed = parse_date(date_str)
    if parsed is None:
        print(f"⚠️ 警告: 非法记录日期 {date_str!r}，星期显示留空", file=sys.stderr)
        return ""
    return "周" + _WEEKDAYS[parsed.weekday()]


# 公开别名：跨模块调用不走私有名
select_daily_file = _select_daily_file


def validate_candidate(raw: dict, workdir: str, previous_raw: dict | None = None):
    """校验候选；原记录已有的错误转 warning，只返回本次新增 errors。"""
    from io_utils import write_temp_json
    from input_validator import validate_record
    os.makedirs(workdir, exist_ok=True)
    tmp = write_temp_json(os.path.join(workdir, ".validate-candidate.json"), raw)
    try:
        _, errors, warnings = validate_record(tmp)
        if previous_raw is not None:
            previous_tmp = write_temp_json(
                os.path.join(workdir, ".validate-previous.json"), previous_raw)
            try:
                _, previous_errors, _ = validate_record(previous_tmp)
            finally:
                if os.path.exists(previous_tmp):
                    os.unlink(previous_tmp)
            inherited = set(previous_errors)
            warnings.extend(f"⚠️ 存量校验问题（本次未新增）: {error}"
                            for error in errors if error in inherited)
            errors = [error for error in errors if error not in inherited]
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return errors, warnings


def backup_file(filepath: str, backup_dir: str, purpose="correction") -> str:
    from lifecycle_store import backup_file as backup
    return backup(filepath, backup_dir, purpose)


def create_pristine_snapshot(raw: dict, backup_dir: str) -> dict:
    from lifecycle_store import create_pristine_snapshot as create
    return create(raw, backup_dir)


def restore_original(daily_dir: str, backup_dir: str, date_str: str,
                     timezone_name=None) -> dict:
    from lifecycle_store import restore_original as restore
    return restore(daily_dir, backup_dir, date_str, timezone_name)


def list_dates(daily_dir: str):
    """与详情、周报共用扫描规则，返回有候选记录的日期（降序）。"""
    from date_utils import parse_date
    dates = set()
    for date_str, candidates in daily_files(daily_dir).items():
        if not candidates:
            continue
        if parse_date(date_str):
            dates.add(date_str)
        else:
            print(f"⚠️ 警告: 跳过非法日期文件 {candidates[0][0]}", file=sys.stderr)
    return sorted(dates, reverse=True)


def latest_record_date(daily_dir: str):
    """最新可解析记录的日期；坏 JSON 不作为趋势回跳目标。"""
    for date_str in list_dates(daily_dir):
        if load_record(daily_dir, date_str) is not None:
            return date_str
    return None


def load_record_with_version(daily_dir: str, date_str: str):
    """返回 (DailyRecord|None, 文件版本|None)，读取与哈希使用同一内容。"""
    from date_utils import parse_date
    if parse_date(date_str) is None:
        return None, None
    filepath = _select_daily_file(daily_dir, date_str)
    if not filepath:
        return None, None
    from io_utils import file_version, read_versioned_json
    try:
        raw, version = read_versioned_json(filepath)
        if not isinstance(raw, dict):
            raise TypeError(f"记录根节点不是对象（{type(raw).__name__}）")
        if raw.get("date") != date_str:
            print(f"⚠️ 警告: {filepath} 内部日期 {raw.get('date')!r} "
                  f"与文件名不一致，按文件名 {date_str} 读取", file=sys.stderr)
            raw = dict(raw, date=date_str)
        return DailyRecord(raw), version
    except (OSError, ValueError, TypeError) as e:
        print(f"⚠️ 警告: 记录 {filepath} 解析失败: {e}", file=sys.stderr)
        return None, file_version(filepath)


def load_record(daily_dir: str, date_str: str):
    """选档并解析为 DailyRecord；无记录或解析失败返回 None。"""
    return load_record_with_version(daily_dir, date_str)[0]


def _is_declared_normal(obs: dict) -> bool:
    """该维度是否只有声明占位；真实观察与占位并存时不算声明正常。"""
    values = [v for v in obs.values() if v]
    from src.record import is_declared_normal_value
    return bool(values) and all(is_declared_normal_value(v) for v in values)


def _scoring_observation(rec: DailyRecord, dim) -> dict:
    return rec.get_scoring_observation(dim)


def _dim_assessments(rec: DailyRecord):
    from src.scoring import assess
    return {dim: assess(dim, _scoring_observation(rec, dim)) for dim in DIMENSIONS}


def _dim_scores(rec: DailyRecord):
    assessments = _dim_assessments(rec)
    return {
        dim.chinese_name: (result.value
                           if result.state in ("normal", "abnormal") else None)
        for dim, result in assessments.items()
    }


def record_summary(rec: DailyRecord) -> dict:
    """列表/日历用的单日摘要；未知项不计入总分或正常分母。"""
    assessments = _dim_assessments(rec)
    dims = {dim.chinese_name: (result.value
                              if result.state in ("normal", "abnormal") else None)
            for dim, result in assessments.items()}
    known = [v for v in dims.values() if v is not None]
    total = round(sum(known), 1)
    return {
        "date": rec.date,
        "weekday": weekday_cn(rec.date) if rec.date else "",
        "coverage": rec.get_covered_dimension_count(),
        "coverage_total": len(DIMENSIONS),
        "dims": dims,
        "total": total,
        "total_sev": sev_class(total / len(DIMENSIONS) if known else None),
        "unknown_count": sum(r.unknown_count for r in assessments.values()),
        "missing_count": sum(len(r.missing_indicators) for r in assessments.values()),
    }


_NEGATIVE_INQUIRY_ANSWERS = {
    "无", "正常", "没有外感不适", "都不明显", "无不适", "无异常",
    "口不渴", "温", "未见异常", "未见", "阴性",
}


def has_positive_inquiry(rec: DailyRecord) -> bool:
    """任一已答问诊含非阴性答案即视为有阳性信息，未答不算阳性。"""
    for answer in rec.get_inquiry_answers().values():
        if answer and answer not in _NEGATIVE_INQUIRY_ANSWERS:
            return True
    return False


def allows_no_abnormal_exit(rec: DailyRecord) -> bool:
    """允许「本次已采集项未见异常」的必要条件，不是健康诊断。"""
    summary = record_summary(rec)
    known = [v for v in summary["dims"].values() if v is not None]
    return (summary["coverage"] > 0 and summary["unknown_count"] == 0
            and bool(known) and all(v == 0 for v in known)
            and not has_positive_inquiry(rec)
            and not rec.get_triggered_danger_flags())


_SUMMARY_CACHE: dict[str, tuple[tuple[int, int], dict]] = {}
_SUMMARY_CACHE_LOCK = threading.RLock()


def _summary_for_date(daily_dir: str, date_str: str):
    filepath = _select_daily_file(daily_dir, date_str)
    if not filepath:
        return None
    try:
        stat = os.stat(filepath)
        signature = stat.st_mtime_ns, stat.st_size
    except OSError:
        return None
    cached = _SUMMARY_CACHE.get(filepath)
    if cached and cached[0] == signature:
        return cached[1]
    with _SUMMARY_CACHE_LOCK:
        cached = _SUMMARY_CACHE.get(filepath)
        if cached and cached[0] == signature:
            return cached[1]
        rec = load_record(daily_dir, date_str)
        if rec is None or not rec.date:
            return None
        summary = record_summary(rec)
        _SUMMARY_CACHE[filepath] = (signature, summary)
        return summary


def list_summaries(daily_dir: str, limit=None):
    """摘要按日期降序；可选择只加载前 limit 条，坏记录跳过。"""
    if limit is not None and limit <= 0:
        return []
    out = []
    for date_str in list_dates(daily_dir):
        summary = _summary_for_date(daily_dir, date_str)
        if summary is not None:
            out.append(summary)
            if limit is not None and len(out) >= limit:
                break
    return out


def calendar_month(daily_dir: str, month: str, today: str):
    """一个月的历网格（周一开头），供模板直接渲染。

    返回 {"month": "2026-06", "label": "2026 年 6 月", "weeks": [[cell,...]]}，
    cell = {"day": int|None, "date", "has", "today", "dots": [sev...], "total", "sev"}。
    """
    import calendar as calendar_lib
    from date_utils import add_month, parse_month
    first = parse_month(month)
    if first is None:
        return {"month": month, "label": month, "weeks": [],
                "prev": None, "next": None}
    year, mon = first.year, first.month
    by_date = {}
    for date_str in list_dates(daily_dir):
        if date_str.startswith(month):
            summary = _summary_for_date(daily_dir, date_str)
            if summary is not None:
                by_date[date_str] = summary

    cells = []
    for week in calendar_lib.monthcalendar(year, mon):
        for day in week:
            if not day:
                cells.append({"day": None})
                continue
            date_str = f"{year:04d}-{mon:02d}-{day:02d}"
            s = by_date.get(date_str)
            cell = {"day": day, "date": date_str, "has": bool(s),
                    "today": date_str == today}
            if s:
                cell["dots"] = [sev_class(v) for v in s["dims"].values()]
                cell["total"] = f'{s["total"]:.1f}'
                cell["sev"] = s["total_sev"]
            cells.append(cell)
    weeks = [cells[i:i + 7] for i in range(0, len(cells), 7)]
    prev_m = add_month(first, -1)
    next_m = add_month(first, 1)
    return {"month": month, "label": f"{year} 年 {mon} 月", "weeks": weeks,
            "prev": prev_m.strftime("%Y-%m") if prev_m else None,
            "next": next_m.strftime("%Y-%m") if next_m else None}


def week_stats(summaries, today: str, all_dates=None):
    """本周截至今天的统计；连续天数从今天或昨天起算，忽略未来日期。"""
    import time_utils
    from date_utils import add_days, parse_date
    today_d = parse_date(today) or time_utils.today()
    week_start = add_days(today_d, -today_d.weekday())
    summaries_by_date = {s["date"]: s for s in summaries}
    dates = set(all_dates) if all_dates is not None else set(summaries_by_date)
    this_week = []
    for offset in range(7):
        day = add_days(week_start, offset)
        if day is not None and day <= today_d and day.isoformat() in summaries_by_date:
            this_week.append(summaries_by_date[day.isoformat()])
    today_str = today_d.isoformat()
    cur = today_d if today_str in dates else add_days(today_d, -1)
    streak = 0
    while cur and cur.isoformat() in dates:
        streak += 1
        cur = add_days(cur, -1)
    avg = round(sum(s["total"] for s in this_week) / len(this_week), 1) if this_week else None
    return {"week_days": len(this_week), "streak": streak, "week_avg": avg}


def load_demo(daily_dir: str) -> str:
    """仅向空库写入合成示例；已有记录或同名文件时拒绝覆盖。"""
    if list_dates(daily_dir):
        raise FileExistsError("记录库非空")
    src = os.path.join(paths.REPO_ROOT, "tests", "fixtures",
                       "2026-06-25_analysis.json")
    os.makedirs(daily_dir, exist_ok=True)
    target = os.path.join(daily_dir, "2026-06-25_analysis.json")
    with open(src, encoding="utf-8") as f:
        content = f.read()
    try:
        with open(target, "x", encoding="utf-8") as f:
            f.write(content)
    except FileExistsError:
        raise
    except Exception:
        if os.path.exists(target):
            os.unlink(target)
        raise
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
                       dim_key: str, indicator: str, value: str,
                       method="manual", evidence=None, action="set", client="",
                       timezone_name=None) -> dict:
    """修正或显式清除观察值：校验 → 审计 → 备份 → 形状感知写回。"""
    from src.dimensions import from_english
    from src.record import _DIMENSION_INDICATORS

    if action not in ("set", "clear"):
        return {"ok": False, "errors": ["未知修正动作"], "warnings": []}
    dim = from_english(dim_key)
    if dim is None or indicator not in _DIMENSION_INDICATORS.get(dim, {}):
        return {"ok": False, "errors": [f"未知的维度或指标: {dim_key}/{indicator}"],
                "warnings": []}
    filepath = _select_daily_file(daily_dir, date_str)
    if not filepath:
        return {"ok": False, "errors": [f"{date_str} 无记录"], "warnings": []}
    try:
        from io_utils import read_versioned_json
        raw, current_version = read_versioned_json(filepath)
    except (OSError, ValueError, TypeError) as e:
        return {"ok": False, "errors": [f"记录读取失败: {e}"], "warnings": []}
    if not isinstance(raw, dict):
        return {"ok": False, "errors": ["记录根节点不是对象"], "warnings": []}
    normalized = None
    if action == "set":
        try:
            normalized = validate_field_value(dim, indicator, value, method)
        except ValueError as e:
            return {"ok": False, "errors": [str(e)], "warnings": []}

    previous_raw = json.loads(json.dumps(raw, ensure_ascii=False))
    if not isinstance(raw.get("pristine_snapshot"), dict):
        raw["pristine_snapshot"] = create_pristine_snapshot(previous_raw, backup_dir)
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
    metadata = raw.get("observation_meta", {})
    if not isinstance(metadata, dict):
        return {"ok": False, "errors": ["记录 observation_meta 格式错误"], "warnings": []}
    full_path = f"{dim.english_name}." + ".".join(path)
    if action == "clear":
        node.pop(path[-1], None)
        metadata.pop(full_path, None)
    else:
        try:
            obs = capture_observation(dim, indicator, value.strip(), "manual", method,
                                      evidence, value=normalized)
        except ValueError as e:
            return {"ok": False, "errors": [str(e)], "warnings": []}
        metadata[obs.path] = obs.to_meta()
        if obs.normalized:
            node[path[-1]] = obs.normalized
        else:
            node.pop(path[-1], None)
    audit = raw.get("correction_audit", [])
    if not isinstance(audit, list):
        return {"ok": False, "errors": ["记录 correction_audit 格式错误"], "warnings": []}
    audit.append({"action": action, "indicator": indicator, "dimension": dim_key,
                  "value": normalized, "method": method,
                  "at": time_utils.iso_now(timezone_name)})
    raw["correction_audit"] = audit
    raw["observation_meta"] = metadata
    if rec.shape == "B":
        raw["schema_version"] = SCHEMA_VERSION
    raw["manually_corrected"] = True
    raw["corrected_at"] = time_utils.iso_now(timezone_name)

    # 重算自动触发项；仅证据消失才撤销，人工/外部无证据标记继续保留。
    from src.danger_review import refresh_danger
    try:
        events = refresh_danger(raw, previous_raw=previous_raw,
                                source="correction", client=client)
    except ValueError as error:
        return {"ok": False, "errors": [str(error)], "warnings": []}

    from src.derived import current_derived_meta
    raw["derived_meta"] = current_derived_meta(DailyRecord(raw))

    # 全部 errors 拦截；原记录已有的问题只告警，通过后备份并原子替换。
    errors, warnings = validate_candidate(
        raw, daily_dir, previous_raw=previous_raw)
    if errors:
        return {"ok": False, "errors": errors, "warnings": warnings}
    from io_utils import atomic_write_json
    backup = backup_file(filepath, backup_dir)
    atomic_write_json(filepath, raw, current_version)

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
        "danger_triggered": (raw.get("danger_flags") or {}).get("triggered", []),
        "cleared": events["cleared"], "revived": events["revived"],
        "summary": record_summary(new_rec),
    }


def list_photos(photos_dir: str, date_str: str, rec=None):
    """优先按当前记录绑定列出照片；旧记录无绑定时保留目录兼容。"""
    d = os.path.join(photos_dir, date_str)
    if not os.path.isdir(d):
        return []
    ok = (".jpg", ".jpeg", ".png", ".webp")
    if rec is not None and "photos" in rec.raw:
        registered = rec.raw["photos"]
        if not isinstance(registered, dict):
            print("⚠️ 警告: 记录 photos 不是对象，原图对照留空", file=sys.stderr)
            return []
        return sorted({value for value in registered.values()
                       if isinstance(value, str) and value == os.path.basename(value)
                       and value.lower().endswith(ok)
                       and os.path.isfile(os.path.join(d, value))})
    return sorted(f for f in os.listdir(d) if f.lower().endswith(ok))


def record_detail(rec: DailyRecord, date_str=None) -> dict:
    """单日详情页的完整视图模型；未知项与正常 0 分明确区分。"""
    identity_date = date_str or rec.date
    from src.scoring import assess_indicators
    assessments = _dim_assessments(rec)
    coverage = rec.get_dimension_coverage()
    dims = []
    for dim in DIMENSIONS:
        obs = rec.get_observation(dim)
        result = assessments[dim]
        declared_normal = (_is_declared_normal(obs)
                           or (not coverage[dim] and any(
                               d.get("kind") == "declared_normal"
                               for d in rec.get_declarations(dim))))
        covered = coverage[dim]
        scored = (assess_indicators(dim, _scoring_observation(rec, dim))
                  if covered else {})
        groups = []
        for gname, indicators in DIM_GROUPS[dim.english_name]:
            fields = []
            for ind in indicators:
                v = obs.get(ind, "")
                opts = _field_options(dim, ind)
                label = INDICATOR_REGISTRY.for_field(dim, ind).label
                base = {"k": label, "v": v, "ind": ind,
                        "kgloss": GLOSSARY.get(label),
                        "opts": opts,
                        "gloss": {o: _glossary(dim, ind, o) for o in opts
                                  if _glossary(dim, ind, o) is not None} if opts else None}
                if v == UNKNOWN_OBSERVATION_MARK:
                    fields.append({**base, "s": None, "unknown": True})
                elif ind in REF_FIELDS:
                    fields.append({**base, "s": None, "ref": REF_FIELDS[ind]})
                elif ind in scored:
                    assessment = scored[ind]
                    fields.append({**base, "s": assessment.value,
                                   "unknown": assessment.state == "unknown",
                                   "review": INDICATOR_REGISTRY.for_field(dim, ind).review or None})
                else:
                    fields.append({**base, "s": 0})
            if any(f["v"] for f in fields):
                groups.append({"name": gname, "fields": fields})
        positives = [a.value for a in scored.values() if a.state == "abnormal"]
        dims.append({
            "key": dim.english_name, "name": dim.chinese_name,
            "covered": covered,
            "declared_normal": declared_normal,
            "score": (result.value
                      if covered and result.state in ("normal", "abnormal") else None),
            "max_indicator": max(positives) if positives else None,
            "unknown_count": result.unknown_count,
            "missing_count": len(result.missing_indicators),
            "groups": groups,
        })

    known = [d["score"] for d in dims if d["score"] is not None]
    total = round(sum(known), 1)
    covered_n = rec.get_covered_dimension_count()

    pattern = rec.get_pattern_differentiation()
    if pattern and not isinstance(pattern, dict):
        print("⚠️ 警告: pattern_differentiation 不是对象，详情页忽略该字段",
              file=sys.stderr)
        pattern = {}
    diagnosis = None
    if pattern:
        tv = pattern.get("three_views") or pattern.get("三观") or {}
        if not isinstance(tv, dict):
            print("⚠️ 警告: three_views 不是对象，详情页忽略该字段", file=sys.stderr)
            tv = {}
        diagnosis = {
            "three_views": [{"k": k, "v": v} for k, v in tv.items()],
            "six_diseases": pattern.get("six_diseases") or pattern.get("六病定位", ""),
            "pathomechanism": (pattern.get("core_pathomechanism")
                               or pattern.get("核心病机", "")),
        }

    diag = rec.raw.get("diagnosis")
    report = diag.get("report") if isinstance(diag, dict) else None
    if report is not None and not isinstance(report, dict):
        print("⚠️ 警告: diagnosis.report 不是对象，详情页忽略该报告", file=sys.stderr)
        report = {}
    elif isinstance(report, dict):
        report = dict(report)
        if "markdown" in report and not isinstance(report["markdown"], str):
            print("⚠️ 警告: 报告 markdown 不是字符串，详情页省略该内容", file=sys.stderr)
        report["markdown"] = report.get("markdown") \
            if isinstance(report.get("markdown"), str) else ""
        for key in ("diet_advice", "lifestyle"):
            if key in report and not isinstance(report[key], dict):
                print(f"⚠️ 警告: 报告 {key} 不是对象，详情页忽略该字段", file=sys.stderr)
                report.pop(key)

    from src.danger import alert_evaluation_map
    evaluations = alert_evaluation_map(rec)
    flags = rec.raw.get("danger_flags", {})
    dismissed = flags.get("dismissed", []) if isinstance(flags, dict) else []
    dismissed = [key for key in dismissed if isinstance(key, str)] \
        if isinstance(dismissed, list) else []
    triggered = [key for key in rec.get_triggered_danger_flags()
                 if isinstance(key, str) and key not in dismissed]
    danger_unknown = [
        {"key": k, **DANGER_FLAGS.get(k, {"name": k, "note": ""}), **evaluation}
        for k, evaluation in evaluations.items()
        if evaluation.get("state") == "unknown"
        and k not in triggered and k not in dismissed]
    danger_not_triggered = [
        DANGER_FLAGS.get(k, {}).get("name", k)
        for k, evaluation in evaluations.items()
        if evaluation.get("state") == "not_triggered"
        and k not in triggered and k not in dismissed]
    return {
        "date": identity_date,
        "weekday": weekday_cn(identity_date) if identity_date else "",
        "coverage": covered_n,
        "coverage_total": len(DIMENSIONS),
        "confidence": rec.get_confidence(),
        "version": rec.get_version(),
        "corrected": bool(rec.raw.get("manually_corrected")),
        "dims": dims,
        "total": total,
        "total_sev": sev_class(total / len(DIMENSIONS) if known else None),
        "unknown_count": sum(r.unknown_count for r in assessments.values()),
        "missing_count": sum(len(r.missing_indicators) for r in assessments.values()),
        "danger_triggered": [
            {"key": k, **DANGER_FLAGS.get(k, {"name": k, "note": ""}),
             **evaluations.get(k, {})}
            for k in triggered],
        "danger_dismissed": [
            {"key": key, **DANGER_FLAGS.get(key, {"name": key, "note": ""}),
             **evaluations.get(key, {})}
            for key in dismissed],
        "danger_not_triggered": danger_not_triggered,
        "danger_unknown": danger_unknown,
        "danger_all": [v["name"] for v in DANGER_FLAGS.values()],
        "diagnosis": diagnosis,
        "report": report,
    }
