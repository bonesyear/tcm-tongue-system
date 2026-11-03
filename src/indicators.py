"""指标注册表：记录路径、选项、采集元数据、术语、出处与预警链接。"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Dict, Iterable

from .dimensions import VisionDimension
from .scoring import DIMENSION_RULES


TEXTBOOK_SHA256 = "88496913d72b514865b8076cfb24e1d5524606b67b7a3facb594d908eefe9db7"
JINGFANG_SHA256 = "2a4d5c99ec0ed075e645a60573c1dd9c48d3410c91e0133e04c3c8bed938d099"


@dataclass(frozen=True)
class SourceRef:
    source_id: str
    sha256: str
    keyword: str
    locator: str


@dataclass(frozen=True)
class IndicatorSpec:
    id: str
    key: str
    dimension: VisionDimension
    paths: Dict[str, list[str]]
    label: str
    source_refs: tuple[SourceRef, ...]
    prompt_part: str | None = None
    prompt_key: str | None = None
    prompt_aliases: tuple[str, ...] = ()
    prompt_options: tuple[str, ...] | None = None
    options: tuple[str, ...] | None = None
    scoring: bool = True
    allowed_methods: tuple[str, ...] = ("photo", "manual", "self_report")
    unknown_semantics: str = "非空未命中=unknown；明确正常/否定=normal；缺失=not_applicable"
    glossary: Dict[str, str] = field(default_factory=dict)
    alert_links: tuple[str, ...] = ()
    review: str = ""
    reference_reason: str = ""
    aliases: tuple[dict, ...] = ()

    def __post_init__(self):
        if self.options is None:
            rules = DIMENSION_RULES.get(self.dimension, {}).get(self.key, {})
            options = tuple(rules) or tuple(FIELD_OPTIONS.get(self.key, ())) or None
            object.__setattr__(self, "options", options)
        if self.prompt_options is None:
            object.__setattr__(self, "prompt_options",
                               _PROMPT_OPTIONS.get(self.id, self.options))


INDICATOR_LABELS = {
    "body_color": "颜色", "body_luster": "光泽", "body_size": "形态",
    "petechiae": "瘀斑瘀点", "tooth_marks": "齿痕", "fissure": "裂纹",
    "prickles": "点刺", "body_dynamics": "动态",
    "coating_color": "苔色", "coating_thickness": "厚薄",
    "coating_moisture": "润燥", "coating_greasy": "腻腐",
    "coating_peeling": "剥落", "coating_amount": "苔量", "coating_distribution": "分布",
    "sublingual_color": "颜色", "sublingual_thickness": "粗细",
    "sublingual_varicosity": "迂曲", "sublingual_petechiae": "瘀点",
    "face_color": "面色", "face_edema": "浮肿", "face_luster": "光泽",
    "lip_color": "唇色", "lip_moisture": "润燥",
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


FIELD_OPTIONS = {
    "body_luster": ["荣润", "少华", "枯"],
    "prickles": ["无", "少量", "点刺", "芒刺"],
    "body_dynamics": ["正常", "颤动", "歪斜", "痿软", "强硬", "短缩", "吐弄"],
    "coating_amount": ["无苔", "苔少", "适中", "苔多"],
    "coating_distribution": ["满布", "偏布一侧"],
    "nose_color": ["正常", "红赤", "青黑", "枯槁"],
    "nose_bleeding": ["无", "少量", "较多"],
    "palm_temp": ["温", "凉", "不温", "厥冷"],
}


REFERENCE_FIELDS = {
    "prickles": "退出评分层，仅供辨证（凸起需触诊，照片判不准）",
    "palm_temp": "照片不可判，已降级为参考项（温度需触诊）",
    "body_luster": "不参与评分，仅供辨证（光泽受光线/闪光灯干扰，静态照片不可判）",
    "body_dynamics": "不参与评分，仅供辨证（动态体征需动态观察；红线词仍会触发危险信号）",
    "coating_amount": "苔量独立记录，不与厚薄/剥落混为同一轴，不单独评分",
    "coating_distribution": "不参与评分，仅供辨证",
    "nose_color": "不参与评分，仅供辨证",
    "nose_bleeding": "不参与评分，仅供辨证（发作事件照片拍不到，以自陈为准）",
}


REVIEW_FIELDS = {
    "jaundice": "急性黄疸红线相关，需肉眼复核",
    "face_color": "红赤需与戴阳鉴别复核（太阳面赤 vs 戴阳面红如妆）",
    "sublingual_varicosity": "血证核心体征，需肉眼复核",
    "tooth_marks": "识图抖动高发字段，需肉眼复核",
    "coating_greasy": "识图抖动高发字段，需肉眼复核",
    "coating_thickness": "识图抖动高发字段，需肉眼复核",
}


_PATHS = {
    VisionDimension.TONGUE: {
        "body_color": {"A": ["舌质颜色"], "B": ["body", "color"], "C": ["body_color"]},
        "body_luster": {"A": ["舌质润燥"], "B": ["body", "luster"], "C": ["body_luster"]},
        "body_size": {"A": ["舌体胖瘦"], "B": ["body", "shape"], "C": ["body_size"]},
        "petechiae": {"A": ["瘀斑瘀点"], "B": ["body", "ecchymosis"], "C": ["petechiae"]},
        "tooth_marks": {"A": ["齿痕"], "B": ["body", "tooth_marks"], "C": ["tooth_marks"]},
        "fissure": {"A": ["裂纹"], "B": ["body", "cracks"], "C": ["fissure"]},
        "prickles": {"A": ["点刺"], "B": ["body", "prickles"], "C": ["prickles"]},
        "body_dynamics": {"A": ["舌体动态"], "B": ["body", "dynamics"], "C": ["body_dynamics"]},
        "coating_color": {"A": ["舌苔颜色"], "B": ["coating", "color"], "C": ["coating_color"]},
        "coating_thickness": {"A": ["舌苔厚薄"], "B": ["coating", "thickness"], "C": ["coating_thickness"]},
        "coating_moisture": {"A": ["舌苔润燥"], "B": ["coating", "moisture"], "C": ["coating_moisture"]},
        "coating_greasy": {"A": ["舌苔腻腐"], "B": ["coating", "greasy"], "C": ["coating_greasy"]},
        "coating_peeling": {"A": ["舌苔剥落"], "B": ["coating", "peeling"], "C": ["coating_peeling"]},
        "coating_amount": {"A": ["舌苔量"], "B": ["coating", "amount"], "C": ["coating_amount"]},
        "coating_distribution": {"A": ["舌苔分布"], "B": ["coating", "distribution"], "C": ["coating_distribution"]},
        "sublingual_color": {"A": ["舌下络脉颜色"], "B": ["sublingual", "vein_color"], "C": ["sublingual_color"]},
        "sublingual_thickness": {"A": ["舌下络脉粗细"], "B": ["sublingual", "vein_thickness"], "C": ["sublingual_thickness"]},
        "sublingual_varicosity": {"A": ["舌下络脉迂曲"], "B": ["sublingual", "vein_tortuosity"], "C": ["sublingual_varicosity"]},
        "sublingual_petechiae": {"A": ["舌下络脉瘀点"], "B": ["sublingual", "petechiae"], "C": ["sublingual_petechiae"]},
    },
    VisionDimension.HEAD_FACE: {
        "face_color": {"A": ["面域", "面色"], "B": ["face", "color"], "C": ["face_color"]},
        "face_edema": {"A": ["面域", "面部水肿"], "B": ["face", "edema"], "C": ["face_edema"]},
        "face_luster": {"A": ["面域", "光泽"], "B": ["face", "luster"], "C": ["face_luster"]},
        "lip_color": {"A": ["唇域", "唇色"], "B": ["lips", "color"], "C": ["lip_color"]},
        "lip_moisture": {"A": ["唇域", "唇润燥"], "B": ["lips", "moisture"], "C": ["lip_moisture"]},
        "nose_color": {"A": ["鼻域", "鼻色"], "B": ["nose", "color"], "C": ["nose_color"]},
        "nose_flare": {"A": ["鼻域", "鼻翼煽动"], "B": ["nose", "flaring"], "C": ["nose_flare"]},
        "nose_bleeding": {"A": ["鼻域", "鼻衄"], "B": ["nose", "bleeding"], "C": ["nose_bleeding"]},
    },
    VisionDimension.EYE: {
        "redness": {"A": ["目赤"], "B": ["redness"], "C": ["redness"]},
        "jaundice": {"A": ["巩膜黄染"], "B": ["scleral_jaundice"], "C": ["jaundice"]},
        "edema": {"A": ["眼睑浮肿"], "B": ["eyelid_edema"], "C": ["edema"]},
        "dark_orbit": {"A": ["目眶黯黑"], "B": ["orbital_color"], "C": ["dark_orbit"]},
        "sclera_color": {"A": ["巩膜颜色"], "B": ["sclera_color"], "C": ["sclera_color"]},
        "lower_lid": {"A": ["下睑颜色"], "B": ["lower_lid_color"], "C": ["lower_lid"]},
    },
    VisionDimension.EAR: {
        "color": {"A": ["耳色"], "B": ["color"], "C": ["color"]},
        "helix": {"A": ["耳轮"], "B": ["helix"], "C": ["helix"]},
    },
    VisionDimension.HAND: {
        "palm_color": {"A": ["手掌颜色"], "B": ["palm_color"], "C": ["palm_color"]},
        "palm_temp": {"A": ["手掌温度"], "B": ["palm_temperature"], "C": ["palm_temp"]},
        "nail_color": {"A": ["甲床颜色"], "B": ["nail_bed"], "C": ["nail_color"]},
        "nail_shape": {"A": ["甲床形态"], "B": ["nail_shape"], "C": ["nail_shape"]},
        "ecchymosis": {"A": ["手掌瘀斑"], "B": ["ecchymosis"], "C": ["ecchymosis"]},
    },
    VisionDimension.SKIN: {
        "color": {"A": ["肤色"], "B": ["color"], "C": ["color"]},
        "cuo": {"A": ["甲错"], "B": ["scaly_skin"], "C": ["cuo"]},
        "yellow_sweat": {"A": ["黄汗"], "B": ["yellow_sweat"], "C": ["yellow_sweat"]},
        "edema": {"A": ["水肿"], "B": ["edema"], "C": ["edema"]},
        "dryness": {"A": ["干燥"], "B": ["dryness"], "C": ["dryness"]},
    },
}


_OBSERVE = {
    "tongue.body.color": ("舌面", "舌质颜色"),
    "tongue.body_luster": ("舌面", "舌质润燥"),
    "tongue.body_size": ("舌面", "舌体.胖瘦"),
    "tongue.petechiae": ("舌面", "瘀斑瘀点"),
    "tongue.tooth_marks": ("舌面", "舌体.齿痕"),
    "tongue.fissure": ("舌面", "舌体.裂纹"),
    "tongue.prickles": ("舌面", "舌体.点刺"),
    "tongue.coating.color": ("舌面", "舌苔.颜色"),
    "tongue.coating.thickness": ("舌面", "舌苔.厚薄"),
    "tongue.coating.moisture": ("舌面", "舌苔.润燥"),
    "tongue.coating.greasy": ("舌面", "舌苔.腻腐"),
    "tongue.coating.peeling": ("舌面", "舌苔.剥落"),
    "tongue.coating_amount": ("舌面", "舌苔.苔量"),
    "tongue.coating_distribution": ("舌面", "舌苔.分布"),
    "tongue.sublingual_color": ("舌底", "颜色"),
    "tongue.sublingual_thickness": ("舌底", "粗细"),
    "tongue.sublingual_varicosity": ("舌底", "走行判断"),
    "tongue.sublingual_petechiae": ("舌底", "瘀点"),
    "head_face.face_color": ("头面部", "面色"),
    "head_face.face_edema": ("头面部", "面部浮肿"),
    "head_face.lip_color": ("头面部", "唇色"),
    "head_face.lip_moisture": ("头面部", "唇润燥"),
    "eye.redness": ("眼部", "目赤"),
    "eye.jaundice": ("眼部", "巩膜黄染"),
    "eye.edema": ("眼部", "眼睑浮肿"),
    "eye.sclera_color": ("眼部", "白睛颜色"),
    "eye.lower_lid": ("眼部", "下睑结膜颜色"),
    "ear.color": ("耳部", "耳色"),
    "ear.helix": ("耳部", "润枯"),
    "hand.palm_color": ("手掌", "掌色"),
    "hand.nail_color": ("手掌", "甲床颜色"),
    "hand.nail_shape": ("手掌", "甲床形态"),
    "skin.color": ("皮肤", "肤色"),
    "skin.cuo": ("皮肤", "甲错"),
    "skin.edema": ("皮肤", "水肿"),
    "skin.dryness": ("皮肤", "皮肤干燥程度"),
}

_PROMPT_ALIASES = {
    "tongue.body_size": ("胖瘦",),
    "tongue.tooth_marks": ("齿痕",),
    "tongue.fissure": ("裂纹",),
    "tongue.prickles": ("点刺",),
}

_CAPTURE_PARTS = {"头面": "头面部", "目": "眼部", "耳": "耳部", "手": "手掌"}

_CAPTURE_ONLY = {
    ("舌面", "舌体动态"): "tongue.body_dynamics",
    ("舌面", "舌强语謇"): "tongue.body_dynamics",
    ("头面部", "鼻翼煽动"): "head_face.nose_flare",
    ("皮肤", "黄汗"): "skin.yellow_sweat",
}

_PROMPT_OPTIONS = {
    "tongue.body_luster": ("润泽", "偏干", "干燥", "干裂"),
    "tongue.body_size": ("正常", "适中", "稍胖", "略瘦", "偏胖", "偏瘦", "胖大", "瘦小", "肿胀"),
    "tongue.prickles": ("无", "点刺", "芒刺", "不明显"),
    "tongue.coating.color": ("白", "黄", "灰", "灰黑", "黑"),
    "tongue.coating.thickness": ("薄", "薄白", "薄黄", "略厚", "稍厚", "偏厚", "白厚", "黄厚", "厚腻", "焦黑", "无苔"),
    "tongue.coating.greasy": ("无", "微腻", "稍腻", "偏腻", "腻", "厚腻", "腐苔"),
    "tongue.coating.peeling": ("无", "剥落", "花剥", "地图舌", "镜面", "剥脱"),
    "tongue.coating_amount": ("无苔", "苔少", "适中", "苔多"),
    "tongue.coating_distribution": ("满布", "偏布一侧"),
    "tongue.sublingual_thickness": ("正常", "增粗", "怒张"),
    "head_face.face_color": ("淡白", "苍白", "㿠白", "萎黄", "红赤", "红如妆", "晦暗", "黧黑", "青灰"),
    "head_face.face_edema": ("无", "轻度浮肿", "明显浮肿", "面目鲜泽"),
    "head_face.lip_color": ("淡红", "红润", "淡粉红", "淡白", "暗黄", "红", "紫暗", "青紫"),
    "eye.redness": ("无", "血丝", "赤丝", "红血丝", "红赤", "充血"),
    "eye.jaundice": ("无", "黄染轻度", "黄染明显"),
    "eye.edema": ("无", "微肿", "浮肿", "浮肿明显", "卧蚕"),
    "eye.sclera_color": ("正常", "蓝巩膜", "苍白"),
    "ear.color": ("正常", "红赤", "青黑", "淡红", "淡白"),
    "hand.palm_color": ("淡红", "红润", "淡白", "红", "暗红", "紫暗"),
    "hand.nail_color": ("淡白", "红润", "紫暗", "暗紫"),
    "hand.nail_shape": ("光滑", "粗糙", "甲错"),
    "skin.color": ("正常", "萎黄", "黄如橘皮", "烟熏"),
    "skin.cuo": ("无", "局部", "广泛", "甲错"),
    "skin.edema": ("无", "全身浮肿"),
    "skin.dryness": ("正常", "粗糙", "龟裂"),
}

_TEXTBOOK = "tcm-textbook"
_EXPERIENCE = "experience"


def _refs(keyword: str, locator: str, source_id: str = _TEXTBOOK) -> tuple[SourceRef, ...]:
    if source_id == _TEXTBOOK:
        return (SourceRef(source_id, TEXTBOOK_SHA256, keyword, locator),)
    if source_id == "jingfang":
        return (SourceRef(source_id, JINGFANG_SHA256, keyword, locator),)
    return (SourceRef(_EXPERIENCE, "", keyword, locator),)


class IndicatorRegistry:
    def __init__(self, specs: Iterable[IndicatorSpec]):
        self._specs = tuple(specs)
        self._by_id = {spec.id: spec for spec in self._specs}
        self._by_dim = {}
        for spec in self._specs:
            self._by_dim.setdefault(spec.dimension, {})[spec.key] = spec

    def __len__(self):
        return len(self._specs)

    def __iter__(self):
        return iter(self._specs)

    def __getitem__(self, indicator_id: str) -> IndicatorSpec:
        return self._by_id[indicator_id]

    def for_dimension(self, dim: VisionDimension) -> Dict[str, Dict[str, list[str]]]:
        return {ind: spec.paths for ind, spec in self._by_dim[dim].items()}

    def for_field(self, dim: VisionDimension, key: str) -> IndicatorSpec:
        return self._by_dim[dim][key]

    def for_prompt(self, part: str, key: str) -> IndicatorSpec:
        normalized = key.replace(".", "")
        for spec in self._specs:
            if spec.prompt_part == part and (
                    spec.prompt_key.replace(".", "") == normalized
                    or key in spec.prompt_aliases):
                return spec
        raise KeyError(f"未知识图指标: {part}/{key}")

    def capture_spec(self, part: str, key: str) -> IndicatorSpec | None:
        part = _CAPTURE_PARTS.get(part, part)
        try:
            return self.for_prompt(part, key)
        except KeyError:
            full_id = _CAPTURE_ONLY.get((part, key)) or _CAPTURE_ONLY.get(
                (part, key.replace(".", "")))
            return self._by_id.get(full_id) if full_id else None

    def observe_map(self) -> dict:
        out = {}
        for spec in self._specs:
            if not spec.prompt_part:
                continue
            part = out.setdefault(spec.prompt_part, {})
            part[spec.prompt_key] = spec.paths["B"]
            for alias in spec.prompt_aliases:
                part[alias] = spec.paths["B"]
        return out

    def prompt_options(self, part: str, key: str) -> tuple[str, ...]:
        return self.for_prompt(part, key).prompt_options or ()

    def glossary_for(self, indicator_id: str, term: str, default=None):
        spec = self._by_id[indicator_id]
        return spec.glossary.get(term, default)

    def normalize_observation(self, dim: VisionDimension, obs: dict) -> dict:
        out = dict(obs)
        for spec in self._specs:
            for alias in spec.aliases:
                source = alias["from_indicator"]
                value = out.get(source)
                if value not in alias["values"]:
                    continue
                if spec.dimension == dim:
                    current = out.get(spec.key, "")
                    if not current:
                        out[spec.key] = value
                    elif not isinstance(current, str) or value not in current.split("；"):
                        out[spec.key] = f"{current}；{value}"
                if source in self._by_dim[dim]:
                    out[source] = ""
                else:
                    out.pop(source, None)
        return out


_QUALIFIED_IDS = {
    "body_color": "body.color",
    "coating_color": "coating.color",
    "coating_thickness": "coating.thickness",
    "coating_moisture": "coating.moisture",
    "coating_greasy": "coating.greasy",
    "coating_peeling": "coating.peeling",
}


def _spec(indicator_id: str, **kwargs) -> IndicatorSpec:
    dimension = kwargs.pop("dimension")
    paths = _PATHS[dimension][indicator_id]
    label = INDICATOR_LABELS.get(indicator_id, indicator_id)
    refs = kwargs.pop("source_refs", None) or _refs(indicator_id, "经验/人工签认", _EXPERIENCE)
    return IndicatorSpec(
        id=f"{dimension.english_name}.{_QUALIFIED_IDS.get(indicator_id, indicator_id)}",
        key=indicator_id,
        dimension=dimension,
        paths=paths,
        label=label,
        source_refs=refs,
        **kwargs,
    )


def _build_specs() -> tuple[IndicatorSpec, ...]:
    specs = []
    for dim, indicators in _PATHS.items():
        for indicator_id in indicators:
            full_id = f"{dim.english_name}.{_QUALIFIED_IDS.get(indicator_id, indicator_id)}"
            part_key = _OBSERVE.get(full_id)
            kwargs = {}
            if part_key:
                kwargs.update(prompt_part=part_key[0], prompt_key=part_key[1],
                              prompt_aliases=_PROMPT_ALIASES.get(full_id, ()))
            if indicator_id in REFERENCE_FIELDS:
                kwargs.update(scoring=False, reference_reason=REFERENCE_FIELDS[indicator_id])
            if indicator_id in REVIEW_FIELDS:
                kwargs.update(review=REVIEW_FIELDS[indicator_id])
            specs.append(_spec(indicator_id, dimension=dim, **kwargs))
    return tuple(specs)


def _with(indicator_id: str, **changes) -> None:
    for index, spec in enumerate(_SPECS):
        if spec.id == indicator_id:
            _SPECS[index] = replace(spec, **changes)
            return
    raise KeyError(indicator_id)


_SPECS = list(_build_specs())


def _textbook(indicator_id: str, keyword: str, locator: str,
              source_id: str = _TEXTBOOK, **changes) -> None:
    changes["source_refs"] = _refs(keyword, locator, source_id)
    _with(indicator_id, **changes)


_textbook("tongue.body.color", "舌色", "PDF p99-101", alert_links=("daiyang",))
_textbook("tongue.body_luster", "舌神/润燥", "PDF p99、p108", unknown_semantics="B07 拆分舌神与苔润燥，当前仅参考")
_textbook("tongue.body_size", "胖大舌/瘦薄舌", "PDF p102")
_textbook("tongue.petechiae", "瘀斑/瘀点", "PDF p101")
_textbook("tongue.tooth_marks", "齿痕舌", "PDF p104")
_textbook("tongue.fissure", "裂纹舌", "PDF p104")
_textbook("tongue.prickles", "点刺舌", "PDF p103-104")
_textbook("tongue.body_dynamics", "舌态/舌强语謇", "PDF p105-107、p118-119",
          allowed_methods=("video", "self_report", "manual"), alert_links=("tongue_rigid",))
_textbook("tongue.coating.color", "苔色", "PDF p111-112")
_textbook("tongue.coating.thickness", "薄厚苔", "PDF p107", alert_links=("tongue_critical",))
_textbook("tongue.coating.moisture", "润/滑/燥/糙苔", "PDF p108")
_textbook("tongue.coating.greasy", "腻苔/腐苔/脓腐苔", "PDF p108-109")
_textbook("tongue.coating.peeling", "剥落苔/类剥苔/镜面舌", "PDF p109-110",
          alert_links=("mirror_tongue",))
_textbook("tongue.coating_amount", "苔量/苔之多少", "PDF p110")
_textbook("tongue.coating_distribution", "偏苔/全苔", "PDF p110、p114")
_with("tongue.sublingual_color", source_refs=(
    _refs("舌下络脉颜色", "PDF p113")
    + _refs("淡紫（正常基线）", "现代经验基线；VOCAB_PROVENANCE §一", _EXPERIENCE)))
_textbook("tongue.sublingual_thickness", "舌下络脉粗细", "PDF p113",
          allowed_methods=("measurement", "photo", "manual"),
          unknown_semantics="无比例尺时不得输出绝对毫米结论，记 unknown")
_textbook("tongue.sublingual_varicosity", "舌下络脉曲张", "PDF p113")
_textbook("tongue.sublingual_petechiae", "舌下瘀点", "PDF p101、p113")
_textbook("head_face.face_color", "面色/戴阳/青灰", "PDF p54-58",
          glossary={
              "红赤": "面色红赤（3 分，头面诊）",
              "青灰": "突见面色青灰，需结合口唇青紫、肢凉等排查心阳不振、心脉闭阻",
          },
          alert_links=("daiyang",))
_textbook("head_face.face_edema", "面肿/目胞浮肿", "PDF p69、p71")
_textbook("head_face.face_luster", "色泽/荣枯", "PDF p54-56")
_textbook("head_face.lip_color", "唇色", "PDF p74")
_textbook("head_face.lip_moisture", "唇润燥", "PDF p74")
_textbook("head_face.nose_color", "鼻之色泽", "PDF p73")
_textbook("head_face.nose_flare", "鼻翼扇动/鼻扇", "PDF p73",
          allowed_methods=("video", "self_report", "manual"),
          glossary={
              "明显": "鼻翼扇动明显可见（需动态观察；重病伴喘、额汗时须紧急复核）",
              "煽动": "鼻翼扇动——呼吸时鼻翼一张一缩，需视频或人工动态观察",
          })
_textbook("head_face.nose_bleeding", "鼻衄", "PDF p74")
_textbook("eye.redness", "目赤", "PDF p70-71",
          glossary={"红赤": "白睛整体明显红赤（4 分，目诊）"})
_textbook("eye.jaundice", "白睛发黄/黄疸", "PDF p71", alert_links=("acute_jaundice",),
          aliases=({"from_indicator": "sclera_color",
                    "values": ("黄染", "黄染轻度", "黄染明显"),},))
_textbook("eye.edema", "胞睑肿胀/目下卧蚕", "PDF p71",
          review="卧蚕位置与浮肿程度需肉眼复核",
          aliases=({"from_dimension": VisionDimension.HEAD_FACE,
                    "from_indicator": "face_edema", "values": ("卧蚕",)},))
_textbook("eye.dark_orbit", "目胞色黑/目眶色黑", "PDF p71")
_textbook("eye.sclera_color", "白睛颜色/白睛蓝斑", "PDF p71、p290",
          glossary={"蓝巩膜": "白睛泛蓝，需与白睛蓝斑区分；不直接等同虫积或缺铁"})
_textbook("eye.lower_lid", "下睑淡黄或苍白", "抽取文本 L7228", source_id="jingfang")
_textbook("ear.color", "耳廓颜色", "PDF p72",
          glossary={"红赤": "耳轮红赤（3 分，耳诊）"})
_textbook("ear.helix", "耳廓润枯", "PDF p72-73")
_textbook("hand.palm_color", "掌色（经验项）", "经验/人工签认", source_id=_EXPERIENCE)
_textbook("hand.palm_temp", "掌温/肤冷", "PDF p226-227",
          allowed_methods=("palpation", "inquiry", "manual"))
_with("hand.nail_color", source_refs=(
    _refs("爪甲色淡", "PDF p263-265")
    + _refs("唇甲暗黄或淡白", "抽取文本 L7228", "jingfang")))
_with("hand.nail_shape",
      source_refs=(
          _refs("爪甲不荣/干枯脆薄", "PDF p303")
          + _refs("甲错（历史经验值，无指甲版教材依据）",
                  "docs/VOCAB_PROVENANCE_2026-10-16.md §五", _EXPERIENCE)),
      unknown_semantics="正常/明确否定=normal；粗糙=unknown；甲错沿用历史经验值，非教材指甲判据",
      glossary={"甲错": "旧字段保留；教材「甲错」指肌肤干枯如鱼鳞，不直接等同指甲病变"},
      review="甲床形态词义需人工核对；甲错不是教材指甲判据")
_textbook("hand.ecchymosis", "手掌瘀斑（经验项）", "经验/人工签认", source_id=_EXPERIENCE)
_textbook("skin.color", "皮肤发黄/黄疸", "PDF p56、p58、p88", alert_links=("acute_jaundice",))
_with("skin.cuo", source_refs=(
    _refs("肌肤甲错", "PDF p88")
    + _refs("肌肤甲错", "抽取文本 L3595、L14839、L1669", "jingfang")))
_with("skin.yellow_sweat",
      source_refs=(
          _refs("黄汗", "PDF p150-151")
          + _refs("汗沾衣，色正黄如柏汁", "抽取文本 L4184", "jingfang")),
      allowed_methods=("inquiry", "self_report"))
_textbook("skin.edema", "肌肤水肿/按之凹陷", "PDF p88、p227",
          allowed_methods=("photo", "palpation", "inquiry", "self_report", "manual"))
_textbook("skin.dryness", "皮肤干枯/皲裂", "PDF p88、p227")


INDICATOR_REGISTRY = IndicatorRegistry(_SPECS)
DIMENSION_INDICATORS = {
    dim: INDICATOR_REGISTRY.for_dimension(dim) for dim in VisionDimension
}
