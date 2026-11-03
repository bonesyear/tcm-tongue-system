"""拍照向导存取层：七部位拍摄 → vision 识图 → 形状 B 记录组装。

草稿存 records/daily/.wizard-<date>.json（以点开头，不参与选档 glob
的 YYYY-MM-DD 前缀匹配；records/daily/* 已被 gitignore）。
"""
from __future__ import annotations

import datetime
import json
import os
import re
import sys

import time_utils
from src import paths
from src.confidence import from_coverage
from src.dimensions import DIMENSIONS, from_chinese
from src.record import DailyRecord, DECLARED_NORMAL_MARK, INQUIRY_TOTAL
from src.observations import (
    Declaration, Observation, SCHEMA_VERSION,
    capture_observation, split_coating_text,
)
from io_utils import VERSION_NOT_PROVIDED

# 七部位（顺序即向导步骤）；prompt_key 对齐 scripts/vision_client.py PROMPTS
PARTS = [
    {"part": "舌面", "prompt_key": "舌面",   "dim": "舌诊",
     "guide_anchor": "part-tongue-surface", "guide_label": "舌面照",
     "tips": ["自然光下拍摄，避开有色光源", "伸舌自然放松，勿用力前伸", "禁用闪光灯", "舌强语謇需视频或人工动态/问诊，静态照片不判"]},
    {"part": "舌底", "prompt_key": "舌底",   "dim": "舌诊",
     "guide_anchor": "part-tongue-bottom", "guide_label": "舌底照",
     "tips": ["舌尖轻触上颚（上门牙后方），充分暴露舌下", "⚠️ 严禁闪光灯（会加剧过度判读）", "对焦舌下两侧络脉", "无可靠比例尺时不报毫米值或毫米阈值"]},
    {"part": "头面", "prompt_key": "头面部", "dim": "头面诊",
     "guide_anchor": "part-face", "guide_label": "头面部照",
     "tips": ["正面素颜，免冠", "面向自然光源，避免逆光", "包含完整面部与唇周", "鼻翼煽动需视频或人工动态观察，静态照片不判"]},
    {"part": "目",   "prompt_key": "眼部",   "dim": "目诊",
     "guide_anchor": "part-eyes", "guide_label": "目部照",
     "tips": ["睁眼平视镜头", "白睛清晰可见", "分别拍摄双眼", "轻拉下睑暴露结膜；未暴露则下睑颜色留空"]},
    {"part": "耳",   "prompt_key": "耳部",   "dim": "耳诊",
     "guide_anchor": "part-ear", "guide_label": "耳部照",
     "tips": ["侧对光源", "一侧耳朵完整入镜", "耳轮形态清晰"]},
    {"part": "手",   "prompt_key": "手掌",   "dim": "手诊",
     "guide_anchor": "part-hands", "guide_label": "手掌照",
     "tips": ["掌心向上自然摊开", "五指微分，甲床清晰", "禁用闪光灯"]},
    {"part": "皮肤", "prompt_key": "皮肤",   "dim": "皮肤诊",
     "guide_anchor": "part-skin", "guide_label": "皮肤照",
     "tips": ["前臂或小腿伸侧", "自然光下拍摄", "如有甲错部位请特写", "凹陷须人工触诊/自陈；黄汗须问诊或衣物证据"]},
]
# 向导问诊步：16 项骨架 + 第 0 项手足温凉，共 17 项。
# 绝汗直接支撑 collapse_yang 红线；手足温凉用于三阴三阳快速鉴别。
# 第 0 项「手足温凉」是原著三阴三阳最快捷鉴别（L6143），照片判不了，必答推荐；
# 其余 16 项为模板既定问诊骨架（全部可跳过）。
INQUIRY_SPEC = {
    "key": "手足温凉",
    "title": "手足温度如何？（问诊 · 必答推荐）",
    "hint": "手足厥冷=病在阴（太阴/少阴/厥阴）；手足温+渴=少阳；手足自温不排除太阴。原著三阴三阳最快捷鉴别。",
    "options": ["温", "偏凉", "凉", "厥冷（冰冷）"],
}

