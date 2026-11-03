#!/usr/bin/env python3
"""望诊识图统一入口 — OpenAI 兼容视觉模型。
模型/端点/Key 通过环境变量或 .env 配置（环境变量优先）；VISION_BASE_URL 必填。
默认模型名 qwen3.8-max 仅为示例，未配置端点时不使用默认第三方地址。
可选请求参数（运行时读取）：VISION_TEMPERATURE（默认不发送该键）/ VISION_MAX_TOKENS（默认 600）/ VISION_TIMEOUT（默认 150，classify 固定 60）。
用法:
  python3 vision_client.py classify <img>              # 2a 部位分类
  python3 vision_client.py observe <img> <part-key>    # 2b 详细观察 (part-key 从 prompt_map 选)
"""
import base64
import json
import math
import os
import re
import sys
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from src.indicators import INDICATOR_REGISTRY
import envfile
from safe_fetch import HTTPStatusError, fetch_json

USAGE = ("用法: vision_client.py classify <img> | "
         "vision_client.py observe <img> <part-key>")
WARN_PREFIX = "[vision_client][warn]"
_LEGACY_KEY_NAMES = ("DASHSCOPE_API_KEY",)
_legacy_warned: set = set()


def _reset_legacy_warn_state():
    _legacy_warned.clear()


def _warn_legacy_key(name):
    if name in _legacy_warned:
        return
    _legacy_warned.add(name)
    print(f"{WARN_PREFIX} 正在使用历史兼容变量 {name} 提供 API Key——功能正常，"
          "但该变量仅为兼容保留，建议迁移到 VISION_API_KEY", file=sys.stderr)


def _read_env_text(path):
    """CLI 读取保留非 UTF-8 告警与替换字符兼容；Web 使用严格解码。"""
    with open(path, "rb") as file:
        raw = file.read()
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        print(f"{WARN_PREFIX} 读取 {path} 发生非 UTF-8 解码失败（{error}）——"
              "已按替换字符（U+FFFD）继续处理；建议转为 UTF-8", file=sys.stderr)
        return raw.decode("utf-8-sig", errors="replace")


def _config_values():
    paths = [".env", os.path.expanduser("~/.config/tcm-tongue/.env")]
    if os.environ.get("VISION_ENABLE_LEGACY_ENV_PATHS") == "1":
        paths.extend([os.path.expanduser("~/.hermes/profiles/tcm-tongue/.env"),
                      os.path.expanduser("~/.hermes/.env")])
    values = {}
    for path in paths:
        try:
            for key, value in envfile.parse_env(_read_env_text(path), path).items():
                if value:
                    values.setdefault(key, value)
        except FileNotFoundError:
            pass
    for key in ("VISION_MODEL", "VISION_BASE_URL", "VISION_MAX_TOKENS",
                "VISION_TIMEOUT", "VISION_TEMPERATURE"):
        values[key] = os.environ.get(key) or values.get(key, "")
    legacy = os.environ.get("DASHSCOPE_API_KEY")
    key = os.environ.get("VISION_API_KEY") or values.get("VISION_API_KEY", "")
    if legacy and not os.environ.get("VISION_API_KEY"):
        _warn_legacy_key("DASHSCOPE_API_KEY")
        key = legacy
    elif not key and values.get("DASHSCOPE_API_KEY"):
        _warn_legacy_key("DASHSCOPE_API_KEY")
        key = values["DASHSCOPE_API_KEY"]
    values["VISION_API_KEY"] = key
    return values


def _positive_int(key, value):
    try:
        result = int(str(value))
    except (TypeError, ValueError) as error:
        raise RuntimeError(f"{key} 必须是正整数，实际为 {value!r}") from error
    if result <= 0:
        raise RuntimeError(f"{key} 必须是正整数，实际为 {value!r}")
    return result


def _load_config():
    values = _config_values()
    temperature = values["VISION_TEMPERATURE"]
    if temperature:
        try:
            temperature = float(temperature)
        except ValueError as error:
            raise RuntimeError("VISION_TEMPERATURE 必须是有限数值") from error
        if not math.isfinite(temperature):
            raise RuntimeError("VISION_TEMPERATURE 必须是有限数值")
    else:
        temperature = None
    return {
        "model": values["VISION_MODEL"] or "qwen3.8-max",
        "url": values["VISION_BASE_URL"],
        "key": values["VISION_API_KEY"],
        "timeout": _positive_int("VISION_TIMEOUT", values["VISION_TIMEOUT"] or 150),
        "max_tokens": _positive_int("VISION_MAX_TOKENS",
                                    values["VISION_MAX_TOKENS"] or 600),
        "temperature": temperature,
    }


