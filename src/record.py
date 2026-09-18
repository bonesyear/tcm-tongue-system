#!/usr/bin/env python3
"""
望诊记录模块（Daily Record module）
=====================================

本模块拥有"一份望诊记录"的形状，把"形状 A（模板格式，中文键）"、
"形状 B（真实 LLM 产出格式，observations 英文键）"与"形状 C（自由格式，
顶层规范英文维度键）"的兼容/迁移逻辑全部藏在 implementation 里。

Interface（小而稳）：
    DailyRecord(raw_json)            # 接受 dict 或 JSON 字符串，自动解析
    record.get_observation(dim)      # 按维度取观测（规范化为 {指标: 文本}）
    record.get_observation_text(dim) # 按维度取观测的纯文本拼接
    record.get_pattern_differentiation()
    record.get_formula()
    record.get_danger_flags()
    record.get_dimension_coverage() / get_covered_dimension_count()
    record.get_inquiry_coverage()
    record.get_confidence()

校验器与周报生成器都退化为本 module 的 adapter，只认 Record interface，
不再各自手抄字段路径 → 形状只在一处定义，改一次全改。

设计语汇：这是首选深 module——删掉它，"记录形状"的
复杂度会立刻重现到模板、校验器、周报三个调用方。
"""

import json
import re
import sys
from typing import Any, Dict, List, Optional, Tuple, Union

from .dimensions import VisionDimension, DIMENSIONS, from_english, from_chinese


# ============================================================
# 形状规范：每个维度的"规范指标"及其在形状 A / B / C 中的字段路径
# ============================================================
# 形状 A：模板/校验器期望的 doubao_vision_analysis.<中文维度>.<中文路径>
# 形状 B：真实记录的 observations.<英文维度>.<英文路径>
# 形状 C：顶层直接用规范英文维度键（tongue/head_face/...，兼容别名
#         face→head_face、palm→hand），维度下的指标键即规范指标名，
#         故 C 路径为恒等映射 ["<指标名>"]。
# 路径用 list 表示嵌套取值；同一规范指标在各形状下各一条路径。
#
# 这里集中维护"形状"，是消除四处各表的核心。