# 16 项问诊骨架（问题文本与 templates/adaptive_analysis_prompt.md §2.1.2 逐字一致，
# 保证报告输入符合模板证据矩阵契约；第 16 项汗出时间特征出自
# 《中医诊断学》p149 特殊汗出，非经方骨架）
INQUIRY_ITEMS = [
    {"q": "恶寒or恶热？", "options": ["恶寒", "恶热", "往来寒热", "都不明显"]},
    {"q": "有汗or无汗？", "options": ["有汗", "无汗", "没有外感不适"]},
    {"q": "头痛or身痛？", "options": ["无", "头痛", "身痛", "头项强痛"]},
    {"q": "口苦？", "options": ["无", "晨起口苦", "全天口苦"]},
    {"q": "咽干？", "options": ["无", "轻微", "明显", "咽干欲饮"]},
    {"q": "目眩？", "options": ["无", "头晕", "目眩(天旋地转)"]},
    {"q": "口渴？", "options": ["口不渴", "口渴欲饮", "渴不欲饮", "口燥但欲漱水不欲咽"]},
    {"q": "食欲？", "options": ["正常", "纳呆不食", "饥不欲食", "消谷善饥"]},
    {"q": "大便？", "options": ["正常", "便溏", "便硬", "便燥", "下利"]},
    {"q": "小便？", "options": ["正常", "小便清长", "小便黄赤", "小便白", "小便不利"]},
    {"q": "睡眠？", "options": ["正常", "失眠烦躁", "嗜睡多寐"]},
    {"q": "胸胁？", "options": ["无不适", "胸胁苦满", "胸闷"]},
    {"q": "腹部？", "options": ["无不适", "腹满", "腹痛", "心下痞"]},
    {"q": "听力？", "options": ["正常", "耳鸣", "听力下降", "耳无所闻"]},
    {"q": "鼻部？", "options": ["正常", "鼻塞", "鼻鸣", "鼻衄"]},
    # 2026-10-16 教材复查 P2：绝汗（脱汗）直接支撑 collapse_yang 红线，
    # 自汗/盗汗为阴阳鉴别常规项（《中医诊断学》p149 特殊汗出）
    {"q": "汗出时间特征？", "options": ["无异常", "自汗(白天易汗出)",
                                      "盗汗(睡中汗出)", "绝汗(大汗淋漓如油)"]},
]

# 问诊总题数由 src.record 统一持有，供 Record、向导与报告共用。

CONTEXT_SPEC = [
    {"key": "age_band", "label": "年龄段", "options": ["未成年", "成年", "老年", "不便提供"]},
    {"key": "chief_complaint", "label": "主诉（不适或想复核的问题）"},
    {"key": "duration", "label": "病程（如 3 天、2 周）"},
    {"key": "recent_dyes", "label": "近期染苔因素（食物/药物/烟酒等）"},
    {"key": "medications", "label": "当前用药"},
    {"key": "sweating_medication", "label": "发汗药或影响汗出的药物"},
    {"key": "history_allergies", "label": "相关既往史与过敏史"},
    {"key": "sleep", "label": "近期睡眠"},
    {"key": "congenital_signs", "label": "先天或长期存在的体征"},
]

PART_BY_NAME = {p["part"]: p for p in PARTS}

# 识图输出（中文键，可嵌套）→ 形状 B 英文路径。
# 未收录的键不丢弃：进 <dim>._raw 保留并在 UI 告警（不静默丢数据）。
from src.indicators import INDICATOR_REGISTRY

OBSERVE_MAP = INDICATOR_REGISTRY.observe_map()
OBSERVE_MAP["舌面"]["危重舌象"] = ["critical_signs"]  # 非指标的安全复核出口

