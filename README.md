# 中医望诊系统（TCM Tongue System）

基于经典经方学术体系的多维度中医望诊辨证系统：六维望诊（舌/头面/目/耳/手/皮肤）的规范化记录、评分、置信度与知识检索。

**纯 Python 数据模型库**——不绑定任何 LLM Agent 框架（Hermes / Codex / 其他均可接入）。

当前版本见根目录 [VERSION](VERSION) 文件；变更历史详见 [CHANGELOG.md](CHANGELOG.md)。

---

## 这是什么

一套望诊领域的 Python 模块，负责：

- **维度规范**：六维望诊（舌/头面/目/耳/手/皮肤）的枚举定义与中英双向适配
- **记录解析**：兼容 A 中文键 / B observations / C 顶层英文键的统一数据层
- **定性→定量评分**：从自然语言描述到 0-10 分的映射引擎
- **置信度与安全边界**：覆盖度→置信度→方剂建议安全控制
- **知识检索**：Grep 优先 + 别名词典展开 + RAG 兜底的混合检索
- **外置知识库**：通过 `TCM_KB_ROOT` 配置有权使用的私有内容；公开仓不再附带原文和别名词典

**它不做什么**：不调用 LLM API、不接收或上传图片、不发起任何 HTTP 请求——以上均由外层 Agent 负责。

> ⚠️ **望诊质量与你接入的视觉模型直接相关。** 本库负责规范化、评分、置信度与检索，**不做图像判读**——「舌苔是腻还是腐」「舌色是淡红还是偏红」这类判断全部来自你配置的视觉模型。模型可能给出含糊、错位或漏判的描述；新 `assess*` 接口会把无法判读或词表外文本标为 `unknown`，旧 `score*` 接口为兼容仍返回 0，**不能把兼容值 0 当作确认正常**。请务必按下文「配置自己的视觉模型」完成接入，并做完核对步骤，不要跳过。

---

## 架构

```
你的 Agent（Hermes / Codex / 自定义）
  │
  ├─ 拍照片 → Vision API → 结构化望诊数据
  ├─ 数据交给 src/record.py → 解析归一
  ├─ 调 scoring.py / confidence.py → 评分 + 安全边界
  ├─ 取 templates/adaptive_analysis_prompt.md → 送入 LLM 做辨证
  └─ 可选：调 retrieval/ → 查经典依据
        │
        ▼
    输出：舌诊报告 / 方剂建议 / 周报趋势
```

---

## 模块说明

| 模块 | Interface | 职责 |
|:---|:---|:---|
| `src/dimensions.py` | `VisionDimension` 枚举、`from_chinese`/`from_english` | 六维规范（中英名/子域/计数规则） |
| `src/indicators.py` | `INDICATOR_REGISTRY`、`DIMENSION_INDICATORS` | 45 项指标的路径、选项、别名、术语、出处与复核元数据 |
| `src/observations.py` | `Observation`、`Declaration`、`capture_observation()` | 采集方式约束、原始值/规范化值、未知与声明分离 |
| `src/record.py` | `DailyRecord.parse`、`get_observation(dim)`、`get_inquiry_answers()`、`get_formula_material()` | A/B/C 与形状 B v2 兼容，17 题问诊统一读取，汇总结构化方剂与报告相关段落 |
| `src/textnorm.py` | `normalize_text()`、`canonical_option()`、`display_text()` | 定向 Unicode/选项规范化，报告外部文本单行限长；不做整串 NFKC |
| `src/scoring.py` | `assess(dim, obs)`、`assess_indicators(dim, obs)`；兼容 `score()` / `score_indicators()` | 定性→状态化评分（正常/异常/未知/不适用），精确/最长子串/否定守卫 |
| `src/text_analysis.py` | `find_term(text, term)` | 评分与预警共享的否定、转折和排除语境分析 |
| `src/alerts.py` | `evaluate_alert()`、`evaluate_alerts()`、`danger_flags_for()` | 单项筛查/组合规则、三态评估、证据与出处；`src/danger.py` 保留兼容接口 |
| `src/danger_review.py` | `refresh_danger()`、`review_snapshot()`、`apply_decision()` | 证据快照、确认令牌、keep/dismiss/clear 审计与 merge 范围；不改变医学规则 |
| `src/confidence.py` | `from_coverage(n)`、`allows_formula(level)`、`allows_dosage(level)`、`is_consistent` | 覆盖度→置信度→安全边界 |
| `src/governance.py` | `build_decision_inventory()`、`validate_decision_table()`、`validate_calibration_report()` | 医学裁决清单、签认/迁移材料与真实标定报告的结构校验；不自动改医学规则 |
| `src/paths.py` | `REPO_ROOT`、`DATA_ROOT`、`ensure_data_dirs()` | 路径配置（`TCM_DATA_ROOT` 环境变量覆盖） |
| `src/retrieval/` | `retrieve(query)` → 结果列表 + 来源标注 | Grep + 同义词 + RAG 混合检索。⚠️ `search()` 接受原始正则，不受信输入请一律走 `retrieve()` |
| `knowledge_base/README.md` | 私有知识库配置说明 | 公开仓不附带原知识库；用 `TCM_KB_ROOT` 指向有权使用的目录 |
| `templates/` | prompt 模板 + JSON 记录模板 | LLM 分析指令、多维记录 schema |