_DIMENSION_INDICATORS: Dict[VisionDimension, Dict[str, Dict[str, List[str]]]] = {
    VisionDimension.TONGUE: {
        "body_color":              {"A": ["舌质颜色"],         "B": ["body", "color"],              "C": ["body_color"]},
        "body_luster":             {"A": ["舌质润燥"],         "B": ["body", "luster"],             "C": ["body_luster"]},
        "body_size":               {"A": ["舌体胖瘦"],         "B": ["body", "shape"],              "C": ["body_size"]},
        "petechiae":               {"A": ["瘀斑瘀点"],         "B": ["body", "ecchymosis"],         "C": ["petechiae"]},
        "tooth_marks":             {"A": ["齿痕"],             "B": ["body", "tooth_marks"],        "C": ["tooth_marks"]},
        "fissure":                 {"A": ["裂纹"],             "B": ["body", "cracks"],             "C": ["fissure"]},
        "prickles":                {"A": ["点刺"],             "B": ["body", "prickles"],           "C": ["prickles"]},
        "body_dynamics":           {"A": ["舌体动态"],         "B": ["body", "dynamics"],           "C": ["body_dynamics"]},
        "coating_color":           {"A": ["舌苔颜色"],         "B": ["coating", "color"],           "C": ["coating_color"]},
        "coating_thickness":       {"A": ["舌苔厚薄"],         "B": ["coating", "thickness"],       "C": ["coating_thickness"]},
        "coating_moisture":        {"A": ["舌苔润燥"],         "B": ["coating", "moisture"],        "C": ["coating_moisture"]},
        "coating_greasy":          {"A": ["舌苔腻腐"],         "B": ["coating", "greasy"],          "C": ["coating_greasy"]},
        "coating_peeling":         {"A": ["舌苔剥落"],         "B": ["coating", "peeling"],         "C": ["coating_peeling"]},
        "coating_distribution":    {"A": ["舌苔分布"],         "B": ["coating", "distribution"],    "C": ["coating_distribution"]},
        "sublingual_color":        {"A": ["舌下络脉颜色"],     "B": ["sublingual", "vein_color"],   "C": ["sublingual_color"]},
        "sublingual_thickness":    {"A": ["舌下络脉粗细"],     "B": ["sublingual", "vein_thickness"], "C": ["sublingual_thickness"]},
        "sublingual_varicosity":   {"A": ["舌下络脉迂曲"],     "B": ["sublingual", "vein_tortuosity"], "C": ["sublingual_varicosity"]},
        "sublingual_petechiae":    {"A": ["舌下络脉瘀点"],     "B": ["sublingual", "petechiae"],    "C": ["sublingual_petechiae"]},
    },
    VisionDimension.HEAD_FACE: {
        "face_color":    {"A": ["面域", "面色"],     "B": ["face", "color"],   "C": ["face_color"]},
        "face_edema":    {"A": ["面域", "面部水肿"], "B": ["face", "edema"],   "C": ["face_edema"]},
        "face_luster":   {"A": ["面域", "光泽"],     "B": ["face", "luster"],  "C": ["face_luster"]},
        "lip_color":     {"A": ["唇域", "唇色"],     "B": ["lips", "color"],   "C": ["lip_color"]},
        "lip_moisture":  {"A": ["唇域", "唇润燥"],   "B": ["lips", "moisture"], "C": ["lip_moisture"]},
        "lip_around":    {"A": ["唇域", "唇周"],     "B": ["lips", "around"],  "C": ["lip_around"]},
        "nose_color":    {"A": ["鼻域", "鼻色"],     "B": ["nose", "color"],   "C": ["nose_color"]},
        "nose_flare":    {"A": ["鼻域", "鼻翼煽动"], "B": ["nose", "flaring"], "C": ["nose_flare"]},
        "nose_bleeding": {"A": ["鼻域", "鼻衄"],     "B": ["nose", "bleeding"], "C": ["nose_bleeding"]},
    },
    VisionDimension.EYE: {
        "redness":       {"A": ["目赤"],         "B": ["redness"],          "C": ["redness"]},
        "jaundice":      {"A": ["巩膜黄染"],     "B": ["scleral_jaundice"], "C": ["jaundice"]},
        "edema":         {"A": ["眼睑浮肿"],     "B": ["eyelid_edema"],     "C": ["edema"]},
        "dark_orbit":    {"A": ["目眶黯黑"],     "B": ["orbital_color"],    "C": ["dark_orbit"]},
        "sclera_color":  {"A": ["巩膜颜色"],     "B": ["sclera_color"],     "C": ["sclera_color"]},
    },
    VisionDimension.EAR: {
        "color":  {"A": ["耳色"], "B": ["color"], "C": ["color"]},
        "helix":  {"A": ["耳轮"], "B": ["helix"], "C": ["helix"]},
    },
    VisionDimension.HAND: {
        "palm_color":  {"A": ["手掌颜色"], "B": ["palm_color"],       "C": ["palm_color"]},
        "palm_temp":   {"A": ["手掌温度"], "B": ["palm_temperature"], "C": ["palm_temp"]},
        "nail_color":  {"A": ["甲床颜色"], "B": ["nail_bed"],         "C": ["nail_color"]},
        "nail_shape":  {"A": ["甲床形态"], "B": ["nail_shape"],       "C": ["nail_shape"]},
        "ecchymosis":  {"A": ["手掌瘀斑"], "B": ["ecchymosis"],       "C": ["ecchymosis"]},
    },
    VisionDimension.SKIN: {
        "color":         {"A": ["肤色"], "B": ["color"],        "C": ["color"]},
        "cuo":           {"A": ["甲错"], "B": ["scaly_skin"],   "C": ["cuo"]},
        "yellow_sweat":  {"A": ["黄汗"], "B": ["yellow_sweat"], "C": ["yellow_sweat"]},
        "edema":         {"A": ["水肿"], "B": ["edema"],        "C": ["edema"]},
        "dryness":       {"A": ["干燥"], "B": ["dryness"],      "C": ["dryness"]},
    },
}

