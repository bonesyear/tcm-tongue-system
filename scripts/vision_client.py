#!/usr/bin/env python3
"""望诊识图统一入口 — 开放接口（OpenAI 兼容视觉模型，默认 Qwen3.8-Max）
模型/端点/Key 通过环境变量 VISION_MODEL / VISION_BASE_URL / VISION_API_KEY 配置，可插拔任意 OpenAI 兼容服务。
可选请求参数（运行时读取）：VISION_TEMPERATURE（默认不发送该键）/ VISION_MAX_TOKENS（默认 600）/ VISION_TIMEOUT（默认 150，classify 固定 60）。
用法:
  python3 vision_client.py classify <img>              # 2a 部位分类
  python3 vision_client.py observe <img> <part-key>    # 2b 详细观察 (part-key 从 prompt_map 选)
"""
import base64, io, json, os, socket, sys, time, urllib.error, urllib.request

USAGE = ("用法: vision_client.py classify <img> | "
         "vision_client.py observe <img> <part-key>")

# 可观测性告警统一前缀（便于 grep 与日志分流）；仅失败/异常/弃用配置路径输出，正常路径零告警
WARN_PREFIX = "[vision_client][warn]"

# 历史兼容 key 变量：作者早期环境用 DashScope，该变量名永久保留为回退
# （与 src/record.py 的 _A_VISION_KEYS 同风格：新名优先、旧名读时兼容、不迁移）。
# 新配置一律用 VISION_API_KEY；使用其他厂商/本地模型的读者无需关心本常量。
_LEGACY_KEY_NAMES = ("DASHSCOPE_API_KEY",)

# 弃用提示去重状态：同一进程内每个变量名最多提示一次（高频调用
# pipeline 不被同一提示刷屏；新进程重新提示，不会因去重永久沉默）。
_legacy_warned: set = set()


def _reset_legacy_warn_state():
    """清空弃用提示去重状态（测试钩子：保证用例独立、与执行顺序无关）。"""
    _legacy_warned.clear()


def _warn_legacy_key(name):
    """历史兼容 key 变量被实际使用时打一条 stderr 弃用提示（不影响功能）。

    模块级 once 去重：每进程每名只提示一次；测试用 _reset_legacy_warn_state()
    显式重置，避免进程级状态在 pytest 单进程内造成用例间顺序依赖。
    """
    if name in _legacy_warned:
        return
    _legacy_warned.add(name)
    print(f"{WARN_PREFIX} 正在使用历史兼容变量 {name} 提供 API Key——功能正常，"
          f"但该变量仅为兼容保留，建议迁移到 VISION_API_KEY", file=sys.stderr)


def _read_env_text(p):
    """读 .env 为文本。正常按 UTF-8 严格解码（不依赖平台默认编码——中文
    Windows 默认 GBK，读含中文注释的 UTF-8 .env 会 UnicodeDecodeError 崩掉
    load_key）；含非 UTF-8 字节时不静默吞掉：降级为替换字符（U+FFFD）并
    在 stderr 打一条可行动告警（哪个文件、哪一字节、建议转 UTF-8）。
    stdout JSON 契约与退出码不受影响（告警只走 stderr）。"""
    with open(p, "rb") as f:
        raw = f.read()
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as e:
        print(f"{WARN_PREFIX} 读取 {p} 发生非 UTF-8 解码失败（{e}）——"
              f"已按替换字符（U+FFFD）继续处理；该文件可能由其他编码（如 GBK）保存，"
              f"建议转为 UTF-8", file=sys.stderr)
        return raw.decode("utf-8", errors="replace")


def load_key():
    # 优先级: 环境变量 VISION_API_KEY > 环境变量历史兼容名 > .env VISION_API_KEY > .env 历史兼容名
    env_key = os.environ.get("VISION_API_KEY", "")
    if env_key:
        return env_key
    for name in _LEGACY_KEY_NAMES:
        env_key = os.environ.get(name, "")
        if env_key:
            _warn_legacy_key(name)
            return env_key
    keys = {}
    # 本地 .env 候选清单：前两条为通用部署路径（当前工作目录 / XDG 配置目录）；
    # 后两条为作者环境便利（存在则加载，不存在则跳过，对使用者无影响）。
    # 通用部署建议用环境变量或项目根 .env。
    for p in [".env",
              os.path.expanduser("~/.config/tcm-tongue/.env"),
              os.path.expanduser("~/.hermes/profiles/tcm-tongue/.env"),
              os.path.expanduser("~/.hermes/.env")]:
        try:
            # StringIO(newline=None) 迭代与文本文件逐行迭代同语义
            # （\n / \r\n / \r 均分行；默认 newline='\n' 不分 lone \r）。
            for line in io.StringIO(_read_env_text(p), newline=None):
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
    key = keys.get("VISION_API_KEY")
    if key:
        return key
    for name in _LEGACY_KEY_NAMES:
        key = keys.get(name, "")
        if key:
            _warn_legacy_key(name)
            return key
    return ""