核心 module（`dimensions` / `indicators` / `record` / `observations` / `scoring` / `alerts` / `text_analysis` / `confidence` / `governance`）仅依赖 Python 标准库。医学治理的 pending 语义、未标定辅助模式、可选标定和趋势边界见 [医学治理与边界](docs/GOVERNANCE_2026-10-27.md)。

---

## 快速开始

### 安装

```bash
pip install -r requirements.txt   # matplotlib numpy（周报画图）+ Pillow（示意图）；核心 src/ 零依赖
```

### Web 界面（推荐）

```bash
pip install -r web/requirements.txt   # Flask + Waitress + Pillow + tzdata（独立声明，不污染核心依赖）
python web/app.py                     # Waitress → http://127.0.0.1:8600
```

完整操作指引（首次配置、拍照向导、修正、趋势、局域网手机访问）见 [docs/web-quickstart.md](docs/web-quickstart.md)。

### 导入或自建知识库

公开仓不提供原知识库文件或在线下载。「设置 → 知识库」前方是默认折叠的「子知识库」分组，展开后可导入中医体质辨证、食疗、方剂三类专用包，分别对应 `TCM_KB_CONSTITUTION_ROOT`、`TCM_KB_DIET_ROOT`、`TCM_KB_FORMULA_ROOT`。分类 ZIP 必须含与卡片匹配的 `kb.yaml`；每类可独立更新和重置，重置只删除本类导入副本并设置 `TCM_KB_<类别>_DISABLED=1`。导入副本位于 `<TCM_DATA_ROOT>/private_kb/<类别>/`，完整路径收在“技术详情”中。

子知识库整组、三个子库和综合知识库各有独立开关。关闭整组会暂停三个子库及综合回退，但不覆盖各子库自身选择，恢复整组后按原选择生效；关闭综合库只暂停综合根及分类回退，不影响已配置的独立专用根。开关只控制检索、报告及本地速览的对应内容，不删除文件。`TCM_KB_CATEGORIES_DISABLED=1` 控制整组，`TCM_KB_COMPOSITE_DISABLED=1` 控制综合库。

综合知识库位于子知识库分组之后，用于一个 ZIP 包含多类资料。需要把中医著作整理成综合包时，先按[从中医著作到知识库](docs/kb-guide.md)选择著作和搭配资料，再把著作电子版与[自建知识库格式与导入规范](docs/KB_AUTHORING.md)交给 AI，生成一个综合知识库 ZIP。设置页知识库卡片右上角也可打开该指南；目录结构、`composite` 清单和别名词典以技术规范为准，不在选书指南中重复。

新 clone 默认不读取外部旧知识库，程序管理副本在成功导入后启用。分类导入只替换本类副本并解除本类自身停用；综合导入替换综合副本、保留三类专用子目录并解除综合自身停用。导入不会自动开启整组或改变其他类别的选择，也不移动、覆盖或删除外部原始知识库；非法包或激活失败保留旧副本，配置写回失败会同时恢复配置和目录，环境变量锁定时不改配置。自定义内容只影响检索与候选参考，不自动修改医学规则，也不是模型训练；资料许可、准确性和人工复核由使用者负责。

每类独立区分未配置、空库、可用和错误；缺少体质库隐藏体质/辨证内容，缺食疗库隐藏饮食建议，缺方剂库隐藏方药及完整方药报告，旧记录内容也不能绕过。默认报告按当前可用类别构造统一检索视图：三类齐全与综合库一致，双模块与源库对应子集一致，缺类不把该类证据送入模型。开启 `TCM_KB_STRICT_CATEGORIES=1` 后不再回退综合库，只认各类专用根；该模式与整组启停相互独立。报告生成使用各类别当前有效根，保存 `kb_categories` 及兼容字段；目录、内容或启停造成有效来源变化时旧报告提示过期，恢复原状态且指纹一致后可继续显示。缺方剂的方名/剂量、缺食疗的结构化饮食、缺体质的结构化辨证输出会在写入前拒绝。报告尾部的条文是**送入模型的候选参考，不等同实际引用**；本地速览始终使用项目内置规则计算，但只有对应类别可用时才展示。

