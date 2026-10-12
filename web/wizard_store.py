"""拍照向导存取层：七部位拍摄 → vision 识图 → 形状 B 记录组装。

草稿存 records/daily/.wizard-<date>.json（以点开头，不参与选档 glob
的 YYYY-MM-DD 前缀匹配；records/daily/* 已被 gitignore）。
"""
from __future__ import annotations

import datetime
import importlib
import json
import os
import re

from src import paths
from src.confidence import from_coverage
from src.dimensions import DIMENSIONS, from_chinese
from src.record import DailyRecord

# 七部位（顺序即向导步骤）；prompt_key 对齐 scripts/vision_client.py PROMPTS
PARTS = [
    {"part": "舌面", "prompt_key": "舌面",   "dim": "舌诊",
     "tips": ["自然光下拍摄，避开有色光源", "伸舌自然放松，勿用力前伸", "禁用闪光灯"]},
    {"part": "舌底", "prompt_key": "舌底",   "dim": "舌诊",
     "tips": ["舌尖抵上腭，露出舌下络脉", "⚠️ 严禁闪光灯（会加剧过度判读）", "对焦舌下两侧络脉"]},
    {"part": "头面", "prompt_key": "头面部", "dim": "头面诊",
     "tips": ["正面素颜，免冠", "面向自然光源，避免逆光", "包含完整面部与唇周"]},
    {"part": "目",   "prompt_key": "眼部",   "dim": "目诊",
     "tips": ["睁眼平视镜头", "白睛清晰可见", "分别拍摄双眼"]},
    {"part": "耳",   "prompt_key": "耳部",   "dim": "耳诊",
     "tips": ["侧对光源", "双耳各拍一张", "耳轮完整入镜"]},
    {"part": "手",   "prompt_key": "手掌",   "dim": "手诊",
     "tips": ["掌心向上自然摊开", "五指微分，甲床清晰", "禁用闪光灯"]},
    {"part": "皮肤", "prompt_key": "皮肤",   "dim": "皮肤诊",
     "tips": ["前臂或小腿伸侧", "自然光下拍摄", "如有黄汗/甲错部位请特写"]},
]
PART_BY_NAME = {p["part"]: p for p in PARTS}

# 识图输出（中文键，可嵌套）→ 形状 B 英文路径。
# 未收录的键不丢弃：进 <dim>._raw 保留并在 UI 告警（不静默丢数据）。
OBSERVE_MAP = {
    "舌面": {
        "舌质颜色": ["body", "color"], "舌质润燥": ["body", "luster"],
        "舌体.胖瘦": ["body", "shape"], "舌体.齿痕": ["body", "tooth_marks"],
        "舌体.裂纹": ["body", "cracks"], "舌体.点刺": ["body", "prickles"],
        "点刺": ["body", "prickles"],
        "舌苔.颜色": ["coating", "color"], "舌苔.厚薄": ["coating", "thickness"],
        "舌苔.润燥": ["coating", "moisture"], "舌苔.腻腐": ["coating", "greasy"],
        "舌苔.剥落": ["coating", "peeling"],
    },
    "舌底": {
        "颜色": ["sublingual", "vein_color"], "粗细": ["sublingual", "vein_thickness"],
        "走行判断": ["sublingual", "vein_tortuosity"],
    },
    "头面部": {
        "面色": ["face", "color"], "面部浮肿": ["face", "edema"],
        "唇色": ["lips", "color"], "唇润燥": ["lips", "moisture"],
    },
    "眼部": {
        "目赤": ["redness"], "巩膜黄染": ["scleral_jaundice"],
        "眼睑浮肿": ["eyelid_edema"], "白睛颜色": ["sclera_color"],
    },
    "耳部": {"耳色": ["color"], "润枯": ["helix"]},
    "手掌": {"掌色": ["palm_color"], "甲床颜色": ["nail_bed"],
             "甲床形态": ["nail_shape"]},
    "皮肤": {"肤色": ["color"], "甲错": ["scaly_skin"], "水肿": ["edema"],
             "皮肤干燥程度": ["dryness"]},
}

# 「未拍摄（用户声明正常）」占位：写到该维度第一个指标路径（validator 对该
# 措辞有豁免，见 input_validator 词表覆盖检查注释；KNOWN_ISSUES #10 定策）
DECLARED_NORMAL_PLACEHOLDER = "未拍摄（用户声明正常）"


def draft_path(daily_dir: str, date_str: str) -> str:
    return os.path.join(daily_dir, f".wizard-{date_str}.json")


def load_draft(daily_dir: str, date_str: str) -> dict:
    p = draft_path(daily_dir, date_str)
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {"date": date_str, "parts": {}}


def save_draft(daily_dir: str, draft: dict) -> None:
    os.makedirs(daily_dir, exist_ok=True)
    with open(draft_path(daily_dir, draft["date"]), "w", encoding="utf-8") as f:
        json.dump(draft, f, ensure_ascii=False, indent=2)


