#!/usr/bin/env python3
"""望诊识图统一入口 — Qwen3.8-Max (DashScope OpenAI 兼容)
用法:
  python3 vision_qwen.py classify <img>          # 2a 部位分类
  python3 vision_qwen.py observe <img> <prompt>  # 2b 详细观察 (prompt 从 prompt_map 选)
"""
import base64, json, os, sys, time, urllib.request

def load_key():
    # 环境变量优先，其次读常见 .env 位置（不随仓库分发）
    for p in [os.path.expanduser("~/.hermes/profiles/tcm-tongue/.env"),
              os.path.expanduser("~/.hermes/.env")]:
        try:
            for line in open(p):
                line = line.strip()
                if line.startswith("DASHSCOPE_API_KEY="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
        except FileNotFoundError:
            pass
    return os.environ.get("DASHSCOPE_API_KEY", "")

MODEL = "qwen3.8-max"
URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"

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
    assert key, "DASHSCOPE_API_KEY not found"
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