本机与局域网访问都须先完成 welcome 确认，设置页与配置操作也不例外。局域网使用须先
在设置页配置 `WEB_ADMIN_TOKEN`，再以 `python web/app.py --lan` 启动；无口令的非回环监听
会拒绝启动。手机确认 welcome 后，在设置页输入口令建立会话，记录、趋势和照片均需验证后
访问；不要把口令放进 URL。welcome 的须知确认不代替身份验证。

### 跑测试

```bash
python3 -m pytest tests/ -v       # 跑全部测试，确认环境 OK（自带脱敏 fixture，开箱即跑）
```

共享 fixture 为每项测试隔离 HOME、模型环境和数据目录；真实配置与健康记录不参与测试，模型调用一律 mock。

### 作为库使用

以仓库根为工作目录（或把仓库根加入 `sys.path`），`src` 是常规 Python 包：

```python
from src.dimensions import VisionDimension
from src.record import DailyRecord
from src.scoring import score
from src.confidence import from_coverage, allows_formula

# 解析 LLM 返回的望诊数据（dict 或 JSON 字符串；日期在记录的 date 字段里）
record = DailyRecord.parse(json_data)

# 获取舌诊观察
tongue_obs = record.get_observation(VisionDimension.TONGUE)

# 评分（0 = 正常，10 = 极重度异常）
scores = score(VisionDimension.TONGUE, tongue_obs)

# 置信度
level = from_coverage(record.get_covered_dimension_count())
print(allows_formula(level))  # True/False
```

### 接入你的 Agent

源码不绑定任何框架。你需要补的唯一一件事是 **orchestration 层**：

1. **拍照 → Vision API**：调你用的 Vision 模型（OpenAI 兼容多模态端点均可），让它产出结构化 JSON——推荐入口是 `scripts/vision_client.py observe`（内置与评分词表逐键对齐的封闭词表 prompt，配置见下文「配置自己的视觉模型」）
2. **JSON → 数据层**：交给 `DailyRecord.parse()` 解析归一
3. **评分 + 置信度**：调 `scoring` / `confidence` 模块
4. **辨证 → LLM**：把评分结果 + 知识库检索结果并入 prompt，调 LLM 输出辨证结论（`templates/adaptive_analysis_prompt.md` 是**本步**的 system prompt，输出 Markdown 报告，非结构化 JSON）
5. **（可选）图表**：`scripts/generate_weekly_report.py` 生成周报趋势图

> **记录形状说明**：本库支持三种记录形状——**A**（模板中文键，顶层 `vision_analysis` / `diagnosis`；旧名 `doubao_vision_analysis` / `deepseek_diagnosis` 永久兼容）、**B**（`observations` 英文键）、**C**（顶层规范英文维度键）。`templates/multi_dim_record_template.json` 是形状 A 的完整 schema 存档参考；**新用户日常记录推荐形状 B**——把 `vision_client.py observe` 的输出并入 `observations` 即可，无需照模板逐键填写。三种形状由 `DailyRecord` 自动识别，下游代码无需感知差异。

任何能运行 Python 的 Agent 都能直接 `import src.dimensions`——标准库即够用，无需任何适配层。

---

## 配置自己的视觉模型

> **本系统不内置判读模型**——识图质量完全取决于你在此处接入的模型。同一张舌照，不同模型给出的描述可能相差很大，**判读能力越强的模型，望诊质量越高**。下面的三件套配置只是让流程「跑起来」；后文的**五步 checklist 才是让它「跑得准」**，其中第 3、5 步不可跳过。

`scripts/vision_client.py` 是识图统一入口，支持任意 **OpenAI 兼容多模态模型**，通过环境变量或项目根 `.env` 配置（环境变量优先；模板见根目录 [.env.example](.env.example)）：

| 变量 | 必填 | 默认 | 含义 |
|:---|:---|:---|:---|
| `VISION_MODEL` | ✅ | — | 模型名（以厂商文档为准） |
| `VISION_BASE_URL` | ✅ | — | OpenAI 兼容的 chat/completions 端点 |
| `VISION_API_KEY` | ✅ | — | 该端点的 API key |
| `VISION_TEMPERATURE` | 否 | 不发送该键 | ⚠️ 设 0 ≠ 确定性输出：部分模型有官方下限（更低值被服务端静默改写），查官方文档 default/range/clamp 三栏 |
| `VISION_MAX_TOKENS` | 否 | 600 | 思考型（reasoning）模型的思考过程占用该额度，建议 ≥8000 |
| `VISION_TIMEOUT` | 否 | 150 | observe 连接、重定向、重试和读取的总时限（classify 固定 60） |

