# Hermes v0.21.3 能力核查（2026-09-17）

> 起因：核查「主模型 `deepseek-flash` 在 Hermes 三表未收录」这一遗留项是否仍然成立。
> 结论：**该遗留项已自动消除**（Hermes 升级后收录），并顺带实测了主模型的原生视觉能力。

## 一、版本现状

| 项 | 值 |
|---|---|
| Hermes Agent | **v0.21.3**（2026.9.14），upstream `948e9706` |
| 安装方式 | git（`/usr/local/lib/hermes-agent`） |
| 主模型 | `deepseek-flash`（provider `deepseek`，见 profile `config.yaml`） |
| 识图模型 | `dashscope/qwen3.8-max`（`auxiliary.vision`，text 模式链路） |

**说明**：先前记录的「Hermes 0.20.6 三表未收录 `deepseek-flash`」是升级前状态，现已过时。

## 二、三表收录实测（源码证据）

| 表 | 位置 | 内容 |
|---|---|---|
| 推理超时 | `agent/reasoning_timeouts.py:25` | `"deepseek-r1", "deepseek-reasoner", "deepseek-flash", "deepseek-v4-flash", "deepseek-v4.1-flash", "deepseek-v4-pro"`；注释明确 `deepseek-flash` 是 version-less canonical Flash id（2026-09 Flash refresh），`deepseek-v4-flash` 服务端仍别名过来 |
| 模型元数据 | `agent/model_metadata.py:344-349` | `"deepseek-v4.1-flash": 1_000_000, "deepseek-v4-flash": 1_000_000, "deepseek-chat": 1_000_000, "deepseek-reasoner": 1_000_000, "deepseek-flash": 1_000_000, "deepseek": 128000` → **1M 上下文已认** |
| 定价 | `agent/usage_pricing.py:189-193` | `("deepseek-flash", "deepseek-v4-flash", "deepseek-chat", "deepseek-reasoner"): ("0.15", "0.60", "0.003")`，档期标注 `deepseek-pricing-2026-09-10`（off-peak；peak = 2x） |

**结论**：无需打补丁，主模型配置直接可用（推理超时、上下文长度、计费三处均已覆盖）。

## 三、图片输入模式机制（`agent/image_routing.py`）

`decide_image_input_mode(provider, model, cfg)` 的判定顺序（`agent.image_input_mode` = `auto` | `native` | `text`）：

1. 非 `auto` → 直接返回该值（**`native` 是绝对覆盖**）
2. `auto` 且存在**显式 `auxiliary.vision` 后端** → 返回 `text`（即：辅助视觉模型先描述，主模型读文本描述）
3. 否则看 `supports_vision`（配置覆盖或 catalog）→ `native` / `text`

代码注释另指出：`models_dev.py:593` 把 `deepseek-flash` 视为 unknown → **会 fallthrough 到 lossy text**。

**本项目当前状态**：`config.yaml` 设 `image_input_mode: auto` **且**显式配置了 `auxiliary.vision`（qwen3.8-max）→ 走 `text` 模式，与现有「2a 分类 + 2b 观察」链路一致。

## 四、主模型原生视觉实测

### 4.1 能力确认（read-only 探测，使用仓库内的非患者示例图）

用 OpenAI 兼容端点（`https://api.deepseek.com/v1/chat/completions`）发送图像：

| 指标 | 视觉请求 | 纯文本对照 |
|---|---|---|
| `prompt_tokens` | **712** | 36 |
| 模型输出 | reasoning 中描述图像内容 | — |

**关键证据**：模型准确读出**图上的叠加文字**（「舌面照示例」「AI生成」）——这是只有真正解析图像才能得到的信息。

**调参坑**：默认思考模式下输出主要落在 `reasoning_content`；`max_tokens` 偏小时 `content` 会为空（400 token 被思考吃满）。实测 `max_tokens=3000` 时 `content` 正常输出完整 JSON（completion 1210 token，其中 reasoning 1129）。

### 4.2 同图对比（同一张示例图、同一 prompt）

| 维度 | A. Qwen3.8-Max（`vision_client.py`，text 链路） | B. deepseek-flash（native） |
|---|---|---|
| 耗时 | **35 s** | **6 s** |
| 输出格式 | 分层结构化 JSON（含分布、根脚、老嫩） | 完整 JSON，键名严格符合 prompt 约定 |
| 舌色 | 淡红（舌尖及舌边稍红） | 「红」（reasoning 中自述在「淡红/偏红/红」间犹豫） |
| 舌体 | 饱满、略偏胖；未见齿痕 | 适中；无齿痕（一致） |
| 裂纹 | 正中纵行裂沟（自中后部延伸至前部） | 「可见生理性正中沟，非深宽病理裂纹」（更贴合 prompt 的生理/病理区分要求） |
| 舌苔 | 白；中后部厚、细腻稍腻；分布不均；前部近少苔；根脚较紧 | 白；**薄**；润；**无腻**；无剥落 |
| 点刺 | 未见明显点刺 | 舌尖可见少量红点 |

**判读**：两者在**苔厚薄/腻/点刺**上出现实质分歧，但**本次用的是 AI 生成示例图**（图上自带「AI生成」标注），**没有临床真值**，因此**不能据此判定优劣**。

## 五、结论与建议

1. **遗留项关闭**：`deepseek-flash` 三表收录问题已随 Hermes 升级消除，无需任何改动。
2. **原生视觉可用**：主模型确实能读图（图内文字可辨），速度快约 6 倍，输出格式合规；使用时要给足 `max_tokens`（思考模式会占用大量 token）。
3. **识图链路维持现状**：继续以 Qwen 为主（已积累临床判读经验，且「中央沟判生理性」「舌底不过度判读」等已写入 prompt 与规范）。**是否切 native 需要真实舌照的 A/B 对比**，而真实舌照涉及使用者健康数据，须由用户决定是否用于对比。
4. **1M 上下文**：V4 家族元数据标称 1M，长档案/长周报分析可受益（当前未触及瓶颈）。
5. **未启用的其他能力**（备查，未评估）：`image_gen_provider/registry`（图像生成）、`provider_media`（生成物落地缓存）、`native/fts5_cjk`（CJK 全文检索，服务于跨会话召回）、`plugin-catalog/`、`optional-mcps/`、`evals/`。

## 六、本报告的数据纪律

- 实测仅使用仓库内的**非患者示例图**（`docs/images/tongue_surface.jpg`）。
- API key 仅在进程内存中使用，未写入报告、未打印。
- 未修改任何 Hermes 配置（`image_input_mode` 保持 `auto`）。
