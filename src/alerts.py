"""安全预警：单项筛查、组合规则与未评估状态。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .dimensions import VisionDimension, DIMENSIONS
from .indicators import INDICATOR_REGISTRY, TEXTBOOK_SHA256, JINGFANG_SHA256
from .record import DailyRecord
from .text_analysis import find_term


ALERT_RULESET_VERSION = "2026-10-26.b06.1"

DANGER_FLAGS = {
    "daiyang": {"name": "戴阳证", "sign": "面红如妆 + 手足厥逆（可兼身反不恶寒、掀衣揭被、脉暴出）", "note": "真阳欲脱，严禁解表发汗，立即就医（原著救治方向：通脉四逆加猪胆汤，须医师面诊）"},
    "skin_cold": {"name": "肤冷脉微", "sign": "皮肤触之冰冷 + 脉微", "note": "真阳衰竭，立即就医"},
    "flesh_wasted": {"name": "大肉已脱", "sign": "大肉已脱 + 大骨陷下", "note": "精血枯竭，预后不良，建议就医"},
    "tongue_rigid": {"name": "舌体强硬", "sign": "舌体强直，转动不灵，且语言謇涩", "note": "中风痰瘀阻络（《中医诊断学》p118 第 9 项），难治，立即就医"},
    "tongue_critical": {"name": "舌象危重", "sign": "苔焦黑干燥 + 舌质干裂起刺", "note": "热极津枯（通用诊断学说法），立即就医"},
    "mirror_tongue": {"name": "镜面舌", "sign": "舌深绛无苔而光亮如镜；或舌色白如镜、毫无血色（主营血大亏）", "note": "胃气、胃阴枯涸（《中医诊断学》p118 第 2 项），病重难治，立即就医"},
    "acute_jaundice": {"name": "急性黄疸", "sign": "巩膜黄染 + 皮肤黄如橘皮（或明确黄疸语境）", "note": "黄疸相关复核提示；急重症需结合病程及全身情况，立即线下评估"},
    "wind_stroke": {"name": "中风重症", "sign": "口不能言 + 身体不收", "note": "中风重症（风痱），立即就医"},
    "throat_erosion": {"name": "狐惑重症", "sign": "默默欲眠、恶闻食臭、面目乍赤乍黑乍白、蚀喉声嗄", "note": "狐惑（厥阴本病，原著有甘草泻心汤方向），建议尽快就医"},
    "yangming_critical": {"name": "阳明危重", "sign": "神昏谵语、循衣摸床、微喘直视", "note": "阳明病危重证（212条），紧急就医"},
    "collapse_yang": {"name": "脱阳前兆", "sign": "神识昏昧 + 冷汗如油", "note": "真阳外脱前兆，紧急就医"},
    "pigkidney_tongue": {"name": "猪腰舌", "sign": "舌面无苔，如去膜的猪腰", "note": "胃气将绝，主病危，立即就医"},
    "sandy_tongue": {"name": "砂皮舌", "sign": "舌粗糙有刺，如沙鱼皮，或干燥枯裂", "note": "津液枯竭，病危，立即就医"},
    "litchi_tongue": {"name": "干荔舌", "sign": "舌敛束而无津，形如干荔肉", "note": "热极津枯，病危，立即就医"},
    "persimmon_tongue": {"name": "火柿舌", "sign": "舌如火柿色，或色紫而干晦如猪肝色", "note": "内脏败坏，病危，立即就医"},
    "ochre_tongue": {"name": "赭黑舌", "sign": "舌质色赭带黑", "note": "肾阴将绝，病危，立即就医"},
    "thin_coatless": {"name": "瘦薄无苔舌", "sign": "舌体瘦小薄嫩，光而无苔", "note": "胃气将绝，难治，立即就医"},
    "retracted_tongue": {"name": "囊缩卷舌", "sign": "舌体卷缩，兼阴囊缩入", "note": "厥阴气绝，难治，立即就医（阴囊症状以自陈为准，不采集照片）"},
    "blue_tongue": {"name": "蓝舌", "sign": "舌质由淡紫转蓝，苔由淡灰转黑或白如霉点", "note": "病危重，难治，立即就医"},
}

DANGER_PATTERNS = {
    "daiyang": ("面红如妆", "红如妆"),
    "tongue_rigid": "强硬",
    "tongue_critical": "焦黑",
    "mirror_tongue": ("镜面", "光剥无苔", "光亮如镜"),
    "acute_jaundice": ("黄如橘皮", "黄染"),
    "flesh_wasted": "大肉已脱",
    "wind_stroke": "口不能言",
    "skin_cold": "触之冰冷",
    "throat_erosion": "狐惑",
    "yangming_critical": "直视",
    "collapse_yang": ("冷汗", "绝汗"),
    "pigkidney_tongue": "猪腰",
    "sandy_tongue": "砂皮",
    "litchi_tongue": "干荔",
    "persimmon_tongue": "火柿",
    "ochre_tongue": "赭黑",
    "thin_coatless": "瘦薄无苔",
    "retracted_tongue": "囊缩",
    "blue_tongue": "蓝舌",
}


def _ref(source_id: str, keyword: str, locator: str, quote: str) -> dict:
    digest = {"tcm-textbook": TEXTBOOK_SHA256,
              "jingfang": JINGFANG_SHA256}.get(source_id, "")
    return {"source_id": source_id, "source_sha256": digest,
            "keyword": keyword, "locator": locator, "quote": quote}


DANGER_PROVENANCE = {
    "daiyang": (_ref("jingfang", "面红如妆/手足厥逆", "抽取文本 L8333、L8833",
                     "可见面红如妆；手足厥逆或四肢拘急"),),
    "skin_cold": (_ref("jingfang", "身冷不温/脉微欲绝", "抽取文本 L8329、L4216",
                       "身冷不温；脉微欲绝"),),
    "flesh_wasted": (_ref("jingfang", "大肉已脱/大骨陷下", "抽取文本 L3603",
                          "大肉已脱…大骨陷下"),),
    "tongue_rigid": (_ref("tcm-textbook", "舌强语謇", "PDF p118",
                          "舌体强直，转动不灵，且语言謇涩"),),
    "tongue_critical": (_ref("tcm-textbook", "苔焦黑干燥/舌质干裂起刺", "PDF p112",
                             "苔焦黑干燥，舌质干裂起刺"),),
    "mirror_tongue": (_ref("tcm-textbook", "镜面舌/光亮如镜", "PDF p118",
                           "舌深绛无苔而光亮如镜；或舌色白如镜、毫无血色"),),
    "acute_jaundice": (_ref("tcm-textbook", "白睛发黄/黄如橘皮", "PDF p56、p58、p71、p88",
                            "白睛发黄为黄疸的主要标志；黄而鲜明如橘皮"),),
    "wind_stroke": (_ref("jingfang", "身体不能自收持/口不能言", "抽取文本 L2285",
                         "身体不能自收持，口不能言"),),
    "throat_erosion": (_ref("jingfang", "默默欲眠/恶闻食臭/面目乍赤乍黑乍白", "抽取文本 L4236",
                            "默默欲眠；恶闻食臭；面目乍赤、乍黑、乍白"),),
    "yangming_critical": (_ref("jingfang", "不识人/循衣摸床/微喘直视", "抽取文本 L2822-2826",
                               "不识人，循衣摸床…微喘直视"),),
    "collapse_yang": (_ref("jingfang", "神识昏昧/冷汗如油", "抽取文本 L8329",
                           "神识昏昧…冷汗如油"),),
    "pigkidney_tongue": (_ref("tcm-textbook", "猪腰舌", "PDF p117", "舌面无苔，如去膜的猪腰"),),
    "sandy_tongue": (_ref("tcm-textbook", "砂皮舌", "PDF p117", "舌粗糙有刺，如沙鱼皮"),),
    "litchi_tongue": (_ref("tcm-textbook", "干荔舌", "PDF p117", "舌敛束而无津，形如干荔肉"),),
    "persimmon_tongue": (_ref("tcm-textbook", "火柿舌", "PDF p117", "舌如火柿色"),),
    "ochre_tongue": (_ref("tcm-textbook", "赭黑舌", "PDF p117", "舌质色赭带黑"),),
    "thin_coatless": (_ref("tcm-textbook", "瘦薄无苔舌", "PDF p117", "舌体瘦小薄嫩，光而无苔"),),
    "retracted_tongue": (_ref("tcm-textbook", "囊缩卷舌", "PDF p117", "舌体卷缩，兼阴囊缩入"),),
    "blue_tongue": (_ref("tcm-textbook", "蓝舌", "PDF p117", "舌质由淡紫转蓝"),),
}


@dataclass(frozen=True)
class Evidence:
    clause_id: str
    label: str
    source: str
    text: str
    state: str
    reason: str = ""

    def to_dict(self) -> dict:
        return {"clause_id": self.clause_id, "label": self.label,
                "source": self.source, "text": self.text,
                "state": self.state, "reason": self.reason}


@dataclass(frozen=True)
class AlertEvaluation:
    rule_id: str
    kind: str
    state: str
    matched_clauses: tuple[str, ...] = ()
    missing_clauses: tuple[str, ...] = ()
    evidence: tuple[Evidence, ...] = ()
    provenance: tuple[dict, ...] = ()

    def to_dict(self) -> dict:
        return {"rule_id": self.rule_id, "kind": self.kind, "state": self.state,
                "matched_clauses": list(self.matched_clauses),
                "missing_clauses": list(self.missing_clauses),
                "evidence": [e.to_dict() for e in self.evidence],
                "provenance": [dict(ref) for ref in self.provenance]}


@dataclass(frozen=True)
class AlertClause:
    id: str
    label: str
    paths: tuple[str, ...]
    terms: tuple[str, ...]
    negative_terms: tuple[str, ...] = ()


@dataclass(frozen=True)
class AlertRule:
    required: tuple[AlertClause, ...] = ()
    any_of: tuple[AlertClause, ...] = ()
    critical_paths: tuple[str, ...] = ()
    scope: str = ""


@dataclass(frozen=True)
class _Source:
    path: str
    text: str
    structured: bool


@dataclass(frozen=True)
class _ClauseResult:
    clause: AlertClause
    state: str
    evidence: Evidence


def _leaf_texts(obj) -> Iterable[str]:
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key in ("_notes", "_type_errors"):
                continue
            yield from _leaf_texts(value)
    elif isinstance(obj, (list, tuple)):
        for value in obj:
            yield from _leaf_texts(value)
    elif obj is not None:
        text = str(obj).strip()
        if text:
            yield text


def _dig(obj, parts) -> object:
    current = obj
    for part in parts:
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _clause(clause_id: str, label: str, paths: Iterable[str],
            terms: Iterable[str], negative: Iterable[str] = ()) -> AlertClause:
    return AlertClause(clause_id, label, tuple(paths), tuple(terms), tuple(negative))


def _looks_like_record(raw: dict) -> bool:
    if any(key in raw for key in ("observations", "vision_analysis", "doubao_vision_analysis")):
        return True
    for dim in DIMENSIONS:
        node = raw.get(dim.english_name)
        if isinstance(node, dict) and any(
                key in INDICATOR_REGISTRY.for_dimension(dim) for key in node):
            return True
    return False


class _Input:
    def __init__(self, observations):
        self.obs = observations
        self.record = observations if isinstance(observations, DailyRecord) else None
        if self.record is None and isinstance(observations, dict) and _looks_like_record(observations):
            self.record = DailyRecord(observations)
        self.raw = self.record.raw if self.record else (
            observations if isinstance(observations, dict) else {})

    def _dimension_root(self, dim: str):
        if self.record:
            node = _dig(self.raw.get("observations", {}), [dim])
            if node is None:
                node = self.raw.get(dim)
            return node if node is not None else self.record.get_observation(VisionDimension(dim))
        root = self.raw.get("observations", self.raw)
        return root.get(dim, {}) if isinstance(root, dict) else {}

    def _path_values(self, path: str) -> list[_Source]:
        parts = path.split(".")
        first = parts[0]
        if first == "inquiry":
            value = _dig(self.raw.get("inquiry", {}), parts[1:])
            if isinstance(value, dict):
                if value.get("asked") is False:
                    value = ""
                else:
                    value = value.get("answer", "")
            return [_Source(path, text, True) for text in _leaf_texts(value)] or [_Source(path, "", True)]
        if first == "context":
            value = _dig(self.raw.get("context", {}), parts[1:])
            return [_Source(path, text, True) for text in _leaf_texts(value)] or [_Source(path, "", True)]

        candidates = [parts]
        if self.record and first in {d.english_name for d in DIMENSIONS}:
            dim = VisionDimension(first)
            paths = INDICATOR_REGISTRY.for_dimension(dim)
            local = parts[1] if len(parts) == 2 and parts[1] in paths else None
            if local is None:
                local = next((key for key, shapes in paths.items()
                              if shapes["B"] == parts[1:]), None)
            if local:
                value = self.record.get_observation(dim).get(local, "")
                if value:
                    return [_Source(path, value, True)]
            if local and len(parts) == 2:
                candidates.append([first, *paths[local]["B"]])
        elif first in {d.english_name for d in DIMENSIONS}:
            paths = INDICATOR_REGISTRY.for_dimension(VisionDimension(first))
            if len(parts) == 2 and parts[1] in paths:
                candidates.append([first, *paths[parts[1]]["B"]])

        values = []
        for candidate in candidates:
            root = self.raw.get("observations", self.raw)
            value = _dig(root, candidate)
            values.extend(_Source(path, text, True) for text in _leaf_texts(value))
        unique = list(dict.fromkeys(values))
        return unique or [_Source(path, "", True)]

    def free_texts(self, scope: str = "") -> list[_Source]:
        if not self.raw:
            root = self.obs
        elif scope:
            root = self._dimension_root(scope)
        elif self.record:
            root = {dim.english_name: self._dimension_root(dim.english_name)
                    for dim in DIMENSIONS}
            root["inquiry"] = self.raw.get("inquiry", {})
            root["context"] = self.raw.get("context", {})
        elif "observations" in self.raw:
            root = {"observations": self.raw["observations"],
                    "inquiry": self.raw.get("inquiry", {}),
                    "context": self.raw.get("context", {})}
        else:
            excluded = {"danger_flags", "diagnosis", "deepseek_diagnosis",
                        "pattern_differentiation", "pattern_update", "formula",
                        "formula_adjust", "formula_with_dosage", "report",
                        "local_report", "llm_report", "derived_meta"}
            root = {key: value for key, value in self.raw.items()
                    if key not in excluded}
        return [_Source(f"text:{scope or 'record'}", text, False)
                for text in _leaf_texts(root)]


def _evidence(clause: AlertClause, source: _Source, state: str, reason: str = "") -> Evidence:
    return Evidence(clause.id, clause.label, source.path, source.text[:160], state, reason)


def _evaluate_clause(data: _Input, clause: AlertClause) -> _ClauseResult:
    sources = []
    for path in clause.paths:
        sources.extend(data._path_values(path))
    scope = clause.paths[0].split(".", 1)[0] if clause.paths else ""
    if scope not in {dim.english_name for dim in DIMENSIONS}:
        scope = ""
    if not any(path.endswith("critical_signs") for path in clause.paths):
        sources.extend(data.free_texts(scope))
    structured_text = any(s.structured and s.text.strip() for s in sources)
    positives = []
    negatives = []
    unknown = []
    for source in sources:
        if source.structured and source.text.strip() in clause.negative_terms:
            negatives.append(_evidence(clause, source, "not_triggered", "明确正常/阴性值"))
            continue
        found = False
        for term in clause.terms:
            match = find_term(source.text, term)
            if match.state == "matched":
                found = True
                positives.append((source, _evidence(clause, source, "matched")))
                break
            if match.state != "missing":
                found = True
            if match.state in ("negated", "excluded"):
                negatives.append(_evidence(clause, source, "not_triggered", match.reason))
        if source.text.strip() and not found and (source.structured or not structured_text):
            unknown.append(_evidence(clause, source, "unknown", "非空但未识别/未评估"))
    if positives:
        best = next((e for source, e in positives if source.structured), positives[0][1])
        return _ClauseResult(clause, "matched", best)
    if unknown:
        return _ClauseResult(clause, "unknown", unknown[0])
    if negatives:
        return _ClauseResult(clause, "not_triggered", negatives[0])
    source = sources[0] if sources else _Source(clause.paths[0] if clause.paths else "text", "", True)
    return _ClauseResult(clause, "unknown", _evidence(clause, source, "unknown", "未采集"))


def _patterns(rule_id: str) -> tuple[str, ...]:
    patterns = DANGER_PATTERNS[rule_id]
    return patterns if isinstance(patterns, tuple) else (patterns,)


def _screening_evidence(data: _Input, rule_id: str, scope: str) -> Evidence | None:
    for source in data.free_texts(scope):
        for pattern in _patterns(rule_id):
            if find_term(source.text, pattern).state == "matched":
                return Evidence(f"{rule_id}.screening", f"单项线索：{pattern}",
                                source.path, source.text[:160], "matched")
    return None


ALERT_RULES = {rule_id: AlertRule() for rule_id in DANGER_FLAGS}
ALERT_RULES["daiyang"] = AlertRule(required=(
    _clause("face.red_makeup", "面红如妆", ("head_face.face_color",),
            ("面红如妆", "红如妆"), ("淡红", "正常", "未见异常", "无")),
    _clause("limb.cold", "手足厥逆", ("hand.palm_temp", "inquiry.手足温凉"),
            ("手足厥逆", "手足厥冷", "四肢厥冷", "厥逆", "厥冷"),
            ("温", "偏凉", "凉", "正常", "未见异常", "无")),
))
ALERT_RULES["acute_jaundice"] = AlertRule(
    required=(_clause("eye.jaundice", "巩膜黄染", ("eye.jaundice",),
                      ("黄染",), ("无", "正常", "未见异常", "无黄染")),),
    any_of=(
        _clause("skin.orange_yellow", "皮肤黄如橘皮", ("skin.color",),
                ("黄如橘皮", "橘皮"), ("正常", "无", "未见异常", "黄如烟熏", "烟熏", "萎黄")),
        _clause("context.jaundice", "黄疸语境",
                ("context.主诉", "context.病程", "inquiry.主诉"),
                ("急性黄疸", "黄疸"), ("无", "正常", "未见异常", "无黄疸")),
    ),
)
ALERT_RULES["mirror_tongue"] = AlertRule(
    any_of=(
        _clause("tongue.mirror", "镜面舌形态", ("tongue.coating_peeling",),
                ("镜面", "光剥无苔", "光亮如镜"),
                ("无", "剥落", "花剥", "地图舌", "剥脱", "局部剥落", "局部无苔")),
        _clause("tongue.critical_mirror", "危重舌象：镜面舌",
                ("tongue.critical_signs",), ("镜面舌", "镜面")),
    ),
    critical_paths=("tongue.coating_peeling", "tongue.critical_signs"),
)
ALERT_RULES["skin_cold"] = AlertRule(required=(
    _clause("skin.cold", "皮肤触之冰冷", ("inquiry.手足温凉", "hand.palm_temp"),
            ("触之冰冷", "肤冷", "冰冷", "厥冷"), ("温", "偏凉", "凉", "正常", "无")),
    _clause("pulse.faint", "脉微", ("context.脉诊", "inquiry.脉诊"),
            ("脉微欲绝", "脉微"), ("脉洪大", "正常", "无")),
))
ALERT_RULES["flesh_wasted"] = AlertRule(required=(
    _clause("flesh.wasted", "大肉已脱", ("skin.appearance", "context.望诊"),
            ("大肉已脱",), ("无", "正常", "未见异常")),
    _clause("bone.collapsed", "大骨陷下", ("skin.appearance", "context.望诊"),
            ("大骨陷下",), ("无", "正常", "未见异常")),
))
ALERT_RULES["tongue_rigid"] = AlertRule(required=(
    _clause("tongue.rigid", "舌体强直", ("tongue.body_dynamics", "tongue.critical_signs"),
            ("舌强语謇", "舌强", "强硬"), ("正常", "无", "痿软")),
    _clause("speech.rigid", "语言謇涩", ("tongue.critical_signs", "inquiry.语言"),
            ("舌强语謇", "语言謇涩", "语謇", "不能语"), ("正常", "无", "语言流利")),
))
ALERT_RULES["tongue_critical"] = AlertRule(required=(
    _clause("coating.charred", "苔焦黑干燥", ("tongue.coating_thickness",),
            ("焦黑",), ("薄", "薄白", "正常", "无")),
    _clause("tongue.dry_cracks", "舌质干裂起刺", ("tongue.body_luster", "tongue.prickles"),
            ("干裂起刺", "干裂", "起刺"), ("润泽", "正常", "无")),
))
ALERT_RULES["wind_stroke"] = AlertRule(required=(
    _clause("speech.lost", "口不能言", ("inquiry.语言", "inquiry.主诉"),
            ("口不能言", "不能言"), ("语言流利", "正常", "无")),
    _clause("body.uncollected", "身体不收", ("inquiry.运动", "context.望诊"),
            ("身体不能自收持", "身体不收", "不收"), ("活动自如", "正常", "无")),
))
ALERT_RULES["throat_erosion"] = AlertRule(required=(
    _clause("throat.sleep", "默默欲眠", ("inquiry.睡眠", "inquiry.主诉"),
            ("默默欲眠",), ("正常", "无", "失眠")),
    _clause("throat.appetite", "恶闻食臭", ("inquiry.食欲", "inquiry.主诉"),
            ("恶闻食臭",), ("正常", "无", "纳可")),
    _clause("throat.face", "面目乍赤乍黑乍白", ("head_face.face_color", "inquiry.主诉"),
            ("面目乍赤乍黑乍白", "乍赤、乍黑、乍白"), ("正常", "无", "未见异常")),
    _clause("throat.voice", "蚀喉声嗄", ("inquiry.主诉", "context.望诊"),
            ("蚀喉声嗄", "声嗄", "声喝"), ("正常", "无", "声音正常")),
))
ALERT_RULES["yangming_critical"] = AlertRule(required=(
    _clause("yangming.mind", "神昏谵语", ("inquiry.主诉", "context.神志"),
            ("神昏谵语", "不识人", "谵语"), ("神志清楚", "正常", "无")),
    _clause("yangming.movement", "循衣摸床", ("inquiry.主诉", "context.望诊"),
            ("循衣摸床",), ("正常", "无")),
    _clause("yangming.gaze", "微喘直视", ("inquiry.呼吸", "inquiry.主诉"),
            ("微喘直视", "直视"), ("正常", "无")),
))
ALERT_RULES["collapse_yang"] = AlertRule(required=(
    _clause("collapse.mind", "神识昏昧", ("inquiry.主诉", "context.神志"),
            ("神识昏昧", "神昏昧", "神昏", "昏昧"), ("神志清楚", "正常", "无")),
    _clause("collapse.sweat", "冷汗如油",
            ("inquiry.汗出时间特征", "inquiry.汗出时间特征？", "skin.sweat"),
            ("冷汗", "绝汗", "大汗淋漓如油"), ("无汗", "无", "正常", "未见异常", "无异常")),
))
for _rule_id, _name, _short in [
    ("pigkidney_tongue", "猪腰舌", "猪腰"),
    ("sandy_tongue", "砂皮舌", "砂皮"),
    ("litchi_tongue", "干荔舌", "干荔"),
    ("persimmon_tongue", "火柿舌", "火柿"),
    ("ochre_tongue", "赭黑舌", "赭黑"),
    ("thin_coatless", "瘦薄无苔舌", "瘦薄无苔"),
    ("retracted_tongue", "囊缩卷舌", "囊缩"),
    ("blue_tongue", "蓝舌", "蓝舌"),
]:
    ALERT_RULES[_rule_id] = AlertRule(
        any_of=(_clause(f"tongue.{_rule_id}", _name,
                        ("tongue.critical_signs",), (_name, _short)),),
        critical_paths=("tongue.critical_signs",),
        scope="" if _rule_id == "retracted_tongue" else "tongue",
    )
del _rule_id, _name, _short


def evaluate_alert(rule_id: str, observations) -> AlertEvaluation:
    if rule_id not in ALERT_RULES:
        raise KeyError(f"未知预警规则: {rule_id}")
    rule = ALERT_RULES[rule_id]
    data = _Input(observations)
    required = [_evaluate_clause(data, clause) for clause in rule.required]
    alternatives = [_evaluate_clause(data, clause) for clause in rule.any_of]
    results = required + alternatives
    matched = [r for r in results if r.state == "matched"]
    preferred = [r for r in alternatives
                 if r.state == "matched" and r.evidence.source in rule.critical_paths]
    if preferred:
        matched = [r for r in matched if r in required or r in preferred]
    screening = _screening_evidence(data, rule_id, rule.scope)
    complete = bool(results) and all(r.state == "matched" for r in required) and (
        not alternatives or any(r.state == "matched" for r in alternatives))
    if complete and (not rule.critical_paths or all(
            r.evidence.source in rule.critical_paths for r in matched)):
        return AlertEvaluation(
            rule_id, "critical_rule", "triggered",
            tuple(r.clause.label for r in matched), (),
            tuple(r.evidence for r in matched), DANGER_PROVENANCE.get(rule_id, ()))
    if screening:
        matched_labels = [r.clause.label for r in matched]
        evidence = [r.evidence for r in matched]
        if not matched:
            matched_labels.append(screening.label)
            evidence.append(screening)
        return AlertEvaluation(
            rule_id, "screening", "triggered", tuple(matched_labels),
            tuple(r.clause.label for r in results if r.state == "unknown"),
            tuple(evidence), DANGER_PROVENANCE.get(rule_id, ()))
    if any(r.state == "not_triggered" for r in required):
        state = "not_triggered"
    elif any(r.state == "unknown" for r in required):
        state = "unknown"
    elif alternatives and all(r.state == "not_triggered" for r in alternatives):
        state = "not_triggered"
    elif any(r.state == "unknown" for r in alternatives):
        state = "unknown"
    else:
        state = "unknown" if not results else "not_triggered"
    return AlertEvaluation(
        rule_id, "critical_rule", state,
        tuple(r.clause.label for r in matched),
        tuple(r.clause.label for r in results if r.state == "unknown")
        if state == "unknown" else (),
        tuple(r.evidence for r in results), DANGER_PROVENANCE.get(rule_id, ()))


def evaluate_alerts(observations, rule_ids=None) -> dict[str, AlertEvaluation]:
    return {rule_id: evaluate_alert(rule_id, observations)
            for rule_id in (rule_ids or DANGER_FLAGS)}


def danger_flags_for(observations, previous: dict | None = None) -> dict:
    evaluations = evaluate_alerts(observations)
    detected = [rule_id for rule_id, result in evaluations.items()
                if result.state == "triggered"]
    previous = previous if isinstance(previous, dict) else {}
    prior = previous.get("triggered", [])
    if not isinstance(prior, list):
        prior = []
    triggered = sorted(set(prior) | set(detected))
    return {
        "triggered": triggered,
        "not_triggered": [rule_id for rule_id, result in evaluations.items()
                          if result.state == "not_triggered" and rule_id not in triggered],
        "unknown": [rule_id for rule_id, result in evaluations.items()
                    if result.state == "unknown" and rule_id not in triggered],
        "evaluations": [result.to_dict() for result in evaluations.values()],
        "ruleset_version": ALERT_RULESET_VERSION,
    }


def alert_evaluation_map(observations) -> dict[str, dict]:
    raw = observations.raw if isinstance(observations, DailyRecord) else observations
    flags = raw.get("danger_flags", {}) if isinstance(raw, dict) else {}
    stored = flags.get("evaluations") if isinstance(flags, dict) else None
    if (isinstance(stored, list)
            and flags.get("ruleset_version") == ALERT_RULESET_VERSION):
        return {item["rule_id"]: item for item in stored
                if isinstance(item, dict) and isinstance(item.get("rule_id"), str)}
    return {rule_id: result.to_dict()
            for rule_id, result in evaluate_alerts(observations).items()}
