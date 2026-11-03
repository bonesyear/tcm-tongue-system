"""观察值、采集能力与声明；不依赖记录存储或 Web 框架。"""
from __future__ import annotations

from dataclasses import dataclass
import re

from .dimensions import VisionDimension
from .indicators import INDICATOR_REGISTRY
from .text_analysis import find_term


SCHEMA_VERSION = 2
UNKNOWN_OBSERVATION_MARK = "无法判读"
DECLARATION_KINDS = frozenset({"declared_normal", "skipped", "refused", "unavailable"})
_METHODS = frozenset({"photo", "video", "manual", "self_report", "inquiry", "palpation", "measurement"})
_CERTAINTIES = frozenset({"unverified", "user_confirmed", "self_reported", "unknown"})
_ABSOLUTE_MEASUREMENT_RE = re.compile(
    r"\d+(?:\.\d+)?\s*(?:毫米|mm)\b|[<>＞＜≤≥]\s*\d+(?:\.\d+)?", re.IGNORECASE)


@dataclass(frozen=True)
class Observation:
    path: str
    indicator_id: str
    source: str
    method: str
    raw: str
    certainty: str
    evidence: dict
    value: str | None = None

    @property
    def normalized(self) -> str:
        if self.certainty == "unknown":
            return ""
        return self.raw if self.value is None else self.value

    def to_meta(self) -> dict:
        return {
            "indicator_id": self.indicator_id,
            "source": self.source,
            "method": self.method,
            "raw": self.raw,
            "certainty": self.certainty,
            "evidence": dict(self.evidence),
            "value": self.normalized,
        }


@dataclass(frozen=True)
class Declaration:
    kind: str
    dimension: str
    part: str = ""
    reason: str = ""

    def __post_init__(self):
        if self.kind not in DECLARATION_KINDS:
            raise ValueError(f"未知声明类型: {self.kind}")
        self_dimension = VisionDimension(self.dimension)
        object.__setattr__(self, "dimension", self_dimension.english_name)

    def to_dict(self) -> dict:
        return {"kind": self.kind, "dimension": self.dimension,
                "part": self.part, "reason": self.reason}


def capture_observation(dimension: VisionDimension, key: str, raw: str,
                        source: str, method: str, evidence: dict | None = None,
                        value: str | None = None, certainty: str | None = None) -> Observation:
    dim = dimension if isinstance(dimension, VisionDimension) else VisionDimension(dimension)
    spec = INDICATOR_REGISTRY.for_field(dim, key)
    if method not in _METHODS:
        raise ValueError(f"未知采集方式: {method}")
    if not isinstance(raw, str):
        raise TypeError("观察原始值必须为字符串")
    if certainty is not None and certainty not in _CERTAINTIES:
        raise ValueError(f"未知观察确定性: {certainty}")
    evidence = dict(evidence or {})
    evidence.setdefault("part", spec.prompt_part)
    clothing = key == "yellow_sweat" and method == "photo" and evidence.get("kind") == "clothing"
    if key == "palm_temp" and method not in ("palpation", "inquiry", "self_report", "manual"):
        raise ValueError("掌温需要触诊或问诊/自陈，不能由照片判定")
    if method not in spec.allowed_methods and not clothing:
        if key in ("body_dynamics", "nose_flare"):
            raise ValueError(f"{spec.label}需要视频或人工动态观察，不能由静态照片直接判定")
        raise ValueError(f"{spec.label}不支持采集方式 {method}；允许：{'/'.join(spec.allowed_methods)}")
    if key == "yellow_sweat" and method not in ("inquiry", "self_report") and not clothing:
        raise ValueError("黄汗需要问诊/自陈或衣物证据，不能用普通皮肤照或默认手动输入替代")
    if dim == VisionDimension.SKIN and key == "edema" and "凹陷" in raw and method not in ("palpation", "self_report", "inquiry"):
        raise ValueError("皮肤凹陷需要人工触诊或自陈，不能由静态照片或默认手动输入直接判定")

    unknown_reason = ""
    if key == "sublingual_thickness" and _ABSOLUTE_MEASUREMENT_RE.search(raw) and evidence.get("has_scale") is not True:
        unknown_reason = "无比例尺，不能输出绝对毫米或毫米阈值结论"
    if key == "lower_lid" and evidence.get("exposed") is not True:
        unknown_reason = "未暴露下睑结膜，不能判定下睑颜色"
    if unknown_reason:
        evidence["unknown_reason"] = unknown_reason
        certainty = "unknown"
    if certainty is None:
        certainty = {"vision": "unverified", "manual": "user_confirmed"}.get(source, "self_reported")
    if certainty not in _CERTAINTIES:
        raise ValueError(f"未知观察确定性: {certainty}")
    return Observation(
        path=f"{dim.english_name}." + ".".join(spec.paths["B"]),
        indicator_id=spec.id,
        source=source,
        method=method,
        raw=raw.strip(),
        certainty=certainty,
        evidence=evidence,
        value=value,
    )


