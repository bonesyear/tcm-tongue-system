#!/usr/bin/env python3
"""望诊识图统一入口 — Qwen3.8-Max (DashScope OpenAI 兼容)
用法:
  python3 vision_qwen.py classify <img>              # 2a 部位分类
  python3 vision_qwen.py observe <img> <part-key>    # 2b 详细观察 (part-key 从 prompt_map 选)
"""
import base64, json, os, sys, time, urllib.request

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
    "舌面": "这是一张舌面照片，请精确观察并只输出JSON：舌质颜色、舌苔(颜色/厚薄/润燥/腻腐/剥落)、舌体(胖瘦/齿痕/裂纹/点刺)。注意区分舌面中央的浅沟是生理性正中沟还是深宽病理裂纹。",
    "舌底": "观察舌下络脉。正常基线：浅蓝紫细条<2mm平直。仅深紫+粗大>2mm+蛇形弯曲才标异常。只输出JSON：颜色/粗细/走行判断(正常/边缘/异常)。",
    "头面部": "观察并只输出JSON：面色(淡白/萎黄/红赤/晦暗/黧黑/青灰)、唇色唇润燥、面部浮肿。",
    "眼部": "观察并只输出JSON：白睛颜色、目赤(无/轻/重)、巩膜黄染(无/轻/重)、眼睑浮肿。",
    "耳部": "观察并只输出JSON：耳色、润枯、耳道分泌物。",
    "手掌": "观察并只输出JSON：掌色(淡白/红/暗红/紫暗)、甲床颜色(淡白/红润/暗紫)、甲床形态(光滑/粗糙/甲错)。",
    "皮肤": "观察并只输出JSON：肤色(正常/萎黄/黄如橘皮/黄如烟熏)、甲错、水肿、皮肤干燥程度。",
    "其他": "描述这张照片的望诊相关特征，输出JSON。",
}

def call(img_path, prompt, timeout=150):
    key = load_key()
    assert key, "VISION_API_KEY or DASHSCOPE_API_KEY not found"
    b64 = base64.b64encode(open(img_path, "rb").read()).decode()
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
            {"type": "text", "text": prompt},
        ]}],
        "max_tokens": 600,
    }
    req = urllib.request.Request(URL, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read().decode())
    msg = data["choices"][0]["message"]
    return round(time.time() - t0), msg.get("content", "")

if __name__ == "__main__":
    mode = sys.argv[1]
    img = sys.argv[2]
    if mode == "classify":
        dt, out = call(img, "这张照片属于哪个类别？选项：舌面/舌底/头面部/眼部/耳部/手掌/皮肤/其他。只输出一个词。", timeout=60)
        print(out.strip())
    elif mode == "observe":
        part = sys.argv[3]
        prompt = PROMPTS.get(part, PROMPTS["其他"])
        dt, out = call(img, prompt)
        print(f"[{dt}s] {out}")