def load_key():
    return _config_values()["VISION_API_KEY"]


PROMPTS = {
    "舌面": "这是一张舌面照片，请精确观察并只输出JSON：舌质颜色、舌苔(颜色/厚薄/润燥/腻腐/剥落/苔量/分布)、舌体(胖瘦/齿痕/裂纹/点刺)、舌质润燥、瘀斑瘀点。舌质颜色只填规范词：{舌面|舌质颜色}（五档，勿用其他词；暗红按红绛记，青紫/淡紫按紫暗记——肉眼难分的颜色一律归并，不勉强细分）。舌苔颜色只填规范词：{舌面|舌苔.颜色}。舌苔厚薄只填规范词：{舌面|舌苔.厚薄}。舌苔润燥只填规范词：{舌面|舌苔.润燥}。舌苔剥落只填规范词：{舌面|舌苔.剥落}。舌苔.苔量只填规范词：{舌面|舌苔.苔量}。舌苔.分布只填规范词：{舌面|舌苔.分布}。舌体裂纹只填规范词：{舌面|舌体.裂纹}。舌质润燥(键名固定为\"舌质润燥\")只填规范词：{舌面|舌质润燥}。舌苔腻腐只填规范词：{舌面|舌苔.腻腐}。舌体胖瘦只填规范词：{舌面|舌体.胖瘦}；若观察到复合描述（如\"胖嫩\"\"瘦薄\"），只按胖瘦成分填写（胖嫩→偏胖，瘦薄→偏瘦），老嫩/厚薄成分不进该字段。齿痕只填规范词：{舌面|舌体.齿痕}（不填\"明显齿痕\"\"舌缘可见\"等描述性短语）。瘀斑瘀点只填规范词：{舌面|瘀斑瘀点}。点刺：输出两个键——\"点刺\"与\"点刺依据\"。先观察舌尖与舌边是否有明显凸起的红色颗粒，在\"点刺依据\"里一句话说明凸起程度与分布；\"点刺\"只填规范词：{舌面|舌体.点刺}。注意区分舌面中央的浅沟是生理性正中沟还是深宽病理裂纹。不判舌神/荣枯（照片光线干扰、静态不可判）。危重舌象出口：仅当观察到明确符合下列典型形态的舌象时，额外输出一个键「危重舌象」，值为对应名称（猪腰舌/镜面舌/砂皮舌/干荔舌/火柿舌/赭黑舌/瘦薄无苔舌/囊缩卷舌/蓝舌）；不典型或不确定则**不输出该键**（宁缺毋滥，不误报）。该键不参与评分，仅触发安全复核。舌强语謇需视频或人工动态/问诊，静态照片不得输出该结论。",
    "舌底": "观察舌下络脉。正常基线：浅蓝紫细条、平直。只记录相对粗细，无比例尺时不得输出毫米数值或毫米阈值结论；只有画面中存在可靠比例尺时才允许另作测量。只输出JSON：颜色只填规范词：{舌底|颜色}；粗细只填规范词：{舌底|粗细}；走行判断只填规范词：{舌底|走行判断}；瘀点只填规范词：{舌底|瘀点}。",
    "头面部": "观察并只输出JSON：面色只填规范词：{头面部|面色}；唇色只填规范词：{头面部|唇色}；唇润燥只填规范词：{头面部|唇润燥}；面部浮肿只填规范词：{头面部|面部浮肿}。鼻翼煽动需视频或人工动态观察，静态照片不得输出该结论。",
    "眼部": "轻拉下睑，充分暴露下睑结膜；未暴露时下睑结膜颜色留空，不得猜测。观察并只输出JSON：白睛颜色只填规范词：{眼部|白睛颜色}；目赤只填规范词：{眼部|目赤}；巩膜黄染只填规范词：{眼部|巩膜黄染}；眼睑浮肿只填规范词：{眼部|眼睑浮肿}；下睑结膜颜色只填规范词：{眼部|下睑结膜颜色}。",
    "耳部": "观察并只输出JSON：耳色只填规范词：{耳部|耳色}；润枯只填规范词：{耳部|润枯}；耳道分泌物。",
    "手掌": "观察并只输出JSON：掌色只填规范词：{手掌|掌色}；甲床颜色只填规范词：{手掌|甲床颜色}；甲床形态只填规范词：{手掌|甲床形态}。",
    "皮肤": "观察并只输出JSON：肤色只填规范词：{皮肤|肤色}；甲错只填规范词：{皮肤|甲错}；水肿只填规范词：{皮肤|水肿}；皮肤干燥程度只填规范词：{皮肤|皮肤干燥程度}。水肿的凹陷必须来自人工触诊或自陈，不能由照片推测；黄汗只接受问诊或衣物证据，不从普通皮肤颜色推断。",
    "其他": "描述这张照片的望诊相关特征，输出JSON。",
}

