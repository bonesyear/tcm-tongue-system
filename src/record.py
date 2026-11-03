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
from .indicators import DIMENSION_INDICATORS, INDICATOR_REGISTRY
from .observations import UNKNOWN_OBSERVATION_MARK
from .textnorm import normalize_text


# A/B/C 路径由指标注册表统一持有；旧私有别名保留给既有调用方。
_DIMENSION_INDICATORS = DIMENSION_INDICATORS

# 形状 C 顶层维度键：规范英文名 + 兼容别名
_C_DIMENSION_KEYS = frozenset(
    [d.english_name for d in DIMENSIONS] + ["face", "palm"]
)
# 形状 C 维度键别名 → 规范英文名
_C_KEY_ALIASES = {"face": "head_face", "palm": "hand"}

# 形状 A 容器键：新名优先，旧名永久兼容（历史档案不迁移，
# 读时双收即满足"历史不追溯"原则）。新记录一律用新名。
_A_VISION_KEYS = ("vision_analysis", "doubao_vision_analysis")
_A_DIAGNOSIS_KEYS = ("diagnosis", "deepseek_diagnosis")


def _normalized_mapping(value):
    if not isinstance(value, dict):
        return {}
    out = {}
    for key, item in value.items():
        normalized = normalize_text(str(key)).replace("．", ".")
        if normalized in out and out[normalized] != item:
            print(f"⚠️ 警告: 规范化后重复键 {normalized!r}，保留首个值", file=sys.stderr)
            continue
        out[normalized] = item
    return out


def _first_present(raw: Dict[str, Any], keys: Tuple[str, ...]) -> Any:
    """取第一个非空容器；空 dict 不再遮蔽同族旧名。"""
    for key in keys:
        if key in raw:
            value = raw.get(key)
            if value is not None and (
                    not isinstance(value, dict) or not _is_empty_shell(value)):
                return value
    return None


# 「未拍摄（用户声明正常）」占位标记（单一事实来源）。
# KNOWN_ISSUES #10 的旧约定「声明正常视同覆盖」已于 v1.7.19 废止
# （原著审查 P1：占位≠亲眼所见，不计覆盖度与置信度）。
DECLARED_NORMAL_MARK = "未拍摄（用户声明正常）"
INQUIRY_TOTAL = 17


def is_declared_normal_value(value) -> bool:
    if not isinstance(value, str):
        return False
    text = normalize_text(value).replace("（", "(").replace("）", ")").replace("，", ",")
    text = re.sub(r"\s+", "", text).strip("。 .")
    return text in ("未拍摄(用户声明正常)", "正常(用户声明,未拍摄)")


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
        cur = _normalized_mapping(cur)
        if key not in cur:
            return ""
        cur = cur[key]
    if cur is None:
        return ""
    if isinstance(cur, (dict, list)):
        return normalize_text(_flatten_to_text(cur))
    return normalize_text(str(cur).strip())


def _safe_int(value: Any) -> int:
    """宽容地把记录字段转成 int;非数值(None/脏字符串)一律按 0 处理。"""
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


# 安全扫描在独立文本副本上做 NFKC，不改写原始方剂或报告。
_DOSE_NUMBER = r"(?:\d+(?:\.\d+)?|[零〇一二三四五六七八九十百千万两半]+)"
_DOSAGE_RE = re.compile(
    rf"{_DOSE_NUMBER}\s*(?:g|克|两|钱|枚|升)(?![a-z])", re.IGNORECASE)
_FORMULA_NAME_RE = re.compile(r"[一-鿿]{1,16}(?:汤|散|丸|饮)")


def has_dosage_content(value: Any) -> bool:
    """识别阿拉伯/中文数字与 g、克、两、钱、枚、升组成的剂量。"""
    import unicodedata
    return bool(_DOSAGE_RE.search(unicodedata.normalize(
        "NFKC", _flatten_to_text(value))))


def has_formula_name(value: Any) -> bool:
    """判断文本是否含以汤、散、丸、饮结尾的中文方名。"""
    import unicodedata
    return bool(_FORMULA_NAME_RE.search(unicodedata.normalize(
        "NFKC", _flatten_to_text(value))))


def has_formula_content(formula: Any) -> bool:
    """判断候选材料是否含实质方剂；结构异常不能成为放行理由。"""
    if not formula:
        return False
    if not isinstance(formula, dict):
        return bool(str(formula).strip())
    content_keys = ("name", "主方", "合方", "ingredients", "核心药组",
                    "剂量建议", "加减", "dosage", "herbs", "方名", "方剂",
                    "组成", "药物", "处方", "prescription", "composition")
    if any(formula.get(k) for k in content_keys):
        return True
    import unicodedata
    text = unicodedata.normalize("NFKC", _flatten_to_text(formula))
    return bool(_DOSAGE_RE.search(text) or _FORMULA_NAME_RE.search(text))


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