# 「未拍摄（用户声明正常）」占位：写到该维度第一个指标路径（validator 对该
# 措辞有豁免，见 input_validator 词表覆盖检查注释；KNOWN_ISSUES #10 定策）
DECLARED_NORMAL_PLACEHOLDER = DECLARED_NORMAL_MARK  # 别名（单一事实来源）


def draft_path(daily_dir: str, date_str: str) -> str:
    return os.path.join(daily_dir, f".wizard-{date_str}.json")


def load_draft_with_version(daily_dir: str, date_str: str):
    p = draft_path(daily_dir, date_str)
    try:
        from io_utils import read_versioned_json
        raw, version = read_versioned_json(p)
        if not isinstance(raw, dict):
            raise ValueError("草稿根节点不是对象")
        if not isinstance(raw.get("parts", {}), dict) or any(
                not isinstance(value, dict) for value in raw.get("parts", {}).values()):
            raise ValueError("草稿 parts 结构异常")
        for key in ("inquiry", "context"):
            if key in raw and not isinstance(raw[key], dict):
                raise ValueError(f"草稿 {key} 不是对象")
        if raw.get("date") != date_str:
            print(f"⚠️ 警告: 草稿 {p} 的日期与文件名不一致，按文件名读取",
                  file=sys.stderr)
            raw = dict(raw, date=date_str)
        raw.setdefault("parts", {})
        return raw, version
    except FileNotFoundError:
        return {"date": date_str, "parts": {}}, None
    except (OSError, ValueError, TypeError) as e:
        # 草稿损坏不可静默重置（AGENTS.md §0：失败要可诊断）——
        # 告警并备份损坏文件，再返回空白草稿
        import uuid
        quarantine = (p + "." + datetime.datetime.now(datetime.timezone.utc).strftime(
            "%Y%m%dT%H%M%S-%fZ") + f".{uuid.uuid4().hex[:12]}.corrupt")
        print(f"⚠️ 警告: 向导草稿 {p} 读取失败（{e}），已重置为空白草稿；"
              f"原文件保留为 {quarantine}", file=sys.stderr)
        try:
            os.replace(p, quarantine)
        except OSError as backup_error:
            print(f"⚠️ 警告: 损坏草稿隔离备份失败: {backup_error}", file=sys.stderr)
        return {"date": date_str, "parts": {}}, None


def load_draft(daily_dir: str, date_str: str) -> dict:
    return load_draft_with_version(daily_dir, date_str)[0]


def save_draft(daily_dir: str, draft: dict,
               expected_version=VERSION_NOT_PROVIDED) -> None:
    from io_utils import atomic_write_json
    os.makedirs(daily_dir, exist_ok=True)
    atomic_write_json(draft_path(daily_dir, draft["date"]), draft, expected_version)


def discard_draft(daily_dir: str, date_str: str,
                  expected_version=VERSION_NOT_PROVIDED) -> None:
    from io_utils import remove_file
    try:
        remove_file(draft_path(daily_dir, date_str), expected_version)
    except FileNotFoundError:
        pass


def wizard_state(daily_dir: str, date_str: str, existing) -> dict:
    """向导页视图模型：七部位状态 + 当日已有记录（三选条用）。"""
    draft = load_draft(daily_dir, date_str)
    parts = []
    for p in PARTS:
        st = draft["parts"].get(p["part"], {})
        parts.append({**p, "status": st.get("status", "pending"),
                      "observation": st.get("observation"),
                      "has_photo": bool(st.get("photo"))})
    return {
        "date": date_str,
        "parts": parts,
        "done_count": sum(1 for p in parts if p["status"] != "pending"),
        "inquiry": draft.get("inquiry", {}),
        "context": draft.get("context", {}),
        "existing": existing,  # None 或 {"coverage": n, "uncovered": [中文名...]}
    }