for _spec in INDICATOR_REGISTRY:
    if _spec.prompt_part not in PROMPTS:
        continue
    _token = "{" + _spec.prompt_part + "|" + _spec.prompt_key + "}"
    if _token not in PROMPTS[_spec.prompt_part]:
        raise ValueError(f"识图 prompt 缺指标占位: {_token}")
    PROMPTS[_spec.prompt_part] = PROMPTS[_spec.prompt_part].replace(
        _token, "/".join(_spec.prompt_options or ()))
del _spec, _token

MIME_MAP = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}

def mime_type(img_path):
    """按扩展名映射 MIME，未知回退 image/jpeg。"""
    return MIME_MAP.get(os.path.splitext(img_path)[1].lower(), "image/jpeg")

def _message_content(data):
    if not isinstance(data, dict):
        raise RuntimeError("vision API 响应顶层必须是对象")
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise RuntimeError("vision API 响应缺少有效 choices")
    choice = choices[0]
    message = choice.get("message")
    if not isinstance(message, dict):
        raise RuntimeError("vision API message 缺失或不是对象"
                           f"（finish_reason={choice.get('finish_reason')!r}）")
    content = message.get("content")
    if content is None:
        content = ""
    elif isinstance(content, list):
        content = "".join(part.get("text", "") for part in content
                          if isinstance(part, dict) and part.get("type") == "text"
                          and isinstance(part.get("text"), str))
    if not isinstance(content, str):
        raise RuntimeError("vision API content 类型不支持")
    return content, choice, message


def call(img_path, prompt, *, model=None, url=None, key=None, timeout=None,
         max_tokens=None, temperature=None, image_sanitized=False):
    if model is None or url is None or key is None:
        config = _load_config()
        model = config["model"] if model is None else model
        url = config["url"] if url is None else url
        key = config["key"] if key is None else key
        timeout = config["timeout"] if timeout is None else timeout
        max_tokens = config["max_tokens"] if max_tokens is None else max_tokens
        temperature = config["temperature"] if temperature is None else temperature
    timeout = _positive_int("VISION_TIMEOUT", 150 if timeout is None else timeout)
    max_tokens = _positive_int("VISION_MAX_TOKENS",
                               600 if max_tokens is None else max_tokens)
    if not key:
        raise RuntimeError("未找到视觉模型 API Key：请配置 VISION_API_KEY"
                           "（历史变量 DASHSCOPE_API_KEY 仍兼容，新配置使用 VISION_API_KEY）")
    if not url:
        raise RuntimeError("未配置 VISION_BASE_URL；不会使用默认第三方端点")
    if not model:
        raise RuntimeError("未配置 VISION_MODEL")
    from photo_store import MAX_PHOTO_BYTES, clean_image_bytes
    with open(img_path, "rb") as file:
        data = file.read(MAX_PHOTO_BYTES + 1)
    if not image_sanitized:
        data = clean_image_bytes(data)
    if len(data) > MAX_PHOTO_BYTES:
        raise RuntimeError("图片超过上传大小上限")
    b64 = base64.b64encode(data).decode()
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": [
            {"type": "image_url",
             "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
            {"type": "text", "text": prompt},
        ]}],
        "max_tokens": max_tokens,
    }
    if temperature is not None:
        try:
            temperature = float(temperature)
        except (TypeError, ValueError) as error:
            raise RuntimeError("VISION_TEMPERATURE 必须是有限数值") from error
        if not math.isfinite(temperature):
            raise RuntimeError("VISION_TEMPERATURE 必须是有限数值")
        payload["temperature"] = temperature
    started = time.monotonic()
    try:
        data = fetch_json(url, payload=payload, api_key=key, timeout=timeout)
    except HTTPStatusError as error:
        message = f"vision API HTTP {error.status}: {error.body}"
        if error.status in (401, 403):
            message += "；请检查 VISION_API_KEY 与厂商权限"
        elif error.status == 404:
            message += "；请检查 VISION_BASE_URL 与 VISION_MODEL"
        elif error.status == 429:
            message += "；模型限流，请稍后重试或降低请求频率"
        elif 400 <= error.status < 500:
            message += ("；排查提示：请检查端点、模型名和请求参数"
                        "（temperature / max_tokens）；必要时核对 VISION_API_KEY")
        raise RuntimeError(message) from error
    except RuntimeError as error:
        raise RuntimeError(f"vision API request failed: {error}") from error
    content, choice, message = _message_content(data)
    if choice.get("finish_reason") == "length":
        print(f"{WARN_PREFIX} 响应 finish_reason='length'：输出可能被截断；"
              "如需完整输出请提高 VISION_MAX_TOKENS（默认 600）", file=sys.stderr)
    if not content.strip():
        print(f"{WARN_PREFIX} 响应 content 为空/纯空白：思考型模型可能吃满额度；"
              "建议提高 VISION_MAX_TOKENS，并检查 reasoning_content"
              f"（本响应 message 键：{sorted(message.keys())}）", file=sys.stderr)
    return round(time.monotonic() - started), content