# 形状 C 顶层维度键：规范英文名 + 兼容别名
_C_DIMENSION_KEYS = frozenset(
    [d.english_name for d in DIMENSIONS] + ["face", "palm"]
)
# 形状 C 维度键别名 → 规范英文名
_C_KEY_ALIASES = {"face": "head_face", "palm": "hand"}


# 顶层必填字段 schema（数据驱动 validator 用）。
# 三种形状的顶层键不同，这里给出共性的"存在性判据"。
SCHEMA = {
    "top_required_any": ["date"],  # 两种形状都必有
    "dimensions": DIMENSIONS,      # 六维规范枚举
    "dimension_indicators": _DIMENSION_INDICATORS,
}


def _dig(obj: Any, path: List[str]) -> str:
    """按路径逐层取值，返回叶子字符串；任一层缺失返回 ''。"""
    cur = obj
    for key in path:
        if not isinstance(cur, dict) or key not in cur:
            return ""
        cur = cur[key]
    if cur is None:
        return ""
    if isinstance(cur, (dict, list)):
        # 嵌套对象：把所有叶子文本拼出（兜底）
        return _flatten_to_text(cur)
    return str(cur).strip()


def _safe_int(value: Any) -> int:
    """宽容地把记录字段转成 int;非数值(None/脏字符串)一律按 0 处理。"""
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


# 方剂内容兜底扫描：剂量模式（如 "桂枝10g"、"10 g"、"10克"）
_DOSAGE_RE = re.compile(r"\d+\s*[gG克]")
# 常见经方名（白名单键未命中时，值中出现方名即算有方剂内容）
_CLASSIC_FORMULA_RE = re.compile(
    r"桂枝汤|麻黄汤|葛根汤|小青龙汤|大青龙汤|白虎汤|大承气汤|小承气汤|"
    r"调胃承气汤|小柴胡汤|大柴胡汤|柴胡桂枝干姜汤|半夏泻心汤|生姜泻心汤|"
    r"甘草泻心汤|五苓散|苓桂术甘汤|真武汤|四逆汤|当归四逆汤|芍药甘草汤|"
    r"桂枝茯苓丸|桃核承气汤|抵当汤|茵陈蒿汤|栀子豉汤|小建中汤|炙甘草汤"
)


def has_formula_content(formula: Any) -> bool:
    """判断方剂对象是否携带任何实质内容(方名/成分/药组/剂量)。

    安全边界检查("LOW 禁方剂")专用:只认 name/主方 两个键会漏掉
    "无方名但携带 12 味药材+具体剂量" 的记录——处方的实质是药物与剂量,
    不是方名。非 dict 的非空值(如整段方剂文本)同样算有内容,
    结构异常不能成为安全检查的放行理由(fail-closed)。

    键白名单之外还有兜底扫描：任意值中出现剂量模式（\\d+[g克]）或
    常见经方名（如桂枝汤/小柴胡汤）即判为有方剂内容——白名单键名
    漂移（如 {"description": "含桂枝10g"}）不能成为放行理由。
    """
    if not formula:
        return False
    if not isinstance(formula, dict):
        return bool(str(formula).strip())
    content_keys = ("name", "主方", "合方", "ingredients", "核心药组",
                    "剂量建议", "加减", "dosage", "herbs")
    if any(formula.get(k) for k in content_keys):
        return True
    text = _flatten_to_text(formula)
    return bool(_DOSAGE_RE.search(text) or _CLASSIC_FORMULA_RE.search(text))