def _flatten(obj, prefix=""):
    """嵌套 dict 拍平；键名规范化，异常叶子保留原类型供复核。"""
    from src.textnorm import normalize_text
    out = {}
    if isinstance(obj, dict):
        for key, value in obj.items():
            key = normalize_text(str(key)).replace("．", ".").strip()
            out.update(_flatten(value, f"{prefix}{key}." if prefix else f"{key}."))
    elif isinstance(obj, list) and all(isinstance(item, str) for item in obj):
        out[prefix.rstrip(".")] = "、".join(item.strip() for item in obj)
    else:
        out[prefix.rstrip(".")] = obj
    return out


def _custom_observation(dim, path, raw, source, method, evidence,
                        value=None, certainty=None):
    return Observation(
        path=f"{dim.english_name}.{path}", indicator_id=f"{dim.english_name}.{path}",
        source=source, method=method, raw=raw,
        certainty=certainty or {"vision": "unverified", "manual": "user_confirmed"}.get(
            source, "self_reported"),
        evidence=dict(evidence), value=value,
    )


def _write_path(node, path, value):
    if not value:
        return
    current = node
    for key in path[:-1]:
        current = current.setdefault(key, {})
    current[path[-1]] = value


_NOTE_KEYS = {"点刺依据", "舌体.点刺依据", "耳道分泌物"}


def map_observation_with_metadata(part: str, observe_json: dict,
                                  source="vision", method="photo",
                                  evidence=None, strict=True):
    if isinstance(observe_json, list):
        if len(observe_json) != 1 or not isinstance(observe_json[0], dict):
            raise ValueError("识图顶层必须是对象或单元素对象数组")
        observe_json = observe_json[0]
        evidence = dict(evidence or {}, model_output_shape="single_item_array")
    if not isinstance(observe_json, dict):
        raise ValueError("识图顶层必须是对象")
    dim = from_chinese(PART_BY_NAME[part]["dim"])
    evidence = dict(evidence or {})
    evidence.setdefault("part", part)
    mapping = OBSERVE_MAP.get(part, {})
    node = {}
    unmapped = []
    observations = []
    observe_json = dict(observe_json)
    critical = observe_json.get("危重舌象")
    if part == "舌面" and isinstance(critical, dict):
        observe_json.pop("危重舌象")
        signs = []
        for sign, present in critical.items():
            sign = str(sign).strip()
            if present is True:
                signs.append(sign)
            elif present is not False:
                observe_json[f"危重舌象.{sign}"] = present
        if signs:
            observe_json["危重舌象"] = "、".join(signs)
    flattened = _flatten(observe_json)

    def reject(key, raw, kind, message):
        node.setdefault("_raw", {})[key] = raw
        node.setdefault("_type_errors", []).append({
            "key": key, "kind": kind, "error": message})

    for flat_key, raw in flattened.items():
        if raw is None or raw == "":
            continue
        if flat_key in _NOTE_KEYS and isinstance(raw, str):
            node.setdefault("_notes", {})[flat_key] = raw
            continue
        if part == "舌面" and flat_key.startswith("危重舌象."):
            reject(flat_key, raw, "type", "危重舌象布尔映射仅接受 true/false")
            continue
        if not isinstance(raw, str):
            reject(flat_key, raw, "type",
                   f"观察值必须为字符串，收到 {type(raw).__name__}")
            continue
        if part == "舌面" and flat_key in ("复合舌苔", "舌苔复合描述", "舌苔.复合描述"):
            fields = split_coating_text(raw)
            if not fields:
                unmapped.append(flat_key)
                observations.append(_custom_observation(
                    dim, "coating.raw", raw, source, method, evidence,
                    certainty="unknown"))
                continue
            for key, normalized in fields.items():
                spec = INDICATOR_REGISTRY.for_field(dim, f"coating_{key}")
                obs = (capture_observation(dim, spec.key, raw, source, method,
                                           evidence, value=normalized)
                       if strict else _custom_observation(
                           dim, ".".join(spec.paths["B"]), raw, source, method,
                           evidence, value=normalized))
                _write_path(node, spec.paths["B"], obs.normalized)
                observations.append(obs)
            continue

        path = mapping.get(flat_key)
        spec = INDICATOR_REGISTRY.capture_spec(part, flat_key)
        if spec is not None:
            path = spec.paths["B"]
        if path == ["critical_signs"]:
            if strict and method == "photo" and any(
                    term in raw for term in ("舌强", "语謇", "不能语")):
                raise ValueError("舌强语謇需视频或人工动态/问诊，静态照片不能直接判定")
            observations.append(_custom_observation(
                dim, "critical_signs", raw, source, method, evidence, value=raw))
            _write_path(node, path, raw)
            continue
        if path is None or spec is None:
            unmapped.append(flat_key)
            observations.append(_custom_observation(
                dim, f"_raw.{flat_key}", raw, source, method, evidence,
                certainty="unknown" if strict else None))
            continue
        import records_store
        try:
            normalized = records_store.validate_field_value(dim, spec.key, raw, method)
        except ValueError as error:
            reject(flat_key, raw, "vocab", str(error))
            continue
        obs = (capture_observation(dim, spec.key, raw, source, method,
                                   evidence, value=normalized)
               if strict else _custom_observation(
                   dim, ".".join(spec.paths["B"]), raw, source, method,
                   evidence, value=normalized))
        _write_path(node, spec.paths["B"], obs.normalized)
        observations.append(obs)

    if unmapped:
        node.setdefault("_raw", {}).update({key: flattened[key] for key in unmapped})
    return node, unmapped, observations


