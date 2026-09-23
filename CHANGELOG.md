# 更新日志

## v1.4.14（Windows 兼容修复：.env 显式 UTF-8 读取 + grep 路径正斜杠统一，2026-09-23）

> 修两处可移植性问题：① `load_key` 读 .env 原依赖平台默认编码，中文 Windows 默认 GBK，读含中文注释的 UTF-8 .env 会 `UnicodeDecodeError` 崩掉整个 key 加载；② `os.path.relpath` 在 Windows 返回反斜杠，命中路径与按 "/" 比较的消费者（含测试断言）跨平台不一致。**stdout JSON 契约、退出码、检索返回结构均不变**。

### 改动

- `scripts/vision_client.py` `load_key`：.env 读取改为「读原始 bytes → 严格 UTF-8 解码」，不再依赖平台默认编码；含非 UTF-8 字节时不静默吞掉——解码失败才降级为替换字符（U+FFFD）并在 stderr 打一条可行动告警（哪个文件、哪一字节失败、建议转 UTF-8），正常路径零告警、stdout 契约不变。
- `src/retrieval/grep_search.py` `_relpath`：命中路径统一为正斜杠（`.replace(os.sep, "/")`），消除 Windows 下返回反斜杠的跨平台不一致；跨盘符 `ValueError` 仍原样返回传入路径，不抛异常。
- README「跑测试」注释不再写死测试数量（数字会随开发腐烂），只保留「跑全部测试确认环境 OK」的意图。

### 测试

- 290 → **294 项**：vision_client +2（含中文注释的 UTF-8 .env 不崩溃且取到 key、并钉住「读取不得依赖平台默认编码」；非 UTF-8 字节 stderr 告警且 key 仍取到）；grep +2（模拟 `os.sep` 为反斜杠时 `_relpath` 统一正斜杠、跨盘符 `ValueError` 走 except 原样返回不抛异常）。fixture 均为纯合成内容。

## v1.4.13（词表覆盖校验 docstring 补充：封闭词表含 0 分基线词的语义说明，2026-09-19）

> 同日另完成作者环境的 API Key 配置迁移（`VISION_API_KEY` 追加、旧变量保留，消除弃用提示）——属作者本地环境操作，文件在仓库外，不入库。**本版仓库内改动仅 docstring 一处：不改任何逻辑、文案与判据，`score()` 语义与评分词表分值不变**。

### 改动

- `scripts/input_validator.py` `_validate_scoring_vocab_coverage` docstring 补三段说明：
  - 规范词清单是「合法写法全集」（全量封闭词表），不是「推荐值」——含 0 分基线词（如齿痕「无:0」、body_color「淡红:0」）；
  - 为何不过滤 0 分词条：清单会退化为「纯异常词表」、诱导填报异常值，此类假阳性发生在数据源头、评分层无法检测，与「不给不可靠数据建展示位」纪律冲突；
  - 未来若做「分组标注」展示，标签应写「基线词」而非「正常词」（0 分词不全是常态，如舌下「淡紫:0」属生理性、苔色「白:0」属色基）。

## v1.4.12（弃用提示进程级 once 去重 + 词表外告警文案两分支化，2026-09-19）

> 解决 v1.4.11 报告遗留的两处「不确定处」：① 词表外告警的良性噪声是否需要豁免/分级；② 旧变量弃用提示在每次调用时重复输出。**`score()` 公开语义、评分词表分值、通过/失败判定全部不变**。

### 问题 ①：词表外告警噪声 —— 经评估不豁免、不分级，仅优化文案

- **豁免词表（逐词维护）否决**：「同义正常描述」表由谁维护、何时更新无答案；模型每次换版本都可能产出新措辞，表只在漏维护时静默失效——恰好在本检查要防的「静默」上失败；且表项过宽会吞掉真阳性。
- **告警分级（按词表是否含 0 分词条区分措辞轻重）否决——被词表数据证伪**：实测两条良性告警中，`face_luster` 词表含显式正常词（`荣润: 0`）✓ 但 `sclera_color` 词表无 0 分词条（会被继续重措辞、过度惊吓）✗；而真阳性 `tooth_marks: 舌缘可见` 的词表恰含 `无: 0`（会被错误轻措辞、弱化漏判警示）✗。「词表是否收 0 分词条」与「值是良性还是漏判」不相关，分级信号无效。
- **实施（文案两分支化）**：告警在保留「该指标将被静默按 0 分（正常）计入评分与红线推断」核心事实（一字未弱化）之后，改为明确的处置分支——「若确为正常描述，0 分即正确结果，可忽略本告警；若意在描述异常表现，则属模型措辞问题而非数据错误，请改用规范词（清单），否则异常将被静默漏判」。库无法可靠区分两种情形，就把判断规则直接交给使用者；良性告警不再以「请改用规范词」打头造成过度惊吓。

### 问题 ②：旧变量弃用提示 —— 模块级 once 去重

- `vision_client.py` 新增模块级 `_legacy_warned` 集合：同一进程内每个变量名最多提示一次（高频调用 pipeline 不刷屏；新进程重新提示，不会因去重永久沉默）。
- 新增显式重置钩子 `_reset_legacy_warn_state()`；`tests/test_vision_client.py` 加 autouse fixture 在每个用例前后清空去重状态——否则 pytest 单进程内「先触发旧变量路径的用例」会吞掉后续用例的 stderr 提示，造成隐藏的顺序依赖。

### 测试

- 288 → **290 项**：vision_client +2（同进程重复调用只提示一次、重置钩子恢复提示）；validator 既有文案测试补三分支断言（静默事实保留/可忽略分支/漏判后果）。
- **顺序无关性验证**：新增去重测试与既有弃用提示测试以两种相反顺序同进程连跑（均绿）、三个相关用例各自单独跑（新进程，均绿）、全量 290 绿——去重状态不引入任何执行顺序依赖。

## v1.4.11（两处遗留修正：key 报错厂商中立化 + 词表外措辞从静默归零变为可告警，2026-09-18）

> ① `DASHSCOPE_API_KEY` 厂商专属回退的报错文案误导使用其他厂商/本地模型的读者；② 最早排查列为「最严重三处」之一的评分盲区——模型用词表外措辞（如「偏胖」写成「较丰满」）→ 词表匹配不到 → 静默按 0 分（正常）计入评分与红线推断，使用者永远无法察觉。本轮两处都只加「可观测性」：**`score()` 公开语义、评分词表分值、通过/失败判定全部不变**。

### 改动

- **问题 A（`scripts/vision_client.py`）**：
  - 旧变量 `DASHSCOPE_API_KEY` 收进模块级兼容层常量 `_LEGACY_KEY_NAMES`（与 `src/record.py` 的 `_A_VISION_KEYS` 同风格：新名优先、旧名读时兼容、不迁移），注释标明「历史兼容，新配置一律用 `VISION_API_KEY`」。**回退链完整保留**（环境变量与 `.env` 两条路径都兼容）——作者环境零回归。
  - 缺 key 报错文案厂商中立化：「未找到视觉模型 API Key：请配置 `VISION_API_KEY`（环境变量或 .env 均可；历史变量 `DASHSCOPE_API_KEY` 仍兼容，但新配置一律用 `VISION_API_KEY`）」——旧变量只以兼容说明的身份出现，不再与主变量并列误导。
  - 旧变量被**实际使用**时打一条 `[vision_client][warn]` stderr 弃用提示（引导作者环境迁移；功能不受影响）。
  - 默认模型/端点（`qwen3.8-max` + DashScope URL）按既定决策**保留不改**，仅补注释再强调「仅为示例，请替换」；`.env.example` 与 README「配置自己的视觉模型」各补一句旧变量兼容说明。
- **问题 B（`src/scoring.py` + `scripts/input_validator.py`）**：
  - `scoring.py` 新增 `match_keyword(rules, text) -> Optional[str]`：与评分完全同一套判据（精确匹配 → 最长未否定子串，含双向否定守卫）的命中查询，`_match_score` 改为委托它——**单一事实来源**，校验器不与评分层漂移；`score()` / `score_indicators()` 语义与返回值逐字节不变（纯重构）。
  - `input_validator.py` 新增 `_validate_scoring_vocab_coverage`（独立函数，与「判读注记」等卫生检查职责分开；同挂 warning 通道，**不改通过/失败判定**）：封闭词表指标（`DIMENSION_RULES` 收录者）的值未命中词表任何词条时告警，文案给出维度/指标/值/后果（静默 0 分）/规范词清单，并明确「通常是模型措辞问题而非数据错误」。
  - **保守豁免**（宁可漏报不可刷屏）：空值跳过；命中词表跳过；值含正常/否定语义标记（无/未/没/不/正常/阴性/生理性/非病理）豁免——词表只收异常词与显式基线词，正常描述本就不入词表；已被判读注记检查告警的值不重复告警。自由文本指标（body_luster / body_dynamics / coating_distribution / prickles / palm_temp / lip_around / nose_color / nose_bleeding 等无词表者）不适用。

