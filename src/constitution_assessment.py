"""GB/T 46939—2025 体质分类与判定的独立规则注册表。"""
from __future__ import annotations

from dataclasses import dataclass

STANDARD_ID = "GB/T 46939—2025"
QUESTIONNAIRE_VERSION = "appendixA-2025"
CONSTITUTIONS = ("平和质", "气虚质", "阳虚质", "阴虚质", "痰湿质", "湿热质",
                 "血瘀质", "气郁质", "特禀质")


@dataclass(frozen=True)
class RuleEntry:
    entry_id: str
    constitution: str
    question: str
    gender_condition: str
    score_direction: str
    source_clause: str
    source_pdf_page: int


def _entry(table, number, constitution, question, page, gender="all", direction="forward"):
    return RuleEntry(
        entry_id=f"GB46939-A{table}-{number:02d}",
        constitution=constitution,
        question=question,
        gender_condition=gender,
        score_direction=direction,
        source_clause=f"附录A 表A.{table} 第({number})项",
        source_pdf_page=page,
    )


RULE_ENTRIES = (
    _entry(1, 1, "平和质", "您精力充沛吗?", 13),
    _entry(1, 2, "平和质", "您容易疲乏吗?", 13, direction="reverse"),
    _entry(1, 3, "平和质", "您感到闷闷不乐、情绪低沉吗?", 13, direction="reverse"),
    _entry(1, 4, "平和质", "您比一般人耐受不了寒冷（冬天的寒冷，夏天的冷空调、电扇等）吗?", 13,
           direction="reverse"),
    _entry(2, 1, "气虚质", "您容易疲乏吗?", 13),
    _entry(2, 2, "气虚质", "您容易气短（呼吸短促，接不上气）吗?", 13),
    _entry(2, 3, "气虚质", "您容易心慌吗?", 13),
    _entry(3, 1, "阳虚质", "您胃脘部、背部或腰膝部怕冷吗?", 13),
    _entry(3, 2, "阳虚质", "您感到怕冷、衣服比别人穿得多吗?", 13),
    _entry(3, 3, "阳虚质", "您比一般人耐受不了寒冷（冬天的寒冷，夏天的冷空调、电扇等）吗?", 13),
    _entry(4, 1, "阴虚质", "您感觉身体、脸上发热吗?", 14),
    _entry(4, 2, "阴虚质", "您皮肤或口唇干吗?", 14),
    _entry(4, 3, "阴虚质", "您面部两颧潮红或偏红吗?", 14),
    _entry(5, 1, "痰湿质", "您感到身体沉重不轻松或不爽快吗?", 14),
    _entry(5, 2, "痰湿质", "您腹部肥满松软吗?", 14),
    _entry(5, 3, "痰湿质", "您嘴里有黏黏的感觉吗?", 14),
    _entry(6, 1, "湿热质", "您面部或鼻部有油腻感或者油亮发光吗?", 14),
    _entry(6, 2, "湿热质", "您小便时尿道有发热感、尿色浓（深）吗?", 14),
    _entry(6, 3, "湿热质", "您带下色黄（白带颜色发黄）吗?", 14, gender="female_only"),
    _entry(6, 4, "湿热质", "您的阴囊部位潮湿吗?", 14, gender="male_only"),
    _entry(7, 1, "血瘀质", "您身体上有哪里疼痛吗?", 14),
    _entry(7, 2, "血瘀质", "您面色晦暗或容易出现褐斑吗?", 14),
    _entry(7, 3, "血瘀质", "您口唇颜色偏暗吗?", 14),
    _entry(8, 1, "气郁质", "您感到闷闷不乐、情绪低沉吗?", 15),
    _entry(8, 2, "气郁质", "您容易精神紧张、焦虑不安吗?", 15),
    _entry(8, 3, "气郁质", "您多愁善感、感情脆弱吗?", 15),
    _entry(9, 1, "特禀质", "您没有感冒时也会打喷嚏吗?", 15),
    _entry(9, 2, "特禀质", "您容易过敏（对药物、食物、气味、花粉或在季节交替、气候变化时）吗?", 15),
    _entry(9, 3, "特禀质", "您的皮肤容易起荨麻疹（风团、风疹块、风疙瘩）吗?", 15),
    _entry(9, 4, "特禀质", "您的皮肤一抓就红，并出现抓痕吗?", 15),
)
RULE_BY_ID = {entry.entry_id: entry for entry in RULE_ENTRIES}


def _validate_registry():
    if len(RULE_ENTRIES) != 30 or len(RULE_BY_ID) != 30:
        raise RuntimeError("GB/T 46939—2025 规则必须包含30个唯一条目")
    if {entry.constitution for entry in RULE_ENTRIES} != set(CONSTITUTIONS):
        raise RuntimeError("九种体质规则不完整")
    for entry in RULE_ENTRIES:
        if entry.gender_condition not in {"all", "female_only", "male_only"}:
            raise RuntimeError(f"非法性别条件: {entry.entry_id}")
        if entry.score_direction not in {"forward", "reverse"}:
            raise RuntimeError(f"非法计分方向: {entry.entry_id}")
        if entry.source_pdf_page not in {13, 14, 15}:
            raise RuntimeError(f"非法来源页码: {entry.entry_id}")


_validate_registry()


