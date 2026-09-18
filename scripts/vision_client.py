#!/usr/bin/env python3
"""望诊识图统一入口 — 开放接口（OpenAI 兼容视觉模型，默认 Qwen3.8-Max）
模型/端点/Key 通过环境变量 VISION_MODEL / VISION_BASE_URL / VISION_API_KEY 配置，可插拔任意 OpenAI 兼容服务。
用法:
  python3 vision_client.py classify <img>              # 2a 部位分类
  python3 vision_client.py observe <img> <part-key>    # 2b 详细观察 (part-key 从 prompt_map 选)
"""
import base64, json, os, socket, sys, time, urllib.error, urllib.request

USAGE = ("用法: vision_client.py classify <img> | "
         "vision_client.py observe <img> <part-key>")

def load_key():
    # 优先级: 环境变量 VISION_API_KEY > .env VISION_API_KEY > 环境变量 DASHSCOPE_API_KEY > .env DASHSCOPE_API_KEY
    env_key = os.environ.get("VISION_API_KEY", "") or os.environ.get("DASHSCOPE_API_KEY", "")
    if env_key:
        return env_key
    keys = {}
    for p in [os.path.expanduser("~/.hermes/profiles/tcm-tongue/.env"),
              os.path.expanduser("~/.hermes/.env")]:
        try:
            with open(p) as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    k = k.strip()
                    v = v.split("#", 1)[0].strip().strip('"').strip("'")
                    if k not in keys and v:
                        keys[k] = v
        except FileNotFoundError:
            pass
    return keys.get("VISION_API_KEY") or keys.get("DASHSCOPE_API_KEY", "")

MODEL = os.environ.get("VISION_MODEL", "qwen3.8-max")
URL = os.environ.get("VISION_BASE_URL",
                     "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions")

PROMPTS = {
    "舌面": "这是一张舌面照片，请精确观察并只输出JSON：舌质颜色、舌苔(颜色/厚薄/润燥/腻腐/剥落)、舌体(胖瘦/齿痕/裂纹/点刺)、舌质润燥(键名固定为\"舌质润燥\"，值只填一个词：润泽/偏干/干燥/干裂)。舌苔腻腐只填规范词：无/微腻/稍腻/偏腻/腻/厚腻/腐苔。舌体胖瘦只填规范词：正常/适中、偏胖、胖大、偏瘦、瘦小（必要时可填肿胀）；若观察到复合描述（如\"胖嫩\"\"瘦薄\"），只按胖瘦成分填写（胖嫩→偏胖，瘦薄→偏瘦），老嫩/厚薄成分不进该字段。齿痕只填规范词：无/轻度/中度/重度（不填\"明显齿痕\"\"舌缘可见\"等描述性短语）。点刺：输出两个键——\"点刺\"与\"点刺依据\"。先观察舌尖与舌边是否有明显凸起的红色颗粒，在\"点刺依据\"里一句话说明凸起程度与分布；\"点刺\"只填结论：确信有则填\"点刺\"或\"芒刺\"，无则填\"无\"，存疑（看不清是否凸起）时填\"不明显\"。注意区分舌面中央的浅沟是生理性正中沟还是深宽病理裂纹。不判舌神/荣枯（照片光线干扰、静态不可判）。",
    "舌底": "观察舌下络脉。正常基线：浅蓝紫细条<2mm平直。仅深紫+粗大>2mm+蛇形弯曲才标异常。只输出JSON：颜色/粗细/走行判断(正常/边缘/异常)。",
    "头面部": "观察并只输出JSON：面色(淡白/萎黄/红赤/晦暗/黧黑/青灰)、唇色唇润燥、面部浮肿。",
    "眼部": "观察并只输出JSON：白睛颜色、目赤(无/轻/重)、巩膜黄染(无/轻/重)、眼睑浮肿。",
    "耳部": "观察并只输出JSON：耳色、润枯、耳道分泌物。",
    "手掌": "观察并只输出JSON：掌色(淡白/红/暗红/紫暗)、甲床颜色(淡白/红润/暗紫)、甲床形态(光滑/粗糙/甲错)。",
    "皮肤": "观察并只输出JSON：肤色(正常/萎黄/黄如橘皮/黄如烟熏)、甲错、水肿、皮肤干燥程度。",
    "其他": "描述这张照片的望诊相关特征，输出JSON。",
}

MIME_MAP = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}

def mime_type(img_path):
    """按扩展名映射 MIME，未知回退 image/jpeg。"""
    return MIME_MAP.get(os.path.splitext(img_path)[1].lower(), "image/jpeg")

def call(img_path, prompt, timeout=150):
    key = load_key()
    if not key:
        raise RuntimeError("VISION_API_KEY or DASHSCOPE_API_KEY not found "
                           "(环境变量与 .env 均未配置)")
    with open(img_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": [
            {"type": "image_url",
             "image_url": {"url": f"data:{mime_type(img_path)};base64,{b64}"}},
            {"type": "text", "text": prompt},
        ]}],
        "max_tokens": 600,
        # 降低采样噪声（贪心解码方向）。收益幅度未定量：2026-09-18 实测
        # n=3 不足以定量，且 temp=0 下仍出过 2 种结果（服务端不确定性），
        # 故不得表述为"解决抖动"。不擅自加 seed/top_p——DashScope 对 VL
        # 模型是否支持未经核实，一次只改一个变量。
        "temperature": 0,
    }
    req = urllib.request.Request(URL, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode(errors="replace")[:200]
        except Exception:
            pass
        raise RuntimeError(f"vision API HTTP {e.code}: {body}") from e
    except (urllib.error.URLError, socket.timeout, TimeoutError) as e:
        raise RuntimeError(f"vision API request failed: {e}") from e
    except json.JSONDecodeError as e:
        raise RuntimeError(f"vision API returned invalid JSON: {e}") from e
    choices = data.get("choices")
    if not choices:
        raise RuntimeError(f"vision API response missing choices: {str(data)[:200]}")
    msg = choices[0].get("message", {})
    return round(time.time() - t0), msg.get("content", "")

def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) < 2:
        print(USAGE, file=sys.stderr)
        sys.exit(2)
    mode, img = argv[0], argv[1]
    if mode == "classify":
        _, out = call(img, "这张照片属于哪个类别？选项：舌面/舌底/头面部/眼部/耳部/手掌/皮肤/其他。只输出一个词。", timeout=60)
        lines = out.strip().splitlines()
        first = lines[0].strip() if lines else ""
        if first not in PROMPTS:
            print(f"[warn] classify 输出 {first!r} 不在已知类别中，回退为 '其他'", file=sys.stderr)
            first = "其他"
        print(first)
    elif mode == "observe":
        if len(argv) < 3:
            print(USAGE, file=sys.stderr)
            sys.exit(2)
        part = argv[2]
        if part not in PROMPTS:
            # 与 classify 分支对齐：无效 part 不得静默回退——调用方拼错
            # 部位名会拿到通用 prompt 却不自知（解析层键名约定随之失效）
            print(f"[warn] observe 收到未知部位 {part!r}，回退为 '其他'"
                  f"（可用类别：{'/'.join(PROMPTS)}）", file=sys.stderr)
        prompt = PROMPTS.get(part, PROMPTS["其他"])
        dt, out = call(img, prompt)
        print(f"[{dt}s] {out}")
    else:
        print(f"未知 mode: {mode!r}\n{USAGE}", file=sys.stderr)
        sys.exit(2)

if __name__ == "__main__":
    sys.exit(main())
