"""定向文本规范化；不改变全角问号、括号或原始记录。"""
from __future__ import annotations

import re
import unicodedata

_TRADITIONAL = {}
for _line in (
    "鏡镜 絕绝 黃黄 紅红 豬猪 藍蓝 視视 強强 體体 語语 無无 見见 陽阳 陰阴",
    "氣气 虛虚 實实 熱热 濕湿 潤润 證证 脈脉 細细 張张 顏颜 蒼苍 膚肤 錯错",
    "長长 時时 間间 難难 這这 個个 為为 於于 腫肿 脹胀 凍冻 涼凉 溫温 屬属",
    "邊边 緣缘 齒齿 點点 輕轻 顫颤 動动 軟软 縮缩 適适 緊紧 淺浅 渾浑 濁浊",
    "榮荣 華华 淨净 剝剥 脫脱 膩腻 幹干 結结 調调 藥药 書书 門门 問问 題题",
    "診诊 斷断 開开 關关 閉闭 內内 外外 與与 對对 導导 緻致 遠远 進进 過过",
    "應应 該该 說说 話话 現现 劑剂 數数 類类 準准 確确 覺觉 學学 醫医 療疗",
):
    for _pair in _line.split():
        _TRADITIONAL[_pair[0]] = _pair[1]

_COMPATIBILITY = ((0x2F00, 0x2FDF), (0xF900, 0xFAFF), (0x2F800, 0x2FA1F))
_HAN = r"⺀-⻿一-鿿豈-﫿\u2f800-\u2fa1f"
_CJK_SPACE = re.compile(rf"([{_HAN}])\s+(?=[{_HAN}])")
_NON_NEGATION = re.compile(r"不规则|不均匀?|不匀|不整|不等|不一")


def normalize_text(text: str) -> str:
    if not isinstance(text, str):
        raise TypeError("文本规范化只接受字符串")
    out = []
    for char in text:
        if unicodedata.category(char) == "Cf":
            continue
        code = ord(char)
        if any(start <= code <= end for start, end in _COMPATIBILITY):
            char = unicodedata.normalize("NFKC", char)
        out.append(_TRADITIONAL.get(char, char))
    return _CJK_SPACE.sub(r"\1", "".join(out)).strip()


def display_text(text: str, limit: int = 200) -> str:
    text = re.sub(r"\s+", " ", normalize_text(text)).strip()
    text = "".join(char for char in text if unicodedata.category(char) != "Cc")
    if limit < 1:
        raise ValueError("文本限长必须为正数")
    return text if len(text) <= limit else text[:limit - 1] + "…"


def has_line_breaks(text: str) -> bool:
    return any(char in "\r\n\v\f\x1c\x1d\x1e\x85\u2028\u2029" for char in text)


def canonical_option(text: str) -> str:
    return normalize_text(text).replace("（", "(").replace("）", ")").replace("？", "?")


def mask_non_negations(text: str) -> str:
    return _NON_NEGATION.sub("__", normalize_text(text))