def map_observation(part: str, observe_json: dict) -> tuple[dict, list]:
    """兼容旧接口；新写入请使用 map_observation_with_metadata。"""
    node, unmapped, _ = map_observation_with_metadata(
        part, observe_json, strict=False)
    return node, unmapped


def _part_observation_meta(st: dict, dim) -> dict:
    if isinstance(st.get("observation_meta"), dict):
        return dict(st["observation_meta"])
    source = st.get("source") or ("vision" if st.get("status") == "observed" else "manual")
    method = st.get("method") or ("photo" if source == "vision" else "manual")
    evidence = dict(st.get("evidence") or {})
    part = st.get("part") or next(
        p["part"] for p in PARTS if from_chinese(p["dim"]) == dim)
    evidence.setdefault("part", part)
    result = {}
    for flat_path, raw in _flatten(st.get("observation") or {}).items():
        if flat_path.split(".", 1)[0] in ("_raw", "_notes", "_type_errors"):
            continue
        path = flat_path.split(".")
        spec = next((s for s in INDICATOR_REGISTRY
                     if s.dimension == dim and s.paths["B"] == path), None)
        if spec is None and flat_path == "critical_signs" and method == "photo" and any(
                term in raw for term in ("舌强", "语謇", "不能语")):
            raise ValueError("舌强语謇需视频或人工动态/问诊，静态照片不能直接判定")
        obs = (capture_observation(dim, spec.key, raw, source, method, evidence)
               if spec else _custom_observation(
                   dim, flat_path, raw, source, method, evidence, value=raw))
        result[obs.path] = obs.to_meta()
    return result


def update_draft_observation(st: dict, dim, indicator: str, raw: str,
                             source: str, method: str, evidence=None, part=""):
    spec = INDICATOR_REGISTRY.for_field(dim, indicator)
    path = spec.paths["B"]
    full_path = f"{dim.english_name}." + ".".join(path)
    metadata = st.setdefault("observation_meta", {})
    if not isinstance(metadata, dict):
        raise ValueError("草稿 observation_meta 格式错误")
    if not raw:
        metadata.pop(full_path, None)
    if not isinstance(st.get("observation"), dict):
        if "observation" in st:
            print("⚠️ 警告：草稿观察结构异常，已重置为空对象", file=sys.stderr)
        st["observation"] = {}
    node = st["observation"]
    for key in path[:-1]:
        node = node.setdefault(key, {})
        if not isinstance(node, dict):
            raise ValueError("草稿观察结构异常")
    if not raw:
        node.pop(path[-1], None)
        return None
    import records_store
    normalized = records_store.validate_field_value(dim, indicator, raw, method)
    obs = capture_observation(dim, indicator, raw.strip(), source, method, evidence,
                              value=normalized)
    metadata[obs.path] = obs.to_meta()
    if obs.normalized:
        node[path[-1]] = obs.normalized
    else:
        node.pop(path[-1], None)
    st.update({"source": source, "method": method,
               "evidence": dict(evidence or {}), "part": part or st.get("part", "")})
    return obs