> ⚠️ 默认模型名 `qwen3.8-max` **仅为示例**，请替换。`VISION_BASE_URL` **没有默认值，必须显式配置**；未配置端点时会报错，不会把 key 或照片发往默认第三方。合法的本地/Ollama HTTP 端点仍可正常使用。

> 兼容说明：旧变量 `DASHSCOPE_API_KEY` 仍作为历史兼容回退被识别（作者早期环境遗留），**新配置一律用 `VISION_API_KEY`**；实际用到旧变量时脚本会打一条 stderr 弃用提示。

**换模型 checklist（五步）**：

1. 复制 `.env.example`，填好 `VISION_MODEL` / `VISION_BASE_URL` / `VISION_API_KEY` 三件套
2. 跑 `python3 scripts/vision_client.py classify <照片>`，确认连通且能正确识别照片类型（舌面/舌下/头面/目/耳/手/皮肤）
3. 跑 `python3 scripts/vision_client.py observe <照片> 舌面`，确认输出为 JSON 且含「舌质润燥」等规范键
4. 输出为空或被截断 → 设 `VISION_MAX_TOKENS=8000`；输出措辞太随意 → 查官方文档后设 `VISION_TEMPERATURE`
5. 同一张照片连跑 5 次，对照肉眼签认；抖动大的字段以肉眼为准，并记录为该模型的已知弱项

> ⚠️ **换模型必须重新核对**：`vision_client.py` 的 prompt 采用封闭词表（如腻腐只填 无/微腻/稍腻/偏腻/腻/厚腻/腐苔），与 `src/scoring.py` 的评分词表逐键对齐。词表之外的措辞在新 `assess*` 接口返回 `unknown`，旧 `score*` 接口为兼容仍返回 0，但 0 **不等于确认正常**。因此换模型后第 3、5 步不是可选项：使用你有权使用的照片核对措辞落域与重复识图稳定性，并对照原图人工复核。上述核查不等于独立医学标定；当前按主人定策以未标定辅助模式运行，不把模型自评当作医学真值，也不宣称疾病诊断或剂量推荐已经验证。详见[医学治理与边界](docs/GOVERNANCE_2026-10-27.md)。

---

## 校验与周报

```bash
# 校验单日记录（安全边界违反 → 退出码 1）
python3 scripts/input_validator.py records/daily/2026-07-09_analysis.json

# 生成周报（需 matplotlib + numpy）
python3 scripts/generate_weekly_report.py 2026-07-09
```

数据目录默认在仓库根下的 `records/`、`charts/`；部署机可用环境变量
`TCM_DATA_ROOT` 指到别处（如 `/root/tcm-tongue-system`），知识库位置
同理可用 `TCM_KB_ROOT` 覆盖（对 grep、RAG 与默认别名词典同时生效；相对路径统一
按仓库根解析）。RAG 只保留相关度过线的证据，AND 查询按真实文件复核全部条件；
手工修改进程内知识库内容后需重启或清理索引缓存，ZIP 导入和回滚会自动清理该根缓存。

部署时可用 `TCM_TIMEZONE` 指定 IANA 时区（如 `Asia/Shanghai`）；Web 也可在 `.env`
配置。未设置时使用系统时区，无效值告警并回退系统时区。记录日期、周报和新的修正/
报告时间戳使用同一口径；旧记录中的 naive 时间戳保留原样，不做时区猜测。

> ⚠️ `TCM_DATA_ROOT` / `TCM_KB_ROOT` / `kb_root` 参数是**部署配置**，
> 不应来自用户输入——知识库根指向任意目录即可读出其中全部 .md 文件。

---

## 目录结构