# 默认模型/端点仅为示例（clone 后不配置也能看到完整结构；README 与
# .env.example 已标注「请务必替换」）——实际使用请通过 VISION_MODEL /
# VISION_BASE_URL 换成你自己的模型与端点。
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

def call(img_path, prompt, timeout=None):
    timeout = timeout or int(os.environ.get("VISION_TIMEOUT", "150"))
    key = load_key()
    if not key:
        raise RuntimeError("未找到视觉模型 API Key：请配置 VISION_API_KEY"
                           "（环境变量或 .env 均可；历史变量 DASHSCOPE_API_KEY"
                           " 仍兼容，但新配置一律用 VISION_API_KEY）")
    with open(img_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": [
            {"type": "image_url",
             "image_url": {"url": f"data:{mime_type(img_path)};base64,{b64}"}},
            {"type": "text", "text": prompt},
        ]}],
        "max_tokens": int(os.environ.get("VISION_MAX_TOKENS", "600")),
    }
    # temperature 仅在显式配置 VISION_TEMPERATURE 时发送；否则由服务端模型默认值生效。
    temperature = os.environ.get("VISION_TEMPERATURE", "").strip()
    if temperature:
        payload["temperature"] = float(temperature)
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
        msg = f"vision API HTTP {e.code}: {body}"
        if 400 <= e.code < 500:
            # 4xx 通用排查提示（厂商中立，不断言任何一家的具体行为）
            msg += ("；排查提示：请检查凭证（VISION_API_KEY）是否有效、端点地址"
                    "（VISION_BASE_URL）是否正确、模型名（VISION_MODEL）是否存在，"
                    "以及请求参数取值（如 temperature / max_tokens）是否被服务端拒绝")
        raise RuntimeError(msg) from e
    except (urllib.error.URLError, socket.timeout, TimeoutError) as e:
        raise RuntimeError(f"vision API request failed: {e}") from e
    except json.JSONDecodeError as e:
        raise RuntimeError(f"vision API returned invalid JSON: {e}") from e
    choices = data.get("choices")
    if not choices:
        raise RuntimeError(f"vision API response missing choices: {str(data)[:200]}")
    msg = choices[0].get("message", {})
    content = msg.get("content") or ""
    # ② 截断告警：finish_reason=length 表示输出达到上限，JSON 可能不完整
    if choices[0].get("finish_reason") == "length":
        print(f"{WARN_PREFIX} 响应 finish_reason='length'：输出已达 max_tokens 上限、"
              f"可能被截断（JSON 可能不完整）；如需完整输出请提高 VISION_MAX_TOKENS"
              f"（默认 600）", file=sys.stderr)
    # ① 空 content 告警：思考型模型的思考过程可能吃满额度导致正文为空
    if not content.strip():
        print(f"{WARN_PREFIX} 响应 content 为空/纯空白：若使用思考型（reasoning）模型，"
              f"其思考过程可能吃满 max_tokens 额度导致正文未输出——建议提高 "
              f"VISION_MAX_TOKENS（默认 600 对思考型模型偏小）；并检查响应是否含 "
              f"reasoning_content 字段（本响应 message 键：{sorted(msg.keys())}）",
              file=sys.stderr)
    return round(time.time() - t0), content

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
        # ③ 非 JSON 告警：去掉首尾空白与可能的 ```json 围栏后，输出应以 '{' 开头
        candidate = out.strip()
        if candidate.startswith("```"):
            candidate = candidate.split("\n", 1)[1] if "\n" in candidate else ""
            candidate = candidate.rsplit("```", 1)[0].strip()
        if not candidate.startswith("{"):
            print(f"{WARN_PREFIX} observe 输出未以 '{{' 开头（已去空白与 ``` 围栏），"
                  f"该模型可能未遵守「只输出 JSON」约定，下游解析可能失败；"
                  f"输出前 60 字符：{out.strip()[:60]!r}", file=sys.stderr)
        print(f"[{dt}s] {out}")
    else:
        print(f"未知 mode: {mode!r}\n{USAGE}", file=sys.stderr)
        sys.exit(2)

if __name__ == "__main__":
    sys.exit(main())