def observe_photo(part: str, img_path: str, **options) -> tuple[dict, list]:
    """调 vision 模型识图。返回 (observe_json, warnings)；失败抛 RuntimeError。"""
    import vision_client
    options = options or vision_client._load_config()
    key = PART_BY_NAME[part]["prompt_key"]
    _, out = vision_client.call(img_path, vision_client.PROMPTS[key],
                                image_sanitized=True, **options)
    try:
        return vision_client.extract_json(out), []
    except ValueError as error:
        raise RuntimeError(
            f"识图输出不是合法 JSON（前 80 字符：{out.strip()[:80]!r}）——"
            "模型可能未遵守「只输出 JSON」约定，请重试或更换模型") from error


# 探测词表与 detect_danger 已下沉至 src/danger.py（2026-10-21 B 批）；
# re-export 保持既有引用兼容（测试与 records_store/app.py 继续走本模块名）
from src.danger import DANGER_PATTERNS, detect_danger  # noqa: F401




def assemble_record(draft: dict, version: str,
                    existing_raw: dict | None = None,
                    merge_only_uncovered: bool = False,
                    timezone_name: str | None = None) -> dict:
    """把草稿组装为形状 B v2；保留旧记录与合并语义。"""
    date_str = draft["date"]
    if merge_only_uncovered and existing_raw:
        if "observations" not in existing_raw:
            raise ValueError("当日记录不是形状 B（旧格式/模板格式），"
                             "「补充未覆盖维度」不支持，请改用「重新分析」")
        raw = json.loads(json.dumps(existing_raw, ensure_ascii=False))
        observations = raw.setdefault("observations", {})
    else:
        raw = {}
        observations = {}
        if existing_raw:
            for key in ("diagnosis", "deepseek_diagnosis",
                        "pattern_differentiation", "pattern_update"):
                if key in existing_raw:
                    raw[key] = json.loads(json.dumps(existing_raw[key], ensure_ascii=False))
    metadata = raw.get("observation_meta", {})
    if not isinstance(metadata, dict):
        raise ValueError("旧记录 observation_meta 格式错误")
    observation_meta = dict(metadata)
    previous_declarations = raw.get("declarations", [])
    if not isinstance(previous_declarations, list) or any(
            not isinstance(item, dict) for item in previous_declarations):
        raise ValueError("旧记录 declarations 格式错误")
    declarations = [dict(item) for item in previous_declarations]

    skipped_declared, skipped_uncovered = [], []
    written_observed, written_manual = [], []
    declaration_status = {
        "skip_normal": "declared_normal", "skip_uncovered": "skipped",
        "refused": "refused", "unavailable": "unavailable",
    }
    for p in PARTS:
        st = draft["parts"].get(p["part"], {})
        status = st.get("status")
        dim = from_chinese(p["dim"])
        dim_en = dim.english_name
        if merge_only_uncovered and existing_raw:
            rec = DailyRecord(existing_raw)
            if rec.get_dimension_coverage().get(dim, False):
                continue
        if status in ("observed", "manual"):
            observation_meta.update(_part_observation_meta(st, dim))
        if status in ("observed", "manual") and st.get("observation"):
            node = observations.setdefault(dim_en, {})
            for k, v in st["observation"].items():
                if isinstance(v, dict) and k in node and isinstance(node[k], dict):
                    node[k].update(v)
                else:
                    node[k] = v
            (written_observed if status == "observed" else written_manual
             ).append(dim_en)
        elif status in declaration_status:
            kind = declaration_status[status]
            if kind == "declared_normal":
                skipped_declared.append(dim_en)
            else:
                skipped_uncovered.append(dim_en)
            observations.setdefault(dim_en, {})
            declarations.append(Declaration(
                kind, dim_en, p["part"], st.get("reason", "")).to_dict())

    prev_skipped = raw.get("skipped_dimensions", {}) if raw else {}
    raw["skipped_dimensions"] = {
        "declared_normal": sorted(set(
            prev_skipped.get("declared_normal", []) + skipped_declared)),
        "uncovered": sorted(set(
            prev_skipped.get("uncovered", []) + skipped_uncovered)),
    }
    if not raw.get("date"):
        raw.update({
            "record_id": f"{date_str}-web",
            "date": date_str,
            "timestamp": time_utils.iso_now(timezone_name),
            "version": version,
        })
    raw["photo_coverage"] = sorted(set(
        (raw.get("photo_coverage") or []) + written_observed))
    photos = raw.get("photos", {})
    if not isinstance(photos, dict):
        raise ValueError("旧记录 photos 格式错误")
    photos = dict(photos)
    for part in PARTS:
        st = draft["parts"].get(part["part"], {})
        if st.get("status") == "observed" and st.get("photo"):
            photos[part["part"]] = st["photo"]
    raw["photos"] = photos
    manual_dims = sorted(set((raw.get("manual_entry") or []) + written_manual))
    if manual_dims:
        raw["manual_entry"] = manual_dims
    raw["observations"] = observations
    raw["observation_meta"] = observation_meta
    raw["declarations"] = declarations
    raw["schema_version"] = SCHEMA_VERSION
    if "context" in draft:
        if not isinstance(draft["context"], dict):
            raise ValueError("context 必须为对象")
        raw["context"] = dict(draft["context"])
    else:
        raw.setdefault("context", {})

    if merge_only_uncovered and existing_raw and isinstance(
            existing_raw.get("inquiry"), dict):
        raw["inquiry"] = dict(existing_raw["inquiry"])
    for q, answer in (draft.get("inquiry") or {}).items():
        if answer:
            raw.setdefault("inquiry", {})[q] = {"asked": True, "answer": answer}

    if "danger_flags" in draft:
        raw["danger_flags"] = draft["danger_flags"]
    else:
        from src.danger import danger_flags_for
        raw["danger_flags"] = danger_flags_for(
            {"observations": observations, "inquiry": draft.get("inquiry") or {},
             "context": raw["context"]},
            previous=raw.get("danger_flags"),
        )
    if "danger_review" in draft:
        raw["danger_review"] = draft["danger_review"]
    rec_check = DailyRecord(raw)
    raw["confidence"] = from_coverage(rec_check.get_covered_dimension_count()).value
    from src.derived import current_derived_meta
    raw["derived_meta"] = current_derived_meta(rec_check)
    return raw


def refresh_draft_review(draft: dict, source="inquiry", client="") -> dict:
    """问诊/上下文变化后刷新草稿红线，不触碰原始答案或观察值。"""
    from src.danger_review import refresh_danger
    observations = {}
    for part in PARTS:
        st = draft["parts"].get(part["part"], {})
        if isinstance(st.get("observation"), dict) and st["observation"]:
            observations[from_chinese(part["dim"]).english_name] = st["observation"]
    raw = {"observations": observations,
           "inquiry": draft.get("inquiry") or {},
           "context": draft.get("context") or {},
           "danger_flags": draft.get("danger_flags") or {},
           "danger_review": draft.get("danger_review") or []}
    events = refresh_danger(raw, source=source, client=client)
    draft["danger_flags"] = raw["danger_flags"]
    draft["danger_review"] = raw["danger_review"]
    return events


def danger_triggered(raw: dict) -> list:
    return DailyRecord(raw).get_triggered_danger_flags()