```
src/
  dimensions.py            # 六维望诊规范枚举
  record.py                # 记录解析 + 形状兼容
  scoring.py               # 定性→定量评分引擎（0=正常基线）
  confidence.py            # 置信度 + 安全边界
  paths.py                 # 路径配置（TCM_DATA_ROOT 可覆盖）
  daily_files.py           # 每日记录一次扫描、统一选档与副本排除
  retrieval/               # 混合检索（Grep + 同义词 + RAG）
scripts/
  input_validator.py       # 记录校验（安全边界违反=退出码 1）
  generate_weekly_report.py # 周报生成
  vision_client.py         # 识图统一入口（OpenAI 兼容视觉模型，可用环境变量插拔）
  backup_to_oss.sh         # OSS 备份（已排除健康数据与版权全文）
templates/                 # Prompt + JSON schema + 非医学自建知识库模板
web/                       # Flask Web 入口（welcome 门禁/记录/详情/趋势/拍照向导/设置，
                           # `python web/app.py` 启动，--lan 开局域网）
tests/                    # pytest 套件（fixtures/ 内置脱敏样例记录；数量随开发变化，以实际运行为准）
knowledge_base/            # 公开仓仅含私有知识库配置说明，不附带原文或词典
docs/                      # 用户指南、架构分析、审查报告
```

---

## 设计原则

- **诊断体系：以《经方探源》为主，《中医诊断学》为辅**（2026-10-21 主人拍板）。
  辨证框架（三观→四证→六病、方证对应、安全红线里的戴阳/脱阳等）一律以
  《经方探源》为准绳；《中医诊断学》只提供舌象/体征的**词汇与量化层**
  （评分词表、危重舌象形态识别）。九体质（学会标准）不进主流程。
  词表逐条出处见 `docs/VOCAB_PROVENANCE_2026-10-16.md`；新增词条/判据必须
  先标出处再入库，**不得伪托**。
- **纯 Python，零框架依赖**：核心 module 仅用标准库；matplotlib/numpy 仅周报画图可选
- **深 module / 浅 interface**：每个 module 用小 interface 背后藏大量行为
- **安全边界可断言**：`allows_formula(LOW) == False` 把"宁缺毋滥"变成可执行测试
- **框架层 LLM 无关**：`src/` 不 import 任何 LLM SDK、不绑定 provider；`scripts/vision_client.py` 是可插拔的识图脚本，按你在 `.env` 中配置的端点发起调用（默认配置仅作示例，可整体替换）

---

## 隐私与数据

> 最后更新：2026-09-25。本声明适用于本仓库发布的代码（`src/`、`scripts/`），不涵盖使用者自行部署时新增的组件或第三方服务。

**本项目方不收集、不存储、不接收你的任何数据**——本库无遥测、无统计上报、无向项目方或任何第三方的数据回传。你的数据只会在一种情况下离开本机：你主动配置并使用了云端视觉/语言模型服务（见下），此时数据的接收方是你自己选择的服务商，而非本项目。

- **数据流向由你掌控**：照片、望诊记录（`records/`）、图表（`charts/`）全部保存在你的机器上。`src/` 框架代码不发起任何网络请求、不含任何分析/追踪 SDK，也不硬编码任何 provider 或 endpoint。`scripts/vision_client.py` 只把照片与 prompt 发送到你**显式配置**的视觉模型端点（`VISION_BASE_URL` 必填，无默认第三方；支持兼容的本地服务）。上传和 CLI 图片会先按 EXIF 方向重排像素并剥离 GPS/设备元数据，再编码为 JPEG；模型只收到清洗后的字节。若你选用云端模型，处理后的图片与文本仍会传输至该服务商——是否采用云端服务、如何保护数据由你决定，API key 亦由你自备。
- **备份默认不碰健康数据**：OSS 备份脚本只打包经过敏感路径筛选的 git 跟踪文件，排除 `records/`、`charts/`、配置与版权文件；需显式配置 `TCM_OSS_BUCKET`，未设置则拒绝上传。
- **使用者的责任**：健康数据属敏感个人信息，请妥善保管本地目录与备份权限；若面向他人提供服务，请遵守当地个人信息保护法规。

由于本项目方不收集任何数据，也不运营任何服务端，因此不存在需向本项目方请求查询、导出或删除的个人数据。就本声明的问题或改进建议，欢迎提交 [GitHub Issue](https://github.com/bonesyear/tcm-tongue-system/issues)。

---

## 许可

项目代码（`src/`、`scripts/`、`web/`、`tests/`）及项目自有模板（`templates/`）采用 [GNU General Public License v3.0](LICENSE)。仓库附许可证全文；`/license` 页面可直接查看。

原始引文、例图及第三方组件保留各自的版权与许可边界，不因代码采用 GPL 而获得再分发授权。原知识库已移入私有目录，公开仓只保留 [配置说明](knowledge_base/README.md)；请用 `TCM_KB_ROOT` 指向你有权使用的目录，详见 [公私分离迁移](docs/MIGRATION_2026-11-03_KB_SPLIT.md)。