def _flatten_to_text(obj: Any) -> str:
    """递归收集对象内所有非空字符串叶子，用空格拼接。"""
    parts: List[str] = []
    if isinstance(obj, dict):
        for v in obj.values():
            t = _flatten_to_text(v)
            if t:
                parts.append(t)
    elif isinstance(obj, list):
        for v in obj:
            t = _flatten_to_text(v)
            if t:
                parts.append(t)
    elif obj is None:
        return ""
    else:
        s = str(obj).strip()
        return s if s else ""
    return " ".join(parts)


# danger_flags 的宽松真值判定：LLM 可能把布尔输出为字符串 "true"/"yes"
# 或数值 1，严格 `is True` 会让真值意图的红线静默不触发（fail-open）。
# 注意：validator 对形状 A 的非布尔 triggered 仍报 error（输入层把关），
# 这里的宽松化面向 Record 的消费方（周报/报告），双保险不冲突。
_TRUE_FLAG_STRINGS = ("true", "yes", "1")


def _is_triggered(value: Any) -> bool:
    """danger_flags.triggered 的宽松真值判断（True/'true'/'yes'/1 均算触发）。"""
    if isinstance(value, str):
        return value.strip().lower() in _TRUE_FLAG_STRINGS
    return value is True or value == 1


class DailyRecord:
    """一份望诊日报记录的规范化表示。

    无论输入是形状 A（doubao_vision_analysis，中文键）、形状 B
    （observations，英文键）还是形状 C（顶层规范英文维度键，兼容
    别名 face/palm），对外都暴露统一的 interface。
    """

    def __init__(self, raw_json: Union[Dict[str, Any], str, bytes]):
        """接受 dict 或 JSON 字符串/字节，自动解析并探测形状。"""
        if isinstance(raw_json, (str, bytes)):
            self.raw: Dict[str, Any] = json.loads(raw_json)
        elif isinstance(raw_json, dict):
            self.raw = raw_json
        else:
            raise TypeError(f"DailyRecord 不支持的类型: {type(raw_json).__name__}")

        # 形状探测（优先级 B > A > C > 默认 B）：
        # B：真实记录，有 observations；A：模板，有 doubao_vision_analysis；
        # C：自由格式，顶层直接含规范英文维度键（tongue/head_face/...，
        #     兼容别名 face/palm）
        if "observations" in self.raw:
            self._shape = "B"
        elif "doubao_vision_analysis" in self.raw:
            self._shape = "A"
        elif _C_DIMENSION_KEYS & self.raw.keys():
            self._shape = "C"
        else:
            # 三种判据都不满足：默认按 B 处理，
            # 各维度观测将返回空，由 validator/调用方判定。
            self._shape = "B"
        # 形状 C 混合形状警告的去重记录（每维度至多打一次）
        self._warned_mixed_shape: set = set()

    # ---- 解析入口（interface） ----
    @classmethod
    def parse(cls, raw_json: Union[Dict[str, Any], str, bytes]) -> "DailyRecord":
        """parse(raw) → Record：标准化解析入口。"""
        return cls(raw_json)

    @property
    def shape(self) -> str:
        """当前记录被识别的形状：'A'（模板/中文键）、'B'（observations/英文键）
        或 'C'（顶层规范英文维度键，兼容别名 face/palm）。"""
        return self._shape

    @property
    def date(self) -> str:
        return str(self.raw.get("date", ""))

    # ---- 维度观测根对象 ----
    def _dimension_root(self, dim: VisionDimension) -> Dict[str, Any]:
        """取某维度在当前形状下的根对象。

        形状 C 的维度节点在顶层，维度键为规范英文名，兼容别名
        face→head_face、palm→hand（规范键优先于别名）。
        容器或维度节点类型不对(如 observations 是字符串)一律按空 dict
        处理——库层不崩,由 validator 的结构校验负责报错。
        """
        if self._shape == "A":
            container = self.raw.get("doubao_vision_analysis")
            key = dim.chinese_name
        elif self._shape == "C":
            container = self.raw
            key = dim.english_name
            if key not in container:
                for alias, canonical in _C_KEY_ALIASES.items():
                    if canonical == key and alias in container:
                        key = alias
                        break
        else:
            container = self.raw.get("observations")
            key = dim.english_name
        if not isinstance(container, dict):
            return {}
        root = container.get(key, {})
        return root if isinstance(root, dict) else {}

    def get_observation(self, dimension: VisionDimension) -> Dict[str, str]:
        """按维度取观测，返回规范化为 {规范指标: 文本} 的字典。

        形状 A↔B 的字段路径迁移在此处完成，调用方无需感知形状差异。
        缺失指标以空串占位，保证返回结构稳定。
        """
        dim = self._as_dimension(dimension)
        root = self._dimension_root(dim)
        shape_key = self._shape
        result: Dict[str, str] = {}
        for indicator, paths in _DIMENSION_INDICATORS[dim].items():
            path = paths.get(shape_key) or paths.get("B") or paths.get("A") or []
            result[indicator] = _dig(root, path)
        self._warn_if_mixed_shape(dim, root)
        return result

    def _warn_if_mixed_shape(self, dim: VisionDimension,
                             root: Dict[str, Any]) -> None:
        """形状 C 下维度节点含未识别键时打 warning，并列出被丢弃的键名。

        旧口径只在维度节点全部解析不到时才告警；部分解析成功时漂移键被
        静默丢弃——实测 08-02 的 tongue 10 键中 body_shape/teeth_marks/
        crack/sublingual_veins 4 键无声丢失，其中 sublingual_veins 的值
        是「异常—中度血瘀」铁证级数据。现升级为「存在未识别键即告警」。
        仅打警告：不抛异常、不改变返回语义、不影响覆盖度与评分；
        每记录每维度至多打一次（_warned_mixed_shape 去重）。
        未识别键全为空值占位时不触发（没有实质内容被丢弃）；
        维度键根本没写（缺失 ≠ 漂移）也不触发。
        """
        if (self._shape != "C" or dim in self._warned_mixed_shape
                or not isinstance(root, dict) or not root):
            return
        known = set(_DIMENSION_INDICATORS[dim])
        dropped = [k for k in root if k not in known]
        if not dropped:
            return
        if not _flatten_to_text({k: root[k] for k in dropped}):
            return  # 未识别键只有空值占位，不算"有内容被丢弃"
        self._warned_mixed_shape.add(dim)
        print(
            f"⚠️ 警告: 形状 C 记录的维度节点 {dim.english_name!r} 含未识别键: "
            f"{', '.join(dropped)} —— 这些键的值不会进入评分，"
            f"请核对是否为键名漂移（规范键名见形状 C 规范）或混合形状"
            f"（B 式嵌套 body/coating/sublingual）",
            file=sys.stderr,
        )

    def get_observation_text(self, dimension: VisionDimension) -> str:
        """按维度取观测的纯文本拼接（供打分/展示）。"""
        obs = self.get_observation(dimension)
        return " ".join(v for v in obs.values() if v)

    def get_pattern_differentiation(self) -> Dict[str, Any]:
        """取辨证结果。

        形状 B：pattern_differentiation；形状 C：pattern_update（别名）；
        形状 A：deepseek_diagnosis.许家栋经方辨证。
        容器类型不对时返回空 dict（结构错误由 validator 报告）；
        形状 A 找不到辨证键时返回 {}，不得回落为整个 diagnosis dict
        （否则"综合辨证结论"等无关字段会污染辨证结果）。
        """
        for key in ("pattern_differentiation", "pattern_update"):
            if key in self.raw:
                val = self.raw.get(key) or {}
                return val if isinstance(val, dict) else {}
        diag = self.raw.get("deepseek_diagnosis") or {}
        if not isinstance(diag, dict):
            return {}
        return diag.get("许家栋经方辨证") or {}

    def get_formula(self) -> Any:
        """取方剂建议。

        形状 B：formula；形状 C：formula_adjust / formula_with_dosage（别名）；
        形状 A：deepseek_diagnosis.方剂建议。
        正常返回 dict；formula 字段为非 dict（如整段方剂文本）时**原样返回**，
        交 has_formula_content 判定——安全检查不能因结构异常而放行。
        """
        for key in ("formula", "formula_adjust", "formula_with_dosage"):
            if key in self.raw:
                return self.raw.get(key) or {}
        diag = self.raw.get("deepseek_diagnosis") or {}
        if not isinstance(diag, dict):
            return {}
        return diag.get("方剂建议", {}) or {}

    def get_danger_flags(self) -> Any:
        """取安全红线（danger_flags）。两种形状键名一致，直接返回。"""
        return self.raw.get("danger_flags", {})

    def get_triggered_danger_flags(self) -> List[str]:
        """取已触发的红线列表。

        形状 B：danger_flags.triggered（列表）；形状 A：遍历 flag 对象，
        triggered 按宽松真值判定（True/'true'/'yes'/1 均算触发）——
        严格 `is True` 会让 LLM 输出的字符串 "true" 静默不触发（fail-open）。
        """
        df = self.get_danger_flags()
        if not isinstance(df, dict):
            return []
        if "triggered" in df and isinstance(df["triggered"], list):
            return list(df["triggered"])
        triggered = []
        for name, flag in df.items():
            if isinstance(flag, dict) and _is_triggered(flag.get("triggered")):
                triggered.append(name)
        return triggered

    # ---- 覆盖度与置信度 ----
    def get_dimension_coverage(self) -> Dict[VisionDimension, bool]:
        """返回每个维度是否被覆盖（有非空观测）。"""
        return {dim: dim.is_covered(self.get_observation(dim)) for dim in DIMENSIONS}

    def get_covered_dimension_count(self) -> int:
        """已覆盖的维度数（用于置信度判定）。"""
        return sum(1 for covered in self.get_dimension_coverage().values() if covered)

    def get_inquiry_coverage(self) -> Tuple[int, int]:
        """取问诊覆盖 (已采集, 总数)。

        形状 B：inquiry_coverage.covered / total；形状 A：inquiry 中 asked=True 计数；
        形状 C：inquiry 为 {问题: 回答字符串} 扁平字典，值为非空字符串则计 1。
        """
        if "inquiry_coverage" in self.raw:
            cov = self.raw.get("inquiry_coverage")
            if not isinstance(cov, dict):
                return 0, 0
            return _safe_int(cov.get("covered")), _safe_int(cov.get("total"))
        inquiry = self.raw.get("inquiry", {}) or {}
        if isinstance(inquiry, dict):
            if self._shape == "C":
                answered = sum(
                    1 for v in inquiry.values()
                    if isinstance(v, str) and v.strip()
                )
                return answered, len(inquiry)
            asked = sum(
                1 for item in inquiry.values()
                if isinstance(item, dict) and item.get("asked") is True
            )
            return asked, len(inquiry)
        return 0, 0

    def get_confidence(self) -> Optional[str]:
        """取记录自报的置信度（如 'HIGH'）。形状 A 无此字段返回 None。"""
        val = self.raw.get("confidence")
        return str(val).strip() if val else None

    def get_version(self) -> Optional[str]:
        """取记录自报的版本号。"""
        val = self.raw.get("version")
        return str(val).strip() if val else None

    # ---- 工具 ----
    @staticmethod
    def _as_dimension(dim) -> VisionDimension:
        if isinstance(dim, VisionDimension):
            return dim
        # 兼容传入中/英文名;未知名必须报错——静默回落到舌诊会把
        # 拼写错误变成"看似合理实则张冠李戴"的观测(scoring 同样抛 ValueError)
        parsed = from_english(str(dim)) or from_chinese(str(dim))
        if parsed is None:
            raise ValueError(f"未知的望诊维度: {dim!r}(合法值见 dimensions.DIMENSIONS)")
        return parsed