def is_absolute_measurement(text: str) -> bool:
    return isinstance(text, str) and bool(_ABSOLUTE_MEASUREMENT_RE.fullmatch(text.strip()))


def _choose(text: str, candidates: tuple[str, ...]) -> str | None:
    return next((term for term in candidates if find_term(text, term).state == "matched"), None)


def split_coating_text(text: str) -> dict[str, str]:
    """把已采集的复合舌苔描述分轴；未观察到的轴不补值。"""
    if not isinstance(text, str):
        raise TypeError("舌苔原始描述必须为字符串")
    fields = {}
    candidates = {
        "color": ("灰黑", "白", "黄", "灰", "黑"),
        "moisture": ("干裂", "偏干", "稍干", "滑", "燥", "润"),
        "greasy": ("厚腻", "微腻", "稍腻", "偏腻", "腐苔", "腻"),
        "peeling": ("地图舌", "镜面", "花剥", "剥脱", "剥落"),
        "distribution": ("偏布一侧", "满布"),
    }
    for axis, terms in candidates.items():
        value = _choose(text, terms)
        if value:
            fields[axis] = value
    if "局部无苔" in text:
        fields["amount"] = "苔少"
    else:
        amount = _choose(text, ("无苔", "苔少", "苔多"))
        if amount:
            fields["amount"] = amount
    if "局部无苔" not in text:
        thickness = _choose(text, (
            "厚腻", "白厚", "黄厚", "焦黑", "薄黄", "薄白", "无苔",
            "略厚", "稍厚", "偏厚", "薄",
        ))
        if thickness:
            fields["thickness"] = thickness
    return fields


def _actual_value(observations, path):
    current = observations
    for key in path:
        if not isinstance(current, dict):
            return ""
        current = current.get(key, "")
    return current


def validate_observation_metadata(metadata, observations=None) -> list[str]:
    if not isinstance(metadata, dict):
        return ["❌ observation_meta 应为对象"]
    specs = {
        f"{spec.dimension.english_name}." + ".".join(spec.paths["B"]): spec
        for spec in INDICATOR_REGISTRY
    }
    errors = []
    for path, meta in metadata.items():
        if not isinstance(meta, dict):
            errors.append(f"❌ observation_meta.{path} 应为对象")
            continue
        raw = meta.get("raw")
        source, method = meta.get("source"), meta.get("method")
        certainty, evidence = meta.get("certainty"), meta.get("evidence")
        if not isinstance(raw, str) or not isinstance(source, str) or not source.strip():
            errors.append(f"❌ observation_meta.{path} 的 raw/source 无效")
            continue
        if method not in _METHODS:
            errors.append(f"❌ observation_meta.{path} 的采集方式无效: {method}")
            continue
        if certainty not in _CERTAINTIES:
            errors.append(f"❌ observation_meta.{path} 的 certainty 无效")
            continue
        if not isinstance(evidence, dict):
            errors.append(f"❌ observation_meta.{path} 的 evidence 应为对象")
            continue
        spec = specs.get(path)
        if spec is None:
            if certainty == "unknown" and meta.get("value") not in (None, ""):
                errors.append(f"❌ observation_meta.{path}: unknown 不应带规范化观察值")
            if method == "photo" and any(term in raw for term in ("舌强", "语謇", "不能语")):
                errors.append(f"❌ observation_meta.{path}: 舌强语謇需视频或人工动态/问诊")
            continue
        if meta.get("indicator_id", spec.id) != spec.id:
            errors.append(f"❌ observation_meta.{path} 的 indicator_id 不匹配")
            continue
        try:
            obs = capture_observation(spec.dimension, spec.key, raw, source, method,
                                      evidence, value=meta.get("value"), certainty=certainty)
        except (TypeError, ValueError) as e:
            errors.append(f"❌ observation_meta.{path}: {e}")
            continue
        if meta.get("value", obs.normalized) != obs.normalized:
            errors.append(f"❌ observation_meta.{path}: value 与采集能力不一致"
                          f"（certainty={certainty}）")
        if observations is not None:
            actual = _actual_value(
                observations, [spec.dimension.english_name, *spec.paths["B"]])
            if actual and actual != obs.normalized:
                errors.append(f"❌ observation_meta.{path}: value 与 observations 不一致")
            if certainty == "unknown" and actual:
                errors.append(f"❌ observation_meta.{path}: unknown 不应带可评分观察值")
    return errors


def validate_declarations(declarations) -> list[str]:
    if not isinstance(declarations, list):
        return ["❌ declarations 应为列表"]
    errors = []
    for index, item in enumerate(declarations):
        if not isinstance(item, dict):
            errors.append(f"❌ declarations[{index}] 应为对象")
            continue
        if not isinstance(item.get("part", ""), str) or not isinstance(item.get("reason", ""), str):
            errors.append(f"❌ declarations[{index}] 的 part/reason 应为文本")
            continue
        try:
            Declaration(item.get("kind"), item.get("dimension"),
                        item.get("part", ""), item.get("reason", ""))
        except (TypeError, ValueError) as e:
            errors.append(f"❌ declarations[{index}]: {e}")
    return errors