def _normalize_answers(answers):
    from collections.abc import Mapping
    if isinstance(answers, Mapping):
        pairs = list(answers.items())
    else:
        if isinstance(answers, (str, bytes)):
            raise TypeError("答案必须是题目到字符串分值的映射或键值对序列")
        try:
            pairs = list(answers)
        except TypeError as error:
            raise TypeError("答案必须是题目到字符串分值的映射或键值对序列") from error
    normalized = {}
    for pair in pairs:
        if not isinstance(pair, (tuple, list)) or len(pair) != 2:
            raise TypeError("每个答案必须是（entry_id, 字符串分值）键值对")
        entry_id, value = pair
        if not isinstance(entry_id, str) or entry_id not in RULE_BY_ID:
            raise ValueError(f"未知题号: {entry_id!r}")
        if entry_id in normalized:
            raise ValueError(f"重复题号: {entry_id}")
        if not isinstance(value, str):
            raise TypeError(f"答案必须是字符串: {entry_id}")
        value = value.strip()
        if not value:
            raise ValueError(f"空答案: {entry_id}")
        scores = {"1": 1, "2": 2, "3": 3, "4": 4, "5": 5,
                  "没有（根本不）": 1, "很少（有一点）": 2, "有时（有些）": 3,
                  "经常（相当）": 4, "总是（非常）": 5}
        if value not in scores:
            raise ValueError(f"非法分值: {entry_id}={value!r}")
        normalized[entry_id] = value
    return normalized


def _normalize_gender(gender):
    if not isinstance(gender, str):
        raise ValueError("体质评估前必须选择男性或女性")
    try:
        return {"male": "male", "female": "female", "男性": "male", "女性": "female"}[
            gender.strip()]
    except KeyError as error:
        raise ValueError("体质评估前必须选择男性或女性") from error


def _biased_result(score):
    if score >= 40:
        return "是"
    if score >= 30:
        return "倾向是"
    return "否"


def _display_score(score):
    return f"{float(score):.2f}"


def evaluate_constitution(answers, gender=None, *, skipped=False):
    """按独立国标规则评估；返回答案、精确分数、九类结果、兼夹与未知项。"""
    from fractions import Fraction
    if skipped:
        return {
            "status": "skipped", "standard_id": STANDARD_ID,
            "questionnaire_version": QUESTIONNAIRE_VERSION,
            "gender": None, "answers": {}, "item_scores": {},
            "results": {}, "combined_results": [],
            "unknown": {"categories": [], "items": {}},
        }
    gender = _normalize_gender(gender)
    answers = _normalize_answers(answers)
    item_scores = {}
    for entry in RULE_ENTRIES:
        if entry.entry_id not in answers:
            continue
        if entry.gender_condition == "female_only" and gender != "female" \
                or entry.gender_condition == "male_only" and gender != "male":
            continue
        value = {"1": 1, "2": 2, "3": 3, "4": 4, "5": 5,
                 "没有（根本不）": 1, "很少（有一点）": 2, "有时（有些）": 3,
                 "经常（相当）": 4, "总是（非常）": 5}[answers[entry.entry_id]]
        item_scores[entry.entry_id] = 6 - value if entry.score_direction == "reverse" else value

    results = {}
    unknown_categories = []
    unknown_items = {}
    for constitution in CONSTITUTIONS:
        entries = [entry for entry in RULE_ENTRIES if entry.constitution == constitution]
        applicable = [entry for entry in entries
                      if not (entry.gender_condition == "female_only" and gender != "female"
                              or entry.gender_condition == "male_only" and gender != "male")]
        excluded = [entry.entry_id for entry in entries if entry not in applicable]
        missing = [entry.entry_id for entry in applicable if entry.entry_id not in answers]
        source_clause = entries[0].source_clause.split(" 第", 1)[0]
        result = {"constitution": constitution,
                  "item_count": len(applicable), "unknown_items": missing,
                  "excluded_items": excluded,
                  "source_clause": source_clause,
                  "source_pdf_page": entries[0].source_pdf_page}
        if missing:
            result.update(result="unknown", raw_score=None,
                          converted_score=None, display_score=None)
            unknown_categories.append(constitution)
            unknown_items[constitution] = missing
        else:
            raw_score = sum(item_scores[entry.entry_id] for entry in applicable)
            converted = Fraction(raw_score - len(applicable), len(applicable) * 4) * 100
            result.update(result=_biased_result(converted), raw_score=raw_score,
                          converted_score=converted, display_score=_display_score(converted))
        results[constitution] = result

    if any(results[constitution]["result"] == "unknown" for constitution in CONSTITUTIONS):
        results["平和质"].update(result="unknown", raw_score=None,
                               converted_score=None, display_score=None)
        if "平和质" not in unknown_categories:
            unknown_categories.insert(0, "平和质")
            if results["平和质"]["unknown_items"]:
                unknown_items["平和质"] = results["平和质"]["unknown_items"]
    else:
        score = results["平和质"]["converted_score"]
        others = [results[constitution]["converted_score"] for constitution in CONSTITUTIONS[1:]]
        if score >= 60 and all(value < 30 for value in others):
            results["平和质"]["result"] = "是"
        elif score >= 60 and all(value < 40 for value in others):
            results["平和质"]["result"] = "基本是"
        else:
            results["平和质"]["result"] = "否"

    combined = []
    for constitution in CONSTITUTIONS[1:]:
        category = results[constitution]
        if category["result"] in {"是", "倾向是"}:
            combined.append({key: category[key] for key in
                             ("constitution", "result", "converted_score",
                              "display_score", "source_clause", "source_pdf_page")})
    return {
        "status": "completed", "standard_id": STANDARD_ID,
        "questionnaire_version": QUESTIONNAIRE_VERSION, "gender": gender,
        "answers": answers, "item_scores": item_scores, "results": results,
        "combined_results": combined,
        "unknown": {"categories": unknown_categories, "items": unknown_items},
        "entry_sources": {entry.entry_id: {"clause": entry.source_clause,
                                           "pdf_page": entry.source_pdf_page}
                          for entry in RULE_ENTRIES},
        "method_source": {"clause": "5.1 判定方法；5.2 判定标准 表1", "pdf_page": 12},
    }