### 实测（12 份真实档案）

- **返回码改动前后逐一零差异**；warning 条数仅 06-25 由 0 → 3：
  - `tooth_marks: '舌缘可见'` —— **真阳性**（齿痕可见但程度未填，静默 0 分；prompt 本就禁止该写法）；
  - `face_luster: '有光泽'`、`sclera_color: '色白，散在红血丝'` —— 良性告警（评分 0 本就正确，提示改用规范词）。
- 08-28 / 09-18 的 24 处「未拍摄（用户声明正常）」占位全部被豁免，无刷屏；判据无需收窄。

### 测试

- 270 → **288 项**：vision_client +4（旧变量 env/.env 两路径兼容 + 弃用提示、新名优先无告警、报错文案厂商中立）；scoring +4（`match_keyword` 精确/最长/否定/空值与 `_match_score` 委托等价）；validator +10（词表外告警文案要素、「较丰满」动机示例、词表内不告警、5 类正常/否定豁免参数化、注记值不重复告警、自由文本指标不检查）。

## v1.4.10（形状探测 footgun 堵上另一半：未识别形状从静默变为 stderr 可诊断，2026-09-18）

> 批次 2（v1.4.x，`5cae1f7`）把形状 A 容器键中性化为 `vision_analysis` 并加了旧名读时兼容层——堵住了「品牌名诱导改名」，但**没堵住「使用者执意用第三个名字」**：若容器键改成 `my_model_analysis` 之类，三判据全不中，静默落入 `else` 按形状 B 处理 → 六维覆盖 0/6 → 推断 LOW → 禁方剂 + 大量告警，且无任何报错指向键名，排查极困难。

### 改动

- **`src/record.py` 形状探测 `else` 分支**（三判据全不中时）：打一条 stderr 提示——说明判定结果（按形状 B 处理、六维观测将为空）、**列出本记录实际顶层键名**（使用者自定义的键名因此可直接被认出）、并指明正确键名 `vision_analysis`（旧名 `doubao_vision_analysis` 仍兼容）。定位与批 4 的 `[vision_client][warn]` 一致：**仅 stderr、不改退出码、不改 stdout 契约、不改解析行为**（`else` 分支仍判为 B）。
- **文案设计原则：不猜使用者意图**。库无法猜出任意自定义键名，所以不做自动修复、不做启发式识别；只把「失败可诊断」做实——提示里回显实际顶层键清单，使用者对照一眼即知自己的键名不在判据内。

### 未改动

- 形状判定结果逐字节不变（A/B/C 正常判定**零 stderr 噪音**）；`score()` / 评分层不动；历史档案不迁移。
- 回归验证：12 份真实档案（`records/daily/*_analysis.json`）逐一跑 `input_validator.py`，**返回码与改动前零差异**；其中 4 份（07-09/07-10/07-15/07-15_b）此前即静默落入 `else` 分支（容器键为 `photo_analysis` 等），本次改动让这些历史静默点首次在 stderr 可见——这正是本改动的预期效果。

### 测试

- `tests/test_record.py` 新增 2 例：① 三判据全不中（自定义键名 `my_model_analysis`）→ 打 stderr 提示、提示含正确键名与实际顶层键名、形状仍为 B、观测为空；② 正常形状 A（新旧名）/B/C 判定不产生任何 stderr 噪音。全套 270 passed。

## v1.4.9（README 隐私声明精确化：消除与识图脚本联网行为的字面冲突，2026-09-18）

> 公开仓库的读者是陌生人，会据此决定要不要放敏感的健康照片 —— **准确性优先于听起来更强的承诺**。本次**零代码改动**，只把声明修到与代码一致。

### 改动（README「隐私与数据」段）

- **`:197` 标题句精确化**：主语从「本库」收窄为「**本项目方**」。原句「本库不上传任何用户数据」的通常理解是「运行这套代码不会让数据离开本机」，而 `vision_client.py` 恰恰会向云端发送照片与 prompt —— 字面冲突真实存在。新句明确「不接收你的任何数据 / 不向项目方或任何第三方回传」，并如实说明**数据离开本机的唯一条件**（你主动配置并使用了云端视觉/语言模型）。**承诺强度不减反增**。
- **`:199` + `:200` 合并为一条**（原两条互相打脸）：原 `:200` 写「本库只处理数据，**不调 LLM、不传图片**」，但 `vision_client.py` 就是本库代码且明确传图，无法局部修补；两条本在讲同一件事的两面（库内发生什么 / 库外 Agent 发生什么），合并后读者读一条即建立完整心智模型。
- **补上默认端点披露**：`vision_client.py:47/49` 硬编码默认模型与端点（`qwen3.8-max` + DashScope 兼容端点）—— 只配 key 不配 URL 时照片会发往该默认端点。原「**仅**向你自行配置的端点」表述过强，现明确标注「默认配置仅作示例，可整体替换为任意 OpenAI 兼容服务，**包括本地部署的模型**」。
- **`:204` 主语同步**为「本项目方」，与 `:197` 一致。

### 未改动

- **代码零改动**（纯文档）；`:195` 适用范围限定、`:201` 备份排除、`:202` 使用者责任均不变。
- 全文自洽性已复核：README 其余位置（`:102`/`:116`/`:186`/`:189`）与 `docs/user-guide.md` **无其他**与「会向云端发送照片」冲突的绝对化表述。

## v1.4.8（校验器判读注记词表补全，2026-09-18）

> 档案写法铁律禁止在值里写模型名/判读注记；校验器的告警词表此前只覆盖部分模型名，换用其他模型后该类注记会漏报。

### 改动

- **`scripts/input_validator.py`**：`_ANNOTATION_WORD_RE` 一次补全主流视觉模型名 —— 在原 `豆包|Qwen|K3|用户确认|误判` 基础上加入 `DeepSeek|Kimi|GPT|Claude|Gemini`。风格与既有条目一致（仍为单条 `|` 分隔正则）；判据仍为「值含括号 **且** 括号内出现模型名或判读词」的保守组合，正常括号描述不误报。
- **`tests/test_input_validator.py`**（新增）：参数化 8 个模型名（DeepSeek/豆包/Qwen/K3/Kimi/GPT/Claude/Gemini）断言触发「判读注记」warning；另设**负例**——「淡红（晨起自然光下拍摄）」等正常括号描述**不得**误报。

## v1.4.7（视觉客户端可观测性：四类失败从静默变为 stderr 可见可行动，2026-09-18）

> 空 content / 输出截断 / 非 JSON 输出 / HTTP 4xx 四类失败此前静默或仅有裸状态码；本批统一以 `[vision_client][warn]` 前缀输出 stderr 告警（4xx 为异常消息内追加排查提示）。**不改退出码、不改 stdout 契约**（下游脚本按行读 stdout），正常路径零告警。

### 改动