def _without_think(text):
    return re.sub(r"<think\b[^>]*>.*?</think\s*>", "", text,
                  flags=re.IGNORECASE | re.DOTALL)


def _json_object(text):
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            value, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise ValueError("未找到完整 JSON 对象")


def extract_json(text):
    if not isinstance(text, str):
        raise ValueError("模型输出必须是字符串")
    text = _without_think(text)
    for candidate in re.findall(r"```(?:json)?\s*(.*?)```", text,
                                flags=re.IGNORECASE | re.DOTALL):
        try:
            return _json_object(candidate)
        except ValueError:
            pass
    return _json_object(text)


def normalize_classify(text):
    if not isinstance(text, str):
        return "其他"
    text = _without_think(text)
    hits = [name for name in sorted(PROMPTS, key=len, reverse=True)
            if re.search(r"(?<![\u4e00-\u9fff])" + re.escape(name)
                         + r"(?![\u4e00-\u9fff])", text)]
    return hits[0] if len(hits) == 1 else "其他"


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) < 2:
        print(USAGE, file=sys.stderr)
        sys.exit(2)
    mode, img = argv[0], argv[1]
    if mode == "classify":
        config = _load_config()
        config["timeout"] = 60
        _, out = call(img, "这张照片属于哪个类别？选项：舌面/舌底/头面部/眼部/耳部/手掌/皮肤/其他。只输出一个词。", **config)
        first = normalize_classify(out)
        if first == "其他" and "其他" not in out:
            print(f"[warn] classify 输出 {out.strip()[:60]!r} 无法唯一识别，回退为 '其他'",
                  file=sys.stderr)
        print(first)
    elif mode == "observe":
        if len(argv) < 3:
            print(USAGE, file=sys.stderr)
            sys.exit(2)
        part = argv[2]
        if part not in PROMPTS:
            print(f"[warn] observe 收到未知部位 {part!r}，回退为 '其他'"
                  f"（可用类别：{'/'.join(PROMPTS)}）", file=sys.stderr)
        config = _load_config()
        dt, out = call(img, PROMPTS.get(part, PROMPTS["其他"]), **config)
        try:
            extract_json(out)
        except ValueError:
            print(f"{WARN_PREFIX} observe 输出未找到完整 JSON 对象，"
                  "下游解析可能失败；"
                  f"输出前 60 字符：{out.strip()[:60]!r}", file=sys.stderr)
        print(f"[{dt}s] {out}")
    else:
        print(f"未知 mode: {mode!r}\n{USAGE}", file=sys.stderr)
        sys.exit(2)

if __name__ == "__main__":
    sys.exit(main())