def _is_empty_shell(obs: Any) -> bool:
    """判断 observations 是否为「空壳」（B02 形状探测用）。

    空壳定义（与维度空白语义一致）：
      - None 是空壳；
      - dict 的全部叶子文本（strip 后）均为空 → 空壳；
      - 其余非 None 值（字符串、列表等）不是空壳——按"有内容"走形状 B
        （行为不变：类型错误由 validator 报告，形状探测不做结构裁判）。
    """
    if obs is None:
        return True
    if isinstance(obs, dict):
        return not _flatten_to_text(obs)
    return False


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

    无论输入是形状 A（vision_analysis，中文键；旧名
    doubao_vision_analysis 永久兼容）、形状 B（observations，英文键）
    还是形状 C（顶层规范英文维度键，兼容别名 face/palm），对外都暴露
    统一的 interface。
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
        # B：真实记录，有 observations；A：模板，有 vision_analysis
        #     （旧名 doubao_vision_analysis 同样判为 A，新名优先）；
        # C：自由格式，顶层直接含规范英文维度键（tongue/head_face/...，
        #     兼容别名 face/palm）
        # observations 为空壳或类型异常且存在 A 容器时，不得遮蔽完整 A 档。
        _obs_present = "observations" in self.raw
        _obs_root = self.raw.get("observations")
        _obs_nonempty = (_obs_present and isinstance(_obs_root, dict) and any(
            isinstance(node, dict) and not _is_empty_shell(node)
            for node in _obs_root.values()))
        _has_a = any(k in self.raw for k in _A_VISION_KEYS)
        if _obs_nonempty or (_obs_present and not _has_a):
            self._shape = "B"
        elif _has_a:
            if _obs_present:
                print(
                    "⚠️ 警告: observations 是空壳或结构异常，"
                    "但记录含 vision_analysis——按形状 A 解析，observations "
                    "已忽略，六维观测取自 vision_analysis。若这不是预期，"
                    "请核对视觉分析容器键名。",
                    file=sys.stderr,
                )
            self._shape = "A"
        elif _C_DIMENSION_KEYS & self.raw.keys():
            self._shape = "C"
        elif _obs_present:
            self._shape = "B"
        else:
            self._shape = "B"
            top_keys = ", ".join(self.raw.keys()) or "(无)"
            print(
                "⚠️ 警告: 未识别的记录形状（三判据均未命中：无 observations、"
                "无 vision_analysis、顶层无维度键 tongue/head_face/eye/ear/"
                "hand/skin），按形状 B 处理，六维观测将为空。"
                f"本记录实际顶层键: {top_keys}。"
                "若你改过视觉分析的容器键名，请改用 vision_analysis"
                "（旧名 doubao_vision_analysis 仍兼容）。",
                file=sys.stderr,
            )
        self._warned_mixed_shape: set = set()
        self._warned_nodes: set = set()

    # ---- 解析入口（interface） ----
    @classmethod
    def parse(cls, raw_json: Union[Dict[str, Any], str, bytes]) -> "DailyRecord":
        """parse(raw) → Record：标准化解析入口。"""
        return cls(raw_json)

    @property
    def shape(self) -> str:
        """当前记录被识别的形状：'A'（模板/中文键，vision_analysis，
        旧名 doubao_vision_analysis 兼容）、'B'（observations/英文键）
        或 'C'（顶层规范英文维度键，兼容别名 face/palm）。"""
        return self._shape

    @property
    def date(self) -> str:
        return str(self.raw.get("date", ""))

    def _warn_once(self, key, message):
        if key not in self._warned_nodes:
            self._warned_nodes.add(key)
            print(message, file=sys.stderr)

    # ---- 维度观测根对象 ----
    def _dimension_root(self, dim: VisionDimension) -> Dict[str, Any]:
        """取某维度在当前形状下的根对象；异常节点告警并降级为空。"""
        if self._shape == "A":
            container = _first_present(self.raw, _A_VISION_KEYS)
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
            self._warn_once("container:" + self._shape,
                            f"⚠️ 警告: {self._shape} 的维度容器不是对象，按空容器处理")
            return {}
        container = _normalized_mapping(container)
        root = container.get(key, {})
        if not isinstance(root, dict):
            self._warn_once("node:" + key,
                            f"⚠️ 警告: 维度节点 {key} 不是对象，按空节点处理")
            return {}
        return root

    def get_observation(self, dimension: VisionDimension) -> Dict[str, str]:
        """按维度取观测，返回规范化为 {规范指标: 文本} 的字典。

        形状 A↔B 的字段路径迁移在此处完成，调用方无需感知形状差异。
        缺失指标以空串占位，保证返回结构稳定。
        """
        dim = self._as_dimension(dimension)
        root = self._dimension_root(dim)
        shape_key = self._shape
        result: Dict[str, str] = {}
        metadata = self.raw.get("observation_meta", {})
        if not isinstance(metadata, dict):
            metadata = {}
        for indicator, paths in _DIMENSION_INDICATORS[dim].items():
            path = paths.get(shape_key) or paths.get("B") or paths.get("A") or []
            value = _dig(root, path)
            meta_path = f"{dim.english_name}." + ".".join(paths["B"])
            entry = metadata.get(meta_path)
            if not value and isinstance(entry, dict) and entry.get("certainty") == "unknown":
                value = UNKNOWN_OBSERVATION_MARK
            result[indicator] = value
        for spec in INDICATOR_REGISTRY:
            if spec.dimension != dim:
                continue
            for alias in spec.aliases:
                source_dim = alias.get("from_dimension", dim)
                if source_dim == dim:
                    continue
                source = alias["from_indicator"]
                paths = INDICATOR_REGISTRY.for_field(source_dim, source).paths
                path = paths.get(shape_key) or paths.get("B") or paths.get("A") or []
                value = _dig(self._dimension_root(source_dim), path)
                if value:
                    result[source] = value
        self._warn_if_mixed_shape(dim, root)
        return INDICATOR_REGISTRY.normalize_observation(dim, result)

    def get_scoring_observation(self, dimension: VisionDimension) -> Dict[str, str]:
        """取评分用观测，排除声明正常占位，原始记录保持不变。"""
        obs = self.get_observation(dimension)
        return {k: v for k, v in obs.items() if not is_declared_normal_value(v)}

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
        形状 A：diagnosis.经方六经辨证（旧名 deepseek_diagnosis 永久兼容，
        新名优先）。
        容器类型不对时返回空 dict（结构错误由 validator 报告）；
        形状 A 找不到辨证键时返回 {}，不得回落为整个 diagnosis dict
        （否则"综合辨证结论"等无关字段会污染辨证结果）。
        B02：键值为 null 时回退下一个别名/旧名，不吞成 {}。
        """
        for key in ("pattern_differentiation", "pattern_update"):
            if key in self.raw:
                val = self.raw.get(key)
                if val is None:
                    continue  # null 不截断别名回退
                return val if isinstance(val, dict) else {}
        diag = _first_present(self.raw, _A_DIAGNOSIS_KEYS) or {}
        if not isinstance(diag, dict):
            return {}
        return diag.get("经方六经辨证") or {}

    def get_formula(self) -> Any:
        """取方剂建议。

        形状 B：formula；形状 C：formula_adjust / formula_with_dosage（别名）；
        形状 A：diagnosis.方剂建议（旧名 deepseek_diagnosis 永久兼容，
        新名优先）。
        正常返回 dict；formula 字段为非 dict（如整段方剂文本）时**原样返回**，
        交 has_formula_content 判定——安全检查不能因结构异常而放行。
        B02：键值为 null 时回退下一个别名/旧名，不吞成 {}。
        """
        for key in ("formula", "formula_adjust", "formula_with_dosage"):
            if key in self.raw:
                val = self.raw.get(key)
                if val is None:
                    continue  # null 不截断别名回退
                return val or {}
        diag = _first_present(self.raw, _A_DIAGNOSIS_KEYS) or {}
        if not isinstance(diag, dict):
            return {}
        return diag.get("方剂建议", {}) or {}

    def get_formula_material(self) -> List[Any]:
        """汇总所有方剂候选；报告只取方剂/剂量相关 Markdown 段落。"""
        import unicodedata
        material = []
        for key in ("formula", "formula_adjust", "formula_with_dosage"):
            value = self.raw.get(key)
            if value:
                material.append(value)
        for key in _A_DIAGNOSIS_KEYS:
            diag = self.raw.get(key)
            if not isinstance(diag, dict):
                continue
            formula = diag.get("方剂建议")
            if formula:
                material.append(formula)
            report = diag.get("report")
            markdown = report.get("markdown") if isinstance(report, dict) else None
            if not isinstance(markdown, str):
                continue
            lines = unicodedata.normalize("NFKC", markdown).splitlines()
            starts = [index for index, line in enumerate(lines)
                      if re.match(r"^\s{0,3}#{1,6}\s+\*{0,2}(?:方剂建议|剂量建议)"
                                  r"\*{0,2}\s*[:：]?\s*$", line)
                      or re.match(r"^\s*(?:[-*+]\s+)?\*\*(?:方剂建议|剂量建议)\*\*"
                                  r"\s*[:：]?\s*$", line)]
            for index in starts:
                end = next((next_index for next_index in range(index + 1, len(lines))
                            if re.match(r"^\s{0,3}#{1,6}\s+", lines[next_index])),
                           len(lines))
                material.append({"text": "\n".join(lines[index:end])})
        return material

    def get_danger_flags(self) -> Any:
        """取安全红线（danger_flags）。两种形状键名一致，直接返回。"""
        return self.raw.get("danger_flags", {})

    def get_declarations(self, dimension=None) -> List[dict]:
        raw = self.raw.get("declarations")
        items = [dict(item) for item in raw if isinstance(item, dict)] \
            if isinstance(raw, list) else []
        if not items:
            skipped = self.raw.get("skipped_dimensions", {})
            if isinstance(skipped, dict):
                for kind, legacy in (("declared_normal", "declared_normal"),
                                     ("skipped", "uncovered")):
                    values = skipped.get(legacy, [])
                    if isinstance(values, list):
                        items.extend({"kind": kind, "dimension": dim,
                                      "part": "", "reason": ""} for dim in values)
        if dimension is not None:
            dim = self._as_dimension(dimension)
            items = [item for item in items
                     if item.get("dimension") == dim.english_name]
        return items

    def get_triggered_danger_flags(self) -> List[str]:
        """取已触发的红线列表。

        形状 B：danger_flags.triggered（列表）；形状 A：遍历 flag 对象，
        triggered 按宽松真值判定（True/'true'/'yes'/1 均算触发）——
        严格 `is True` 会让 LLM 输出的字符串 "true" 静默不触发（fail-open）。
        """
        df = self.get_danger_flags()
        if not isinstance(df, dict):
            return []
        triggered = []
        if isinstance(df.get("triggered"), list):
            triggered.extend(item for item in df["triggered"] if isinstance(item, str))
        for name, flag in df.items():
            if isinstance(flag, dict) and _is_triggered(flag.get("triggered")) \
                    and name not in triggered:
                triggered.append(name)
        return triggered

    # ---- 覆盖度与置信度 ----
    def get_dimension_coverage(self) -> Dict[VisionDimension, bool]:
        """返回每个维度是否被覆盖（有非空观测）。

        「未拍摄（用户声明正常）」占位不算覆盖（v1.7.19 起，
        DECLARED_NORMAL_MARK 约定：占位≠亲眼所见）。B02 细化：
        占位是**逐指标**剔除而非整维否决——维度内只要存在至少一个
        非空且非占位的真实观察值即算覆盖；占位与真实值混合的档案
        不再被占位拖成未覆盖，占位-only 维度照旧未覆盖。"""
        def covered(dim):
            obs = self.get_scoring_observation(dim)
            return any(v and v != UNKNOWN_OBSERVATION_MARK for v in obs.values())
        return {dim: covered(dim) for dim in DIMENSIONS}

    def get_covered_dimension_count(self) -> int:
        """已覆盖的维度数（用于置信度判定）。"""
        return sum(1 for covered in self.get_dimension_coverage().values() if covered)

    def get_inquiry_answers(self) -> Dict[str, str]:
        """统一返回 A/B/C 的已答问诊；仅展示层做规范化与限长。"""
        from .textnorm import display_text
        inquiry = self.raw.get("inquiry")
        if not isinstance(inquiry, dict):
            return {}
        answers = {}
        for question, entry in inquiry.items():
            if not isinstance(question, str):
                self._warn_once("inquiry-key", "⚠️ 警告: 忽略非字符串问诊键")
                continue
            if isinstance(entry, dict):
                if entry.get("asked") is not True:
                    continue
                answer = entry.get("answer")
            else:
                answer = entry
            if not isinstance(answer, str) or not answer.strip():
                continue
            question = display_text(question, 64)
            answer = display_text(answer, 64)
            if question and answer:
                answers[question] = answer
        return answers

    def get_inquiry_coverage(self) -> Tuple[int, int]:
        """取问诊覆盖 (已采集, 契约总数 17)。"""
        if "inquiry_coverage" in self.raw:
            coverage = self.raw.get("inquiry_coverage")
            if not isinstance(coverage, dict):
                return 0, INQUIRY_TOTAL
            covered = _safe_int(coverage.get("covered"))
            if coverage.get("total") not in (None, INQUIRY_TOTAL):
                self._warn_once("inquiry-total",
                                f"⚠️ 警告: 问诊总数 {coverage.get('total')!r} 与契约 {INQUIRY_TOTAL} 不一致")
            return covered, INQUIRY_TOTAL
        return len(self.get_inquiry_answers()), INQUIRY_TOTAL

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