- **`scripts/vision_client.py` 新增统一告警前缀常量 `WARN_PREFIX = "[vision_client][warn]"`**，所有新告警共用，便于 grep 与日志分流。
- **告警① 空 content**（响应解析段）：`choices[0].message.content` 为空/纯空白时告警——提示思考型（reasoning）模型的思考过程可能吃满 `VISION_MAX_TOKENS` 额度导致正文未输出（默认 600 对思考型模型偏小，建议提高），并提示检查响应是否含 `reasoning_content` 字段（附本响应 message 键清单）。`content` 为 `null` 时归一为空串返回（原样返回 `None` 会让调用方在 `.strip()` 处崩出 `AttributeError`）。
- **告警② 输出截断**（响应解析段）：`choices[0].finish_reason == "length"` 时告警——输出已达 max_tokens 上限、可能被截断（JSON 可能不完整），建议提高 `VISION_MAX_TOKENS`。
- **告警③ 非 JSON 输出**（observe 分支）：模型输出去掉首尾空白与可能的 ` ```json ` 围栏后不以 `{` 开头时告警——该模型可能未遵守「只输出 JSON」约定，下游解析可能失败（附输出前 60 字符）；stdout 照常打印原文，契约不变。
- **告警④ HTTP 4xx 排查提示**（HTTP 错误段）：4xx 时 `RuntimeError` 消息追加通用排查提示——检查凭证（`VISION_API_KEY`）、端点地址（`VISION_BASE_URL`）、模型名（`VISION_MODEL`）与请求参数取值（temperature / max_tokens）是否被服务端拒绝；**厂商中立，不断言任何一家的具体行为**。5xx 不追加。

### 测试

- 255 → **259 项**：新增 4 个 mock 测试（每类告警一个）——① 空 content 告警含 `VISION_MAX_TOKENS` 与 `reasoning_content` 提示；② `finish_reason=length` 告警（同测试内先断言正常 `stop` 路径 `err == ""`）；③ observe 非 JSON 输出告警且 stdout 逐字节不变；④ HTTP 400 消息含排查提示、500 不含。

## v1.4.6（视觉模型请求参数环境变量化 + 本地 .env 候选路径泛化，2026-09-18）

> 请求参数从写死改为环境变量驱动，作者环境行为保持等价（不传 `temperature` ≡ 服务端默认值生效，官方文档已证实、本批实测复核）。

### 改动

- **`scripts/vision_client.py` 请求参数环境变量化**（三个变量均在 `call()` 内运行时读取，不做模块级常量）：`max_tokens` 改从 `VISION_MAX_TOKENS` 读（默认 600）；`temperature` 仅当 `VISION_TEMPERATURE` 非空时发送（未设置或空串 → payload 完全不含该键，由服务端模型默认值生效）；`call(..., timeout=None)` 生效值 = `timeout or int(os.environ.get("VISION_TIMEOUT", "150"))`（classify 显式传 60 不变）。原 Qwen 专属 temperature 论证注释整段删除，替换为一行中性说明（论据已迁入 `.env.example` / README / CHANGELOG v1.4.3）。key 回退链、MIME 回退、错误处理结构未动。
- **本地 `.env` 候选路径泛化**（`load_key()`）：候选序列改为 当前工作目录 `.env` → `~/.config/tcm-tongue/.env` → 原有两条作者便利路径（`~/.hermes/profiles/tcm-tongue/.env`、`~/.hermes/.env`，保留不移除）；注释注明后两条为作者环境便利、通用部署建议用环境变量或项目根 `.env`。
- **默认值标注**：`.env.example` 与 README「配置自己的视觉模型」明确标注——代码默认值（`qwen3.8-max` + DashScope 端点）仅为示例（clone 后不配置也能看到结构），请务必替换为自己的模型与端点；代码默认值本身未改。
- **`scripts/hooks/README.md`**：凭证指纹层的 `.env` 路径描述泛化为「作者环境的多个 `.env` 路径（实际清单见 `pre-push` 顶部常量）」；`pre-push` 脚本实际路径未动（hook 必须真能读到凭证才能比对指纹）。

### 测试

- 253 → **255 项**：删除 `test_call_payload_temperature`（原断言 `temperature == 0.6`），新增 3 个——① 默认 payload 不含 `temperature` 键 + `max_tokens == 600` + 无 `seed`/`top_p`；② 设 `VISION_TEMPERATURE` 后出现该键；③ `VISION_MAX_TOKENS` 生效覆盖默认值。新增 autouse fixture 清除运行环境残留的 `VISION_TEMPERATURE` / `VISION_MAX_TOKENS` / `VISION_TIMEOUT`；`load_key` 相关测试补 `chdir` 隔离相对路径 `.env` 候选。
- 作者环境实测：`unset` 三个变量后 classify/observe 与批 0 基线模式类别一致、JSON 结构一致、无新 stderr；`VISION_MAX_TOKENS=8000` 与 `VISION_TEMPERATURE=0.6` 各跑一次 observe 均正常返回。

## v1.4.5（形状 A 键名中性化 + 读时兼容层，2026-09-18）

> 形状 A 的两个品牌键改名（`doubao_vision_analysis`→`vision_analysis`、`deepseek_diagnosis`→`diagnosis`），代码层新旧双名双收、**新名优先**。消除「用户自行改名导致形状探测静默塌缩」的 footgun；历史档案**零迁移**、可继续校验——旧名永久兼容（读时双收即满足「历史不追溯」原则），新记录一律用新名。纯解析层改动，`score()` / `compute_dimension_deviation()` 公开语义与双门槛逻辑未动。

### 改动

- **`src/record.py` 读时兼容层**：新增模块级常量 `_A_VISION_KEYS = ("vision_analysis", "doubao_vision_analysis")` / `_A_DIAGNOSIS_KEYS = ("diagnosis", "deepseek_diagnosis")` 与助手 `_first_present()`（按序取第一个存在的顶层键）；形状 A 探测、`_dimension_root`、`get_pattern_differentiation`、`get_formula` 四处改走兼容层；相关注释与 docstring 同步注明「旧名永久兼容，新记录一律用新名」。
- **`scripts/input_validator.py`**：`_DICT_FIELDS` 追加 `vision_analysis` / `diagnosis`（旧名保留——历史档案仍需类型校验）。
- **模板与 prompt**：`templates/multi_dim_record_template.json` 两键改新名；`templates/adaptive_analysis_prompt.md` 三处 `doubao_analysis` → `vision_analysis`（prompt 的 User Message 键与记录文件键统一为同一个名，消除批 1 留下的文件内自相矛盾）。
- **知识库**：`smartphone-visual-diagnostics.md` 开头「Doubao Vision」→「视觉模型」（活文档与模板同级处置，不按历史存档冻结）。
- **README**：① 修「接入你的 Agent」第 1 步的事实性错误——原让新用户把 `adaptive_analysis_prompt.md` 当作 Vision 模型的 system prompt，但该文件实为第 4 步辨证 LLM 的 prompt（输出 Markdown 报告，非结构化 JSON）；第 1 步改指 `scripts/vision_client.py`（内置封闭词表 prompt 的推荐入口）。② 五步后新增「记录形状说明」小段：三种形状（A 模板中文键 / B `observations` 英文键 / C 顶层维度键）；`multi_dim_record_template.json` 定位为形状 A 的完整 schema 存档参考，**新用户日常记录推荐形状 B**。既有隐私声明段未触碰。

### 测试

- 252 → **253 项**：新增 `test_shape_a_new_key_wins_when_both_present`（同一记录同时含新旧两键时取新名，钉死「新名优先」规则）；`test_shape_a_template_compatibility` 重命名为 `test_shape_a_legacy_key_compat`（旧名固件保留）；6 处 `doubao_vision_analysis` 与 3 处 `deepseek_diagnosis` 测试固件改新名；`tests/test_weekly_report.py` 的旧名固件保留（一个固件同时覆盖两条兼容路径 + 周报链路）。
- 旧名固件与新名固件各跑一次 `input_validator.py`，均识别为形状 A 且无新增 error；`records/daily/` 现存 12 份档案逐一回归，与批 0 基线零差异。

## v1.4.4（视觉模型可移植性·文档与配置模板，2026-09-18）

> 纯文档批次，零代码改动。目标：让非作者用户仅靠仓库文档即可完成视觉模型配置，并修掉全部已确认的文档漂移。

### 改动

- **新增 `.env.example`**：视觉模型配置模板（`VISION_MODEL` / `VISION_BASE_URL` / `VISION_API_KEY` 必填三件套 + `VISION_TEMPERATURE` / `VISION_MAX_TOKENS` / `VISION_TIMEOUT` 可选项），全部占位符、不含任何真实凭证；注释内嵌「设 0 ≠ 确定性输出（部分模型有官方下限、被服务端静默改写）」与「思考型模型建议 `VISION_MAX_TOKENS≥8000`」两条关键提示。
- **README 新增「配置自己的视觉模型」章节**：变量表 + 换模型五步 checklist + 「换模型必须重新标定」声明（prompt 封闭词表与 `src/scoring.py` 评分词表逐键对齐，词表外措辞会被评分层**静默读作 0 分 = 正常**）。
- **README 两处声明修正**：设计原则「LLM 无关」限定为「**框架层** LLM 无关」（`src/` 不绑定 provider；`vision_client.py` 按用户配置的端点发起调用）；隐私声明「本库不发起任何网络请求」修正为「`src/` 框架层不发起请求；`scripts/vision_client.py` 仅向用户自行配置的 `VISION_BASE_URL` 发送照片与 prompt」。
- **文档抗漂移**：`docs/user-guide.md` 头部不再写死版本号与模型名，改为引用 `VERSION` / `CHANGELOG.md` / `.env.example` 单一事实源；README 顶部版本号同样改为引用 `VERSION`；`templates/adaptive_analysis_prompt.md` 去掉「Doubao 视觉模型」模型名，改为「视觉模型（OpenAI 兼容，可插拔）」。
- **版本统一（4 处漂移）**：`VERSION`（1.3.4）、CHANGELOG 顶部（v1.4.3）、`README.md` 顶部（v1.4.0）、`docs/user-guide.md` 头部（v1.3.3）原四处不一致；本版统一为 **1.4.4**（README 与 user-guide 改为引用 `VERSION`，今后不再随版本迭代漂移）。

### 测试

- 无新增/无修改（纯文档）；全量 pytest 与 v1.4.3 基线一致（252 项全绿）。

## v1.4.3（识图采样稳定性处置：温度真相查明（视觉理解下限 0.6）+ 点刺退出评分层 + prompt 安全阀 + 腻腐封闭词表，2026-09-18）

> 依据：同日 Qwen3.8-Max 采样稳定性实验（同一张真实舌照，三组各 3 次，共 9 次调用）——点刺 **9/9 判「有」** 而用户肉眼为「无」；temperature=0 下腻腐仍抖（3 次出 2 种结果）。
> ⚠️ **温度框架更正（同日查明）**：DashScope 官方文档（`qwen-api-via-dashscope`）明确 qwen3.8-max（思考模式）**视觉理解 temperature 默认 0.6、0.6 以下被服务端静默改为 0.6**——本版本涉及的所有「temp=0」条件实际生效值均为 0.6，与不传参等价；上述「temp=0 下仍抖」是**默认温度下的基线抖动观测**（仍真实），不构成「温度干预失败」的证据。实验 1（同图 temp=0 vs temp=1.0 各 10 次交叉交替）实测两组无可辨差异（双侧 Fisher p≈0.21/0.47 不显著）。

### 改动

- **请求 payload 温度显式化：`temperature: 0` → `0.6`**（`scripts/vision_client.py`）：官方文档（DashScope「qwen-api-via-dashscope」）明确 qwen3.8-max（思考模式）**视觉理解 temperature 默认 0.6、0.6 以下被服务端静默改为 0.6**——最初落地的 `0` 与不传参等价，从未生效；该模型视觉理解的随机性下限即 0.6，**温度无法用于降噪**。显式写 `0.6` 只为如实反映生效值、避免「已降噪」误导，**不得表述为降低/解决抖动**（实验 1：temp=0 vs temp=1.0 各 10 次交叉交替无可辨差异，Fisher p≈0.21/0.47）。未加 `seed`/`top_p`（DashScope 对 VL 模型是否支持未经核实），一次只改一个变量。
- **点刺退出评分层、降级到辨证层**（`src/scoring.py`）：凸起度需触诊/动态观察，静态照片判不准（9/9 实证），违反收录原则「评分层只收静态照片可客观判读的指标」（`scoring.py:139-143`），同 #18 `palm_temp` 先例。`prickles` 从 `DIMENSION_RULES[TONGUE]` 移除；词表 `TONGUE_PRICKLES_MAP` 保留备查（含轮次 11 `少量: 2` 兜底语义）。**档案 `prickles` 字段（用户肉眼值）继续保留供辨证层使用，只是不参与数值评分**；观测层（`record.py` 指标路径）不动。`score()` / `compute_dimension_deviation()` 公开语义与双门槛判定逻辑未动。
- **舌面 prompt 点刺恢复安全阀**（`scripts/vision_client.py`）：v1.4.2 的规范化句「不填『不明显』等」拆掉了模型存疑时的对冲出口，使系统性偏向直接落成 5 分假阳性。现改为：输出 `点刺` 与 `点刺依据` 两个键——先判断是否有明显凸起的红色颗粒并给出凸起度/分布依据；确信有填「点刺」/「芒刺」，无填「无」，**存疑填「不明显」**（评分层自然归零，恢复出口安全；与 #6 的 `少量: 2` 兜底不冲突）。
- **舌面 prompt 腻腐封闭词表**（`scripts/vision_client.py`）：腻腐只填 无/微腻/稍腻/偏腻/腻/厚腻/腐苔，异常档与 `TONGUE_COATING_GREASY_MAP` 键完全对齐——只保证「评分映射确定」，**不承诺消除判断层面抖动**（本次腻腐抖动是 无/腻 级别的判断摇摆，非措辞问题）。
- **「需用户肉眼确认」清单**（`docs/user-guide.md` §八）：点刺与腻腐并列列入，附原因与肉眼判断难度（腻苔肉眼易判）；腻腐**不降级**——它是静态可判的形态学体征，与点刺（凸起度静态不可判）区别对待。

### ⚠️ 结构变化提示

- 舌诊评分维度少一项（`prickles` 退出）：**历史偏离度不可直接比较**（参照 #17 历史不追溯原则，历史档案数值不追溯修改）。实测：fixture 舌诊 detail 由 `{score: 5.5, max: 7.0, n: 4}` 变为 `{score: 5.7, max: 7.0, n: 3}`；`records/daily/2026-09-18` 舌诊偏离度 3.5 不变（点刺本就为 0）；`records/daily/2026-08-28` 重算为 5.2（n=6，点刺 5 分退出分母）。

### 文档论据修正

- `docs/HERMES_021_CAPABILITY_CHECK_2026-09-17.md` §8.2/8.3 + 新增 §8.6：9-17 A/B「Qwen 点刺判对」标注为**少数采样命中**（同图 9/9 实测证伪）；「Qwen 判读质量更优」论据**撤回（证据不足）**（四分歧项 native 有 2 项更接近签认值）；「维持 Qwen 为识图主力」结论方向保留，立足点改为运营性理由（prompt 已按 Qwen 调校 / 不扩大隐私面 / 切换收益约 30s 每次）。
- `records/daily/2026-09-18_analysis.json` `ab_test_note`：同步修正（档案 `prickles: "无"` 用户肉眼签认值不动；validator 0 错误 0 警告）。
- `docs/KNOWN_ISSUES.md` #5：由「点刺判读不稳定」扩展为「抖动 + 系统性偏向」，补入 9/9 实测、规范化句拆安全阀的核心洞察、d+b 处置与腻腐连带处置；§0 总览表与 §5 坑表同步更新。后续（同日）再补**温度真相**：temp=0 被服务端钳制到 0.6、从未生效，点刺 10/10 判有与采样温度无关。

### 测试

- 251 → **252 项**：`test_prickles_scoring` / `test_prickles_shaoliang_conservative` 重写为「已退出评分注册表」+「词表保留 `_match_score` 行为不变」两组断言；新增 `test_call_payload_temperature`（payload 显式 temperature=0.6、无 seed/top_p）；周报 fixture 舌诊期望值同步为 5.7/7.0/3。

## v1.4.2（点刺「少量」漏判修复：词表兜底 + prompt 规范化，2026-09-18）

### 修复

- **`TONGUE_PRICKLES_MAP` 收 `少量: 2`**（`src/scoring.py`）：修复 KNOWN_ISSUES #6——06-25 真实档案点刺值「少量」MISS 落 0。2 分为保守档（远低于点刺 5/芒刺 6），符合该表「分辨率敏感 → 分值保守」的既定口径；既有 `点刺: 5` / `芒刺: 6` 不变。实测：「少量点刺」同长平局取高 → 5（方向正确），「无点刺」「点刺不明显」否定守卫仍归零，无跨字段串扰。
- **舌面 prompt 点刺规范化**（`scripts/vision_client.py`，根本解法）：点刺字段只填规范词（无/点刺/芒刺），不填「少量」「散在」「不明显」等描述性短语——与齿痕规范化对称；既有 5 条 prompt 约定（「舌质润燥」键名单值、胖瘦规范词、齿痕规范词、正中沟/病理裂纹区分、不判舌神/荣枯）逐项保留。

### 影响说明

- 本地档案 `records/daily/2026-06-25_analysis.json`（gitignored，未修改）的 `prickles=少量` 得分由 0 → 2，下次生成该周周报时点刺信号恢复（轻量保守分）。
- 测试 fixture `2026-06-25_analysis.json` 的点刺值为「舌尖散在点刺」（命中点刺 5），周报舌诊 detail 期望 `score 5.5 / max 7.0 / n 4` 不变。

## v1.4.1（周报 detail 字段改名 + 趋势措辞修正，2026-09-18）

### 修复

- **`dimension_deviation_detail` 键 `mean` → `score`**（`scripts/generate_weekly_report.py`）：该值取 `score_dimension(...)`，非舌维度实为「各指标之和封顶 10」而非均值（实测手诊出现 `mean 4.0 > max 2.0` 的数学矛盾），键名与 `score()` / `score_dimension` 对齐。数值不变，仅改名。
- **`describe_trend` 新增 `metric_name` 参数**（默认 `"均值"`，旧调用逐字不变）：五个非舌维度（`_dim_trend`）传 `"累计分"`，降幅中性文案由「头面诊偏离度均值较周初降低…」改为「头面诊偏离度累计分较周初降低…」——不再把 sum 说成「均值」。舌诊摘要「舌诊综合偏离度均值…」逐字保留（舌诊该值确为 sparse 均值）。双门槛判定逻辑未动。

### ⚠️ 口径变更提示

- 周报 JSON 的 `dimension_deviation_detail.<维度>.first/last` 内键 **`mean` 更名为 `score`**（**结构变化**，值不变）；仓库外无消费者，如有自研下游请同步改键名。
- 非舌维度趋势文案量纲称呼由「均值」改为「累计分」（仅措辞，判定口径不变）。

## v1.4.0（形状 C 档案规范 + 评分与周报修复，2026-09-17）

> 本轮共 20 次提交（含文档入档），测试 159 → **232 项**。两项核心变化：① 新增**档案形状 C**（顶层规范维度键），使解析层对真实产出重新生效；② 评分覆盖扩展 + 周报「无观测」语义修正。

### 新功能

- **档案形状 C（`src/record.py`）**：顶层使用规范英文维度键（`tongue` / `head_face` / `eye` / `ear` / `hand` / `skin`）+ 维度内使用规范指标名（`body_color` / `coating_peeling` / `sublingual_thickness` …）的档案，现可被完整解析（实测维度覆盖 **0/6 → 6/6**）。形状检测优先级 B > A > C > 默认 B；兼容维度别名 `face`→`head_face`、`palm`→`hand`（规范键优先）；`get_inquiry_coverage` 支持扁平 `{问题: 回答}` 计数；新增骨架模板 `templates/daily_record_shape_c_template.json` 与脱敏样例 `tests/fixtures/shape_c_sample.json`。
- **评分覆盖扩展（`src/scoring.py`）**：新增 7 个指标的评分规则（0 = 正常基线，越高越异常）——
  - `coating_peeling`：剥落 6 / 剥脱 6 / 花剥 6 / 地图舌 7 / 镜面 9
  - `coating_greasy`：稍腻 3 / 腻 5 / 厚腻 8 / 腐苔 7
  - `coating_color`：白 0 / 黄 3 / 灰 6 / 黑 7 / 灰黑 8
  - `prickles`：点刺 5 / 芒刺 6
  - `sublingual_color`：淡紫 0 / 紫暗 6 / 青紫 8
  - `sublingual_thickness`：增粗 5 / 怒张 7
  - `sublingual_petechiae`：复用瘀斑表
  并补 `body_color` 词条 `"红润": 0`（原靠单字「红」命中误报 7 分）。纳入原则：**评分层只收静态照片可客观判读的指标**（需动态观察者如 `body_dynamics` 排除）。
- **雷达图 9 轴**：新增「舌苔剥落」轴；轴集合改为从 `TONGUE_RADAR_METRIC_KEYS` 单一来源取（消除硬编码 8 轴假设）。
- **周报评分多维输出**：新增 `dimension_deviation_detail`（每维度 first/last 各含 `mean` / `max` / `n`）；摘要呈现「均值 X（最重单项 Y 分，共 N 项异常）」。

### 修复

**辨证与评分层**

- 否定词表移除「非」——「非典型黄染」不再被误否定漏报；同时补入真否定「并非 / 绝非」以避免反向敞口。
- `_match_score` 平局规则改为**同长度取分值最高者**（fail-loud）——「湿润偏滑」原被「润 = 0」掩盖得 0 分，现正确命中「滑 = 7」。
- `has_formula_content` 增加兜底扫描（剂量模式 `\d+[g克]` + 27 个经方名白名单），键名漂移不再漏检。
- `get_pattern_differentiation` 形状 A 缺键时返回 `{}`（原返回整个 diag，污染辨证结果）。
- `confidence.parse_level` 英文词边界严格化（`HIGH1` / `HIGH_2` 不再误判为 HIGH）。
- `danger_flags` 宽松真值判定（字符串 `"true"` / `"yes"` / 数值 `1` 均可触发），修复 fail-open。
- `score()` 非舌诊维度返回值类型统一为 float（原 int，JSON 中出现 `0` 与 `0.0` 并列）。

**方案 A：舌质「润燥」降级**

- `body_luster` 移出评分层（照片光线干扰、静态照片不可判舌神/荣枯），辨证层保留；形状 A 路径键 `舌质荣枯` → `舌质润燥`；删除死代码 `TONGUE_BODY_LUSTER_MAP`。

**周报「无观测」语义**

- 维度级与逐指标级 `n = 0` 不再显示 0.0 → 「本周无有效观测（未拍到或未解析到有分指标）」；雷达图对全无观测的日期**跳过绘制**并提示（原会画出「完美居中的多边形」，视觉上等同于「一切正常」）。
- 摘要与下周建议在全维度无观测时不再输出偏离度排名，也不再误报「偏离度总体较低，建议维持现状」；逐指标判据采用 `get_observation` 文本非空（区分「正常 0」与「无数据」）。
- `describe_trend` 增加**双门槛**：仅当最重单项下降 ≥ 0.5 且异常项数不增时，才判定「异常程度减轻」（防止新增轻度异常稀释均值被读成好转）。

**周报档案选择**

- 新增 `_select_daily_file` 三级规则：精确 `{date}_analysis.json` 优先 → 排除 `.bak` / `copy` / `tmp` / `_旧格式` 候选后取 mtime 最新 → 多份候选打印警告。修正原「取字典序最新」静默选中副本的问题（实测 2026-07-15 曾读错 `_b` 副本而丢弃正档）。

**vision_client.py**

- 文件句柄改用 `with`；HTTP 错误带状态码与响应摘要；JSON 解码失败 / 超时 / 缺 `choices` 统一转 `RuntimeError`；运行时校验由 `assert` 改为显式错误（`python -O` 下不再失效）；参数不足或未知模式退出码 2；MIME 类型映射（png/jpg/jpeg/webp，回退 jpeg）；`classify` 未知类别回退「其他」并告警；`observe` 无效部位告警（原静默回退）。

**图表**

- CJK 字体候选补入 `Noto Sans CJK JP`（Linux 的 Noto `.ttc` 常只注册 JP 名，原候选 `Noto Sans CJK SC` 匹配不到，会落到缺 ASCII 字形的 `Droid Sans Fallback`）+ 字体回退链 → 图上字母 / 数字 / 破折号不再显示为方块（实测渲染警告 25 → 0）。

### 测试

- 159 → **232 项**：新增 `tests/test_vision_client.py`（20 项，全 mock 免网络）、`tests/test_record_shape_c.py`（12 项）；周报 / 评分 / 记录层补充约 40 项，含「正常路径逐字不变」的兼容性钉子与「代价侧」反例（如「有观测且 0 分」的逐字兼容、`并非 / 绝非` 真否定）。

### 文档

- 新增 5 份模型复核 / 分析报告：`docs/K3_REVIEW_2026-09-17.md`、`docs/K3_POST_R2_AUDIT_2026-09-17.md`、`docs/K3_SCORING_ADVICE_2026-09-17.md`、`docs/K3_SCORING_METRIC_ADVICE_2026-09-17.md`、`docs/K3_NO_OBSERVATION_ANALYSIS_2026-09-17.md`。
- `docs/REPAIR_PLAN_2026-08-25.md` 更新执行进度（形状 C 与轮次 1–5 全部完成，含逐轮实测数据与遗留清单）。

### ⚠️ 口径变更提示

- 评分覆盖扩展（新增 7 个指标进入分母）使维度偏离度均值与历史数值**不可直接纵向比较**（如 2026-08-28 舌诊 6.0 → 5.3）。周报现同时给出 `max`（最重单项）与 `n`（异常项数）以补足负荷信息；均值口径本身含义为「已发现异常的平均烈度」，非异常负荷。

## v1.3.5（隐私声明与代码整理，2026-08-28）

### 文档
- README 新增「隐私与数据」章节：明确**程序本身不收集/不上传/不传输任何用户数据**（无遥测、无统计上报、无回传）；照片与记录仅存本地；网络调用仅发生于使用者自配置的外层 Agent（自备 API key）；OSS 备份脚本默认排除健康数据与版权全文。

### 代码整理
- `scripts/vision_qwen.py` → **`scripts/vision_client.py`**：开放接口更名（模型/端点/Key 由环境变量 `VISION_MODEL`/`VISION_BASE_URL`/`VISION_API_KEY` 配置，可插拔任意 OpenAI 兼容视觉服务，默认 Qwen3.8-Max）
- vision_client.py 增量修复：`load_key()` 合并重复循环、跳过注释行、处理行内注释；assert 提示文案更新；docstring 参数名修正
- 代码卫生：清理 6 处未使用 import（ruff F401）+ 15 处空白行尾随空格（W293）

### 审查与规划（待执行）
- Kimi 代码审查报告归档 `docs/CODE_REVIEW_2026-08-25_KIMI.md`（18 条问题 + 增量确认 + 决策记录）
- 修改执行规划归档 `docs/REPAIR_PLAN_2026-08-25.md`（3 轮次 14 条 + "干燥/润泽"方案 A 落地清单）

## v1.3.4（许可与合规，2026-07-12）

- 新增 `LICENSE`（GNU GPL v3）
- README 新增"许可"章节
- 移除文档中对版权著作的明确引用（README、knowledge_base/README.md）

## v1.3.3（全面审查修复，2026-07-12）

> 依据 `docs/CODE_REVIEW_2026-07-12.md` 审查报告（13 项 Bug + 8 项安全/合规风险 +
> 8 项优化建议），经用户确认后全量执行；随后经 62 智能体多视角对抗验证，
> 确认的 16 条残留问题亦全部修复。测试从 131 项增至 **159 项**，
> 首次在非部署机（macOS）上全绿。

### P0 修复
- **Bug 1/3 可移植性**：新增 `src/paths.py` 集中路径配置（仓库根推导 +
  `TCM_DATA_ROOT` 环境变量覆盖）；`generate_weekly_report.py` 目录创建移入
  `main()`（import 零副作用）；`draw_hand_diagram.py` 输出路径仓库相对化 +
  跨平台 CJK 字体候选列表；`backup_to_oss.sh` 路径/哈希命令（md5sum↔shasum）
  可移植化。测试 fixture 改为入库的脱敏样例 `tests/fixtures/2026-06-25_analysis.json`
  （原依赖被 .gitignore 排除的真实记录，新环境克隆后测试必挂）。
- **Bug 2 包结构**：`src/` 成为常规包（新增 `__init__.py`，内部改相对导入）；
  README 快速开始的 `from src.record import DailyRecord` 现在真实可用；
  修正示例中不存在的 `parse(date_str=)` 参数与 `covered_dimensions()` 方法。
  测试/脚本统一为 `from src.xxx import ...` 风格。
- **Bug 4 评分基线归零**：`淡红 5→0`、`润 5→0`（正常表现一律 0 分，与
  薄白/荣润/适中对齐）。修复"完全正常舌象得 5.0 分踩关注线"、"记录正常
  发现反而抬高偏离度"两个语义矛盾。⚠️ **口径变更**：历史周报的舌诊偏离度
  数值与新口径不可直接纵向对比。
- **Bug 5 否定守卫重构**：否定词集 `{无,不}` 扩为 `{无,不,未,没,非}`
  （"非常"经负向前瞻排除），回看窗口 3 字→6 字，且以标点为界只在同一
  小句内生效。修复"未见明显浮肿""没有黄染""无明显的浮肿"三类假阳性；
  新增 `不温=4` 枚举（原被否定守卫抹成 0 分）。
- **Bug 6 检索层资源**：TF-IDF 后端由 numpy 稠密矩阵（605 MB，峰值 RSS
  1.28 GB）重写为纯 Python 倒排索引（峰值 RSS 85 MB，零依赖）；dispatcher
  按 kb_root 缓存 RagSearch 实例（原每次低命中查询重建索引 ~0.4s，现缓存
  命中 ~1ms）。RAG 兜底不再依赖 numpy，`is_available()` 恒为 True。
- **Bug 7 安全边界执法**：validator 中 "LOW 置信度输出方剂" 由警告升级为
  **严重错误（退出码 1）**；周报摘要显式标注安全边界警示（不再只打 stderr）。

### P1 修复
- **Bug 8**：`confidence.parse_level` 支持中文（高/高度/高度确信 等），
  英文前缀匹配加词边界（"HIGHEST" 不再误判为 HIGH）。
- **Bug 9**：`DailyRecord._as_dimension` 未知维度名抛 `ValueError`，
  不再静默回落到舌诊。
- **Bug 10**：周报同日多份记录改为取字典序最新（原 glob 顺序不确定）。
- **Bug 11**：补齐 `body_dynamics`（舌体动态）与 `nose_bleeding`（鼻衄）
  指标映射，模板↔Record 对齐，字段不再被静默丢弃；模板鼻域新增"鼻衄"。
- **Bug 12**：周报 `week_id` 改用 ISO 周（`%G-W%V`，原 `%Y-%U` 周日起算
  且跨年错位）。
- **Bug 13**：validator 严重度分级理顺——结构缺失=error、取值可疑=warning，
  文案与退出码一致。
- 潜在崩溃修复：validator/周报对无法解析的自报置信度先 `parse_level` 拦截，
  不再把垃圾值直接传给 `allows_formula`（原会抛 `ValueError`）。
- 周报图表新增 matplotlib CJK 字体自动配置（macOS/Linux 候选列表），
  修复非部署机上图表中文全为方框。

### 安全与合规
- **风险 A（健康隐私）**：备份脚本排除全部 `records/`（含周报）与 `charts/`
  ——个人健康数据不再上传 OSS。
- **风险 B（版权）**：全文 `jingfang_tanyuan_full.md` 从备份
  与版本库排除（.gitignore），仅本地保留供检索；knowledge_base/README
  增加版权说明。
- **风险 C（ReDoS）**：`search()/search_and()` 接受原始正则的安全边界在
  模块 docstring 与 README 显式标注；不受信输入一律走 `retrieve()`。
- **风险 D**：备份临时文件改用 `mktemp` + trap 清理（原 /tmp 固定路径）。
- **风险 F（提示注入）**：`adaptive_analysis_prompt.md` §7.2 新增第 7 条
  "数据与指令隔离"规则。
- **风险 G**：user-guide.html 移除 Google Fonts 外链（不再向第三方发请求）。
- **风险 H**：requirements.txt 注明 PyYAML 可选策略；新增 requirements-dev.txt
  （pytest）。

### 对抗验证第二轮修复（62 智能体多视角验证，16 条确认发现全部修复）
- **安全 fail-open 闭环**（validator + 周报，1 条 critical + 3 条 major）：
  - `parse_level` 补齐 "低置信度/高置信度/中等" 等高频中文写法与
    "HIGH置信度" 中英混排（原 CJK 字符被 isalpha() 误判为英文后缀）；
    纯空白串返回 None（原抛 IndexError，违反自身契约）。
  - "LOW 禁方剂"检查改为以【自报等级与覆盖度推断等级中更严格者】执行——
    原实现不自报 confidence、或自报无法解析的值即可绕过铁律。
  - 方剂内容判定改用新增的 `record.has_formula_content()`：无方名但携带
    药材+剂量（ingredients/核心药组/剂量建议等键）同样算方剂；
    formula 为非 dict 文本时原样保留供判定（结构异常不放行）。
  - danger_flags 类型错误升级为 error：形状 B 的 triggered 非列表、
    形状 A 的 triggered 非布尔都会让红线状态被静默"清零"显示
    "✅ 无触发"，现一律退出码 1。
- **评分守卫两处盲区**（major）：`_match_score` 改为检查关键词的
  **全部出现位置**（原只查首位："舌质不红，但舌边红" 中第二个真阳性
  "红" 被吞，漏报异常）；新增后置否定短语守卫（"浮肿不明显/黄染未见/
  阴性" 原计满分）。
- **检索**（major）：`TCM_KB_ROOT` 环境变量现对 RAG 兜底同样生效
  （原仅 grep 读取，设置后 retrieve() 会混合两个知识库的结果）。
- **validator 健壮性**（major）：新增顶层容器类型校验（observations/
  danger_flags/formula 等字段存在但非对象 → error）；顶层 JSON 为数组、
  observations 为字符串等畸形输入现产出 error 报告而非裸 traceback；
  record.py 各访问器对类型错误容器一律按空处理（库层不崩）。
- **周报**（major）：`load_week_records` 排序 key 强制 str()——某条记录
  date 为数值时整周周报崩溃，与容错加载契约相悖。
- **风险 E 补落实**（上轮遗漏）：kb_root/TCM_KB_ROOT "部署配置，不应来自
  用户输入" 的信任边界标注补入 retrieval/__init__.py、grep_search.py、
  README 与 retrieval-design.md。
- 文档一致性：README 知识库行数 10000→9000（实际 9050）、Pillow 依赖
  归属注释修正；retrieval-design.md 补记包结构变更（决策 12 已过时）。

### 文档
- README：版本号、快速开始、模块表（补 `allows_dosage`/`paths`）、目录结构、
  数据目录环境变量说明、测试数 131→159。
- user-guide.md / user-guide.html：版本标注更新。
- knowledge_base/README.md：目录树补齐 `jingfang_tanyuan_full.md` 与
  `synonym_map.yaml`，增加版权与使用范围说明。
- retrieval-design.md：追加 2026-07-12 实现更新记（KB 规模 1752→~10800 行、
  实测延迟、TF-IDF 倒排化、dispatcher 缓存）。
- 版本口径说明：`VERSION` 文件自 v1.3.1 起已改存语义版本（本次同步为
  1.3.3），v1.3.0 changelog 中"VERSION=4 为备份计数器"的表述自此作废。
  **v1.3.1 / v1.3.2 无对应 changelog 条目**——版本号提升时未同步记录，
  内容已不可考，特此注明以消除"CHANGELOG 最新 1.3.0 vs VERSION 1.3.2"
  的矛盾。

---

## v1.3.0（架构深化重构，2026-06-27）

> 依据 `/improve-codebase-architecture` 审查报告，把"望诊记录"这一领域概念
> 从四处各表（模板 / 校验器 / 周报 / 真实 LLM 产出）收敛为四个深 module。
> 核心修复：周报对真实记录（形状 B）不再静默产出全零趋势。

### 新增：四个深 module（`src/`，仅依赖 Python 标准库）
- `src/dimensions.py`：六维望诊规范枚举 `VisionDimension`（舌/头面/目/耳/手/皮肤），
  每维携带中文名、英文名、子域列表与计数规则；提供中↔英双向 adapter。
  消除"head_face vs 头面诊"式拼写漂移（原先中英文重拼 5+ 处）。
- `src/record.py`：`DailyRecord` 拥有"记录形状"，把形状 A（模板/doubao_vision_analysis/中文键）
  与形状 B（真实产出/observations/英文键）的兼容/迁移逻辑藏在 implementation。
  Interface：`parse`、`get_observation(dim)`、`get_pattern_differentiation`、
  `get_formula`、`get_danger_flags`、`get_dimension_coverage`、`get_inquiry_coverage`、`get_confidence`。
- `src/scoring.py`：把定性→定量评分（7 张映射表 + 匹配策略）从 800 行周报脚本抽出。
  Interface：`score(dim, observation) → 0-10`、`score_indicators(dim, observation)`。
  匹配策略：精确匹配优先 → 最长子串匹配（"红如妆"优先于"红"）→ 否定守卫
  （"无明显浮肿"不计分），复用 validator 三级匹配经验。
- `src/confidence.py`：把"覆盖几维→置信度→允许输出什么"安全边界从自然语言变成可执行代码。
  `from_coverage(n)`、`allows_formula(level)`（LOW 禁方剂）、`is_consistent(claimed, n)`、
  `prompt_paragraph()`。

### 重构：消费方退化为 module 的 adapter
- `scripts/input_validator.py`：数据驱动校验，从 Dimension 取规范六维、从 Record 取数据、
  从 Confidence 复核安全边界。对真实记录（形状 B）不再误报"全部必填字段缺失"；
  新增置信度一致性校验与 LOW 禁方剂安全断言。
- `scripts/generate_weekly_report.py`：改用 Record 取数据（代替硬编码 `vision.get("头面诊")`）、
  Dimension 取维度名（代替硬编码中文名 ×48）、Scoring 打分（代替 extract_tongue_metrics
  与 compute_dimension_deviation 内裸逻辑）；周报新增 `confidence_checks` 校验断言。
  评分映射表已全部迁入 Scoring module。

### 测试（从 0 到 41 项，全部通过）
- `tests/test_record.py`：以真实记录 `records/daily/2026-06-25_analysis.json` 为 fixture，
  断言 `get_observation("tongue")` 有内容、`get_formula()` 非空、形状 A↔B 双向兼容、无信息丢失。
- `tests/test_dimensions.py`：6 维 + 中英双向映射 + 计数规则。
- `tests/test_scoring.py`：`score(TONGUE, "舌红苔黄") > 0`；最长匹配消除"红"歧义；
  否定守卫（无明显浮肿/无黄染不误命中）；正常皮肤得 0 分；结构化输入避免跨字段误匹配。
- `tests/test_confidence.py`：`allows_formula(LOW) == False`；覆盖度→等级映射；一致性校验。
- `tests/test_weekly_report.py`：真实记录偏离度非全零（核心 bug 回归）；周报产出有效输出；
  validator 对真实记录无严重错误；LOW+方剂被安全边界检出。

### 已修复的核心 bug
- 周报 `extract_tongue_metrics()` / `compute_dimension_deviation()` 原读 `doubao_vision_analysis`
  （形状 A），真实记录是形状 B → 对真实数据返回全 0，雷达图与趋势线为平线、`records/weekly/` 长期为空。
  经 Record module 形状归一后，真实记录产出非零偏离度（舌诊 2.1 / 头面诊 5 / 目诊 4 / 耳诊 3）。

### 跳过（Speculative，有意不改）
- 候选 5（日报/周报渲染 seam）：日报由 LLM 直产是有意设计，本次不纳入 Python 化。

### 备注
- `VERSION` 文件（=4）是 `backup_to_oss.sh` 的备份清单计数器，非语义版本，与 CHANGELOG
  语义版本是不同概念，保持不动以免破坏备份自增逻辑。语义版本以本 CHANGELOG 为准。

---

## v1.2.2（Claude 修复 3 个残留问题，2026-06-23）

### constitution-types.md 表格结构修复
- 9 个体质判定表格统一为六维结构（舌象/头面诊/目诊/耳诊/手诊/皮肤）
- 唇域描述合并入头面诊行（如"面色萎黄；唇色淡白"）
- 补齐耳诊维度（根据各体质特征填写耳色+耳轮描述）

### 基础套餐定义统一
- user-guide.md：基础套餐 +皮肤照（4张→5张=4维），恢复为 HIGH 置信度
- overlap-analysis.md：基础套餐置信度标注对齐（HIGH）

### overlap-analysis.md 表述修正
- L203：5维→MEDIUM 改为 3维→MEDIUM / 4-6维→HIGH

---

## v1.2.1（OpenCode+Claude 联合审查修复，2026-06-23）

### P0 修复
- **C4** `generate_weekly_report.py`：无苔评分 0→8，薄白改为0(正常基线)。无苔(镜面舌)是阴虚重症，不应被量化为正常。同步调整白厚/黄厚/厚腻评分以拉开区分度。
- **C1** `user-guide.md`：基础套餐 4张=3维=MEDIUM（非4维/HIGH），标题和结论同步修正。
- **C2** `user-guide.md`：最佳组合补上耳部照，从6张→7张，现真正覆盖全部6个维度。
- **C3** `draw_hand_diagram.py`：字体 DejaVuSans→DroidSansFallbackFull（含真正CJK字形）；裸except→except(OSError, IOError)。

### P1 修复
- `user-guide.md`：报告示例中大便同时在已采集和缺失列表中→移除缺失列表中的大便。
- `dimension-overlap-analysis.md`：基础套餐 5维→4维。
- `constitution-types.md`：20处旧维度名：面象→头面诊、唇口→唇域；引言中更新为v1.2.0六维体系。
- `input_validator.py`：`validate_enum_value()` 子串匹配→精确匹配+子串警告+反向子串警告三级。消除"红"误匹配"红如妆"等歧义。

### 审查者
OpenCode/GLM-5.2 (初始审查) + Claude/Kimi K2.7 (独立验证) → 用户决策修改

---

## v1.2.0（六大拍照维度 + 十五项可跳过问诊，2026-06-19）

### 核心架构变更
- **维度体系重构**：从 9 个独立拍照维度重构为 6 个拍照维度 + 15 项可跳过问诊
  - 拍照维度：舌诊(舌面+舌底)、头面诊(面域+唇域+鼻域)、目诊、耳诊、手诊、皮肤诊
  - 问诊项：15 项经典经方六病辨证核心问诊骨架，全部可跳过
  - 移除独立拍照维度：面诊/唇诊/鼻诊 → 合并为头面诊；咽喉诊/形体诊 → 移入问诊
- **置信度阈值调整**：1维→LOW, 2-3维→MEDIUM, 4-6维→HIGH（原 1-2→LOW, 3-4→MEDIUM, 5-9→HIGH）
- **问诊数据独立角色**：不改变置信度等级，仅在等级内提升辨证精度
- **新增核心设计原则**：用户可跳过任何问诊项；一份证据说一分话；拍得到的拍照，拍不到的问诊

### 模板
- multi_dim_record_template.json：完全重写
  - photos：从 9 个字段减至 7 个（tongue_surface/tongue_bottom/head_face/eyes/ears/hands/skin）
  - doubao_vision_analysis：从 10 个维度减至 6 个，头面诊含面域/唇域/鼻域三个子域
  - 新增 inquiry 对象：15 个问诊项，每项含 {asked: bool, answer: str}，全部默认 asked=false
  - danger_flags：保持 9 个标志，throat_erosion 触发条件改为含问诊（咽干+吞咽困难+面目乍赤乍黑）
  - deepseek_diagnosis：新增"因问诊缺失导致的不确定性"字段

### 提示词
- adaptive_analysis_prompt.md：大幅重写
  - §2.1 维度映射表：9维→6维拍照+15项问诊双矩阵
  - 新增 §2.3 问诊数据输入格式
  - §3.1 置信度映射更新：1→LOW, 2-3→MEDIUM, 4-6→HIGH
  - §3.2-3.4 三种置信度辨证流程全面重写，每种都处理问诊数据缺失
  - §3.5 未覆盖维度标准话术更新为6维
  - §4.5 安全红线：咽喉溃烂触发条件改为"咽干+吞咽困难+面目乍赤乍黑→建议就医"
  - 输出格式模板：N/9→N/6，新增"问诊缺失影响标注"模块
  - 示例更新：三种置信度示例均增加问诊数据维度

### 技能
- SKILL.md（tcm-tongue-analysis）：v1.1.0 → v1.2.0
  - Step 2 统一 prompt：部位列表改为7个（舌面/舌底/头面/眼部/耳部/手掌/皮肤），头面包含面唇鼻域描述
  - Step 3 问诊采集：15项列表重排（统一为恶寒→汗出→头痛→口苦→咽干→目眩→口渴→食欲→大便→小便→睡眠→胸胁→腹部→听力→鼻部），标注"用户可跳过任意项"
  - Step 4 证据矩阵：增加问诊数据行
  - Step 5 输出格式：N/7→N/6，增加"因缺少以下问诊信息"标注
  - 置信度表：1→LOW, 2-3→MEDIUM, 4-6→HIGH
  - 安全红线：与 adaptive_analysis_prompt 一致
  - 新增铁律：用户可跳过任何问诊项——不强求

### 知识库
- smartphone-visual-diagnostics.md：完全重写
  - 从 9 个独立维度章节重写为 6 个拍照维度 + 15 项问诊补充
  - 删除鼻部/咽喉/形体独立章节
  - 面诊/唇诊/鼻诊合并为头面诊（含面域/唇域/鼻域子域）
  - 耳诊保留为独立拍照维度（Tier 2）
  - 新增 §二 十五项问诊补充表
- knowledge_base/README.md：更新目录结构，移除计划中列表

### 脚本
- input_validator.py：同步更新全部常量
  - REQUIRED_PHOTO_FIELDS：7 个（tongue_surface/tongue_bottom/head_face/eyes/ears/hands/skin）
  - REQUIRED_VISION_DIMENSIONS：6 个（舌诊/头面诊/目诊/耳诊/手诊/皮肤诊）
  - 新增 REQUIRED_HEAD_FACE_SUBFIELDS（面域/唇域/鼻域子字段）
  - 新增 REQUIRED_INQUIRY_FIELDS（15 项）和 validate_inquiry() 函数
  - REQUIRED_DANGER_FLAGS：9 个（保持，注释更新）
  - 新增 inquiry 覆盖统计输出
  - 移除 THROAT_COLORS 枚举验证
- generate_weekly_report.py：维度名称同步更新
  - 面诊→头面诊（含面域+唇域+鼻域子域评分）
  - 新增耳诊偏离度趋势线
  - 趋势图从 5 条线增至 6 条线

### 模板（其他）
- weekly_report_template.json：trend_analysis 更新维度名称
  - face_trend→head_face_trend，新增 ear_trend
  - 移除 lip_trend/nose_trend/throat_trend/body_trend

### 文档
- user-guide.md：完全重写
  - 标题："九大诊断维度"→"六大拍照维度"
  - 拍照总览表：从 8 行减至 6 行（舌诊/头面诊/目诊/耳诊/手诊/皮肤诊）
  - 拍照指南：头面诊合并面+唇+鼻三域，移除咽喉/形体独立章节，新增耳部照章节（从 Tier 3 提升至正式维度）
  - 新增 §四 十五项问诊（全部可跳过）
  - 套餐推荐：最佳组合从 5 张更新为 6 张
  - 报告示例：N/9→N/6，增加问诊覆盖行
- user-guide.html：从更新后的 md 重新生成，嵌入 base64 图片

### 工程
- VERSION：更新为 2（v1.2.0）

---

## v1.0.1（Claude Code 审查改进版，2026-06-19）

### 技能与提示词
- SKILL.md Step 2 统一 prompt 新增鼻部/耳部/咽喉三个观察框架（鼻色/鼻衄/鼻鸣/鼻塞/鼻翼煽动、耳色/耳轮干枯/耳无所闻、咽喉颜色/咽干/喉中痰鸣/扁桃体）
- SKILL.md 安全红线从 5 条扩充至 10 条（新增肤冷+脉微真阳衰竭、巩膜黄染+橘皮急性肝胆重症、口不能言+身体不收中风重症、咽喉溃烂+面目乍赤乍黑狐惑重症、戴阳证严禁解表发汗）
- adaptive_analysis_prompt.md 安全红线同步扩充至 10 条，铁律第 3 条增加戴阳证严禁解表发汗约束

### 模板
- multi_dim_record_template.json：photos 从 5 个扩展至 9 个（新增 eyes/lips/skin/body/throat），doubao_vision_analysis 新增咽喉诊/鼻诊/耳诊/形体诊，skin_lesion 重命名为 skin，新增顶级 danger_flags 对象（9 种危重标志）
- weekly_report_template.json：trend_analysis 新增 face_trend/eye_trend/hand_trend/skin_trend，charts 改为对象数组格式

### 知识库
- 新增 knowledge_base/diet-lifestyle/diet-therapy.md：基于经典经方体系的食疗方案（四气五味概述、九种体质食疗映射、药物与食物禁忌、六病代表方饮食建议）
- 新增 knowledge_base/diagnostics/constitution-types.md：九种体质多维判定标准（舌象+面象+目诊+手诊+皮肤+唇口六维交叉判定）

### 脚本
- 重写 scripts/generate_weekly_report.py：实现 load_week_records()（含错误处理）、generate_radar_chart()（舌象指标分数映射）、generate_trend_chart()（多维度趋势线），使用 matplotlib+numpy
- 新增 scripts/input_validator.py：验证 daily analysis JSON 的必填字段、枚举值合法性、danger_flags 完整性检查

### 文档
- docs/user-guide.html：维度引用从 7 更新为 9（标题"七大拍照维度"→"九大诊断维度"，示例中 5/7→5/9，维度表扩充）

### 工程
- 新增 .gitignore（Python 缓存、生成数据、系统文件）
- 新增 requirements.txt（matplotlib>=3.7, numpy>=1.24）
- 新增 records/daily/.gitkeep、records/weekly/.gitkeep、charts/.gitkeep

---

## v1.0.0（初始版本，2026-06-18）

- 多维度中医望诊系统初始发布
- 基于经典经方经方学术体系的三观→四证→六病辨证路径
- 支持舌诊/面诊/目诊/手诊/皮肤诊/唇口诊多维度照片采集
- Doubao 视觉模型部位识别+望诊分析
- DeepSeek V4 自适应辨证引擎（LOW/MEDIUM/HIGH 三档置信度）
- 周报趋势分析（舌象雷达图、关键指标趋势线）
- 飞书机器人集成