def discard_draft(daily_dir: str, date_str: str) -> None:
    try:
        os.unlink(draft_path(daily_dir, date_str))
    except OSError:
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
        "existing": existing,  # None 或 {"coverage": n, "uncovered": [中文名...]}
    }


def _flatten(obj, prefix=""):
    """嵌套 dict 拍平为 {点号路径: 叶子文本}。"""
    out = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.update(_flatten(v, f"{prefix}{k}." if prefix else f"{k}."))
    else:
        out[prefix.rstrip(".")] = "" if obj is None else str(obj).strip()
    return out


def map_observation(part: str, observe_json: dict) -> tuple[dict, list]:
    """把某部位的识图 JSON 映射为形状 B 的英文路径节点。

    返回 (dim_node, unmapped_keys)。未识别键进 dim_node["_raw"] 保留。
    """
    mapping = OBSERVE_MAP.get(part, {})
    node: dict = {}
    unmapped = []
    for flat_key, value in _flatten(observe_json).items():
        if not value:
            continue
        if flat_key in mapping:
            path = mapping[flat_key]
            cur = node
            for k in path[:-1]:
                cur = cur.setdefault(k, {})
            cur[path[-1]] = value
        else:
            unmapped.append(flat_key)
    if unmapped:
        node["_raw"] = {k: _flatten(observe_json)[k] for k in unmapped}
    return node, unmapped


def observe_photo(part: str, img_path: str) -> tuple[dict, list]:
    """调 vision 模型识图。返回 (observe_json, warnings)；失败抛 RuntimeError。"""
    import vision_client
    importlib.reload(vision_client)  # 模块级 MODEL/URL 在 import 时读取，跟随最新配置
    key = PART_BY_NAME[part]["prompt_key"]
    _, out = vision_client.call(img_path, vision_client.PROMPTS[key])
    candidate = out.strip()
    if candidate.startswith("```"):
        candidate = candidate.split("\n", 1)[1] if "\n" in candidate else ""
        candidate = candidate.rsplit("```", 1)[0].strip()
    try:
        return json.loads(candidate), []
    except json.JSONDecodeError:
        raise RuntimeError(
            f"识图输出不是合法 JSON（前 80 字符：{out.strip()[:80]!r}）——"
            f"模型可能未遵守「只输出 JSON」约定，请重试或更换模型")


def assemble_record(draft: dict, version: str,
                    existing_raw: dict | None = None,
                    merge_only_uncovered: bool = False) -> dict:
    """把草稿组装为形状 B 记录。

    merge_only_uncovered=True 时在 existing_raw 基础上只补未覆盖维度
    （「补充未覆盖维度」入口）；否则整体重建（当日重分析由调用方先备份）。
    """
    date_str = draft["date"]
    observations: dict = {}
    if merge_only_uncovered and existing_raw:
        observations = json.loads(json.dumps(
            existing_raw.get("observations", {}), ensure_ascii=False))

    for p in PARTS:
        st = draft["parts"].get(p["part"], {})
        status = st.get("status")
        dim = from_chinese(p["dim"])
        dim_en = dim.english_name
        if merge_only_uncovered and existing_raw:
            rec = DailyRecord(existing_raw)
            if dim.is_covered(rec.get_observation(dim)):
                continue  # 已覆盖维度不动
        if status == "observed" and st.get("observation"):
            node = observations.setdefault(dim_en, {})
            for k, v in st["observation"].items():
                if isinstance(v, dict) and k in node and isinstance(node[k], dict):
                    node[k].update(v)
                else:
                    node[k] = v
        elif status == "skip_normal":
            node = observations.setdefault(dim_en, {})
            from src.record import _DIMENSION_INDICATORS, _flatten_to_text
            if _flatten_to_text(node):
                continue  # 同维度另一部位已识图（如舌面+舌底），占位不覆盖真值
            first = next(iter(_DIMENSION_INDICATORS[dim]))
            path = _DIMENSION_INDICATORS[dim][first]["B"]
            cur = node
            for k in path[:-1]:
                cur = cur.setdefault(k, {})
            cur[path[-1]] = DECLARED_NORMAL_PLACEHOLDER
        # skip_uncovered：什么都不写（维度缺席 = 未覆盖）

    raw = {
        "record_id": f"{date_str}-web",
        "date": date_str,
        "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
        "version": version,
        "photo_coverage": sorted({from_chinese(PART_BY_NAME[pt]["dim"]).english_name
            for pt, st in draft["parts"].items() if st.get("status") == "observed"}),
        "observations": observations,
        "danger_flags": draft.get("danger_flags") or {
            "triggered": [],
            "not_triggered": ["daiyang", "skin_cold", "flesh_wasted",
                              "tongue_rigid", "tongue_critical", "mirror_tongue",
                              "acute_jaundice", "wind_stroke", "throat_erosion"],
        },
    }
    covered = DailyRecord(raw).get_covered_dimension_count()
    raw["confidence"] = from_coverage(covered).value
    return raw


def danger_triggered(raw: dict) -> list:
    return DailyRecord(raw).get_triggered_danger_flags()
