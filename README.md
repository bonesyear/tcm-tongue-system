# 中医望诊系统（TCM Tongue System）

基于经典经方学术体系的多维度中医望诊辨证系统：六维望诊（舌/头面/目/耳/手/皮肤）的规范化记录、评分、置信度与知识检索。

**纯 Python 数据模型库**——不绑定任何 LLM Agent 框架（Hermes / Codex / 其他均可接入）。

当前版本见根目录 [VERSION](VERSION) 文件；变更历史详见 [CHANGELOG.md](CHANGELOG.md)。

---

## 这是什么

一套望诊领域的 Python 模块，负责：

- **维度规范**：六维望诊（舌/头面/目/耳/手/皮肤）的枚举定义与中英双向适配
- **记录解析**：兼容两种 LLM 输出格式（中文键 vs 英文键）的统一数据层
- **定性→定量评分**：从自然语言描述到 0-10 分的映射引擎
- **置信度与安全边界**：覆盖度→置信度→方剂建议安全控制
- **知识检索**：Grep 优先 + 别名词典展开 + RAG 兜底的混合检索
- **结构化知识库**：7 个 Markdown/YAML 文件，涵盖辨证框架、方剂体系、体质分型、食疗等

**它不做什么**：不调用 LLM API、不接收或上传图片、不发起任何 HTTP 请求——以上均由外层 Agent 负责。

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
| `src/record.py` | `DailyRecord.parse`、`get_observation(dim)`、`get_formula()`… | 记录形状兼容（中文键↔英文键归一） |
| `src/scoring.py` | `score(dim, obs)`、`score_indicators(dim, obs)` | 定性→定量评分（0=正常基线），精确/最长子串/否定守卫 |
| `src/confidence.py` | `from_coverage(n)`、`allows_formula(level)`、`allows_dosage(level)`、`is_consistent` | 覆盖度→置信度→安全边界 |
| `src/paths.py` | `REPO_ROOT`、`DATA_ROOT`、`ensure_data_dirs()` | 路径配置（`TCM_DATA_ROOT` 环境变量覆盖） |
| `src/retrieval/` | `retrieve(query)` → 结果列表 + 来源标注 | Grep + 同义词 + RAG 混合检索。⚠️ `search()` 接受原始正则，不受信输入请一律走 `retrieve()` |
| `knowledge_base/` | 7 个 Markdown/YAML 文件 | 辨证框架、方剂体系、体质分型、食疗、别名词典 |
| `templates/` | prompt 模板 + JSON 记录模板 | LLM 分析指令、多维记录 schema |

四个核心 module（`dimensions` / `record` / `scoring` / `confidence`）仅依赖 Python 标准库。

---

## 快速开始

### 安装

```bash
pip install -r requirements.txt   # matplotlib numpy（周报画图）+ Pillow（示意图）；核心 src/ 零依赖
```

### 跑测试

```bash
python3 -m pytest tests/ -v       # 159 项，确认环境 OK（自带脱敏 fixture，开箱即跑）
```

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

`scripts/vision_client.py` 是识图统一入口，支持任意 **OpenAI 兼容多模态模型**，全部通过环境变量配置（模板见根目录 [.env.example](.env.example)，复制为 `.env` 或直接导出环境变量）：

| 变量 | 必填 | 默认 | 含义 |
|:---|:---|:---|:---|
| `VISION_MODEL` | ✅ | — | 模型名（以厂商文档为准） |
| `VISION_BASE_URL` | ✅ | — | OpenAI 兼容的 chat/completions 端点 |
| `VISION_API_KEY` | ✅ | — | 该端点的 API key |
| `VISION_TEMPERATURE` | 否 | 不发送该键 | ⚠️ 设 0 ≠ 确定性输出：部分模型有官方下限（更低值被服务端静默改写），查官方文档 default/range/clamp 三栏 |
| `VISION_MAX_TOKENS` | 否 | 600 | 思考型（reasoning）模型的思考过程占用该额度，建议 ≥8000 |
| `VISION_TIMEOUT` | 否 | 150 | observe 单次请求超时秒数（classify 固定 60） |

> ⚠️ 代码默认值（`qwen3.8-max` + DashScope 端点）**仅为示例**，目的是 clone 后不配置也能看到结构；**请务必替换为你自己的模型与端点**。

**换模型 checklist（五步）**：

1. 复制 `.env.example`，填好 `VISION_MODEL` / `VISION_BASE_URL` / `VISION_API_KEY` 三件套
2. 跑 `python3 scripts/vision_client.py classify <照片>`，确认连通且能正确识别照片类型（舌面/舌下/头面/目/耳/手/皮肤）
3. 跑 `python3 scripts/vision_client.py observe <照片> 舌面`，确认输出为 JSON 且含「舌质润燥」等规范键
4. 输出为空或被截断 → 设 `VISION_MAX_TOKENS=8000`；输出措辞太随意 → 查官方文档后设 `VISION_TEMPERATURE`
5. 同一张照片连跑 5 次，对照肉眼签认；抖动大的字段以肉眼为准，并记录为该模型的已知弱项

> ⚠️ **换模型必须重新标定**：`vision_client.py` 的 prompt 采用封闭词表（如腻腐只填 无/微腻/稍腻/偏腻/腻/厚腻/腐苔），与 `src/scoring.py` 的评分词表**逐键对齐**——词表之外的措辞会被评分层**静默读作 0 分 = 正常**，不产生任何报错。因此换模型后第 3、5 步不是可选项：必须用真实照片验证新模型的措辞落在封闭词表内，否则异常体征会被静默归零。

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
同理可用 `TCM_KB_ROOT` 覆盖（对 grep 与 RAG 同时生效）。

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
  retrieval/               # 混合检索（Grep + 同义词 + RAG）
scripts/
  input_validator.py       # 记录校验（安全边界违反=退出码 1）
  generate_weekly_report.py # 周报生成
  draw_hand_diagram.py     # 手部解剖示意图
  vision_client.py         # 识图统一入口（OpenAI 兼容视觉模型，可用环境变量插拔）
  backup_to_oss.sh         # OSS 备份（已排除健康数据与版权全文）
templates/                 # Prompt 模板 + JSON schema
tests/                     # 159 项 pytest（fixtures/ 内置脱敏样例记录）
knowledge_base/            # 经方体系知识库（含版权说明见其 README）
docs/                      # 用户指南、架构分析、审查报告
```

---

## 设计原则

- **纯 Python，零框架依赖**：四个核心 module 仅用标准库；matplotlib/numpy 仅周报画图可选
- **深 module / 浅 interface**：每个 module 用小 interface 背后藏大量行为
- **安全边界可断言**：`allows_formula(LOW) == False` 把"宁缺毋滥"变成可执行测试
- **框架层 LLM 无关**：`src/` 不 import 任何 LLM SDK、不绑定 provider；`scripts/vision_client.py` 是可插拔的识图脚本，按你在 `.env` 中配置的端点发起调用（默认配置仅作示例，可整体替换）

---

## 隐私与数据

> 最后更新：2026-08-28。本声明适用于本仓库发布的代码（`src/`、`scripts/`），不涵盖使用者自行部署时新增的组件或第三方服务。

**本库不收集、不存储、不上传任何用户数据**——无遥测、无统计上报、无数据回传。

- **数据只在本机**：照片、望诊记录（`records/`）、图表（`charts/`）全部保存在你的机器上。`src/` 框架代码不发起任何网络请求、不含任何分析/追踪 SDK，也不硬编码任何 provider 或 endpoint；`scripts/vision_client.py` 仅向你**自行配置**的端点（`VISION_BASE_URL`）发送照片与 prompt，是否使用云端视觉服务由你决定。
- **网络调用由外层 Agent 发起**：本库只处理数据，不调 LLM、不传图片。若你配置的 Agent 使用**云端模型**（视觉/语言），则相关照片与文本会上传至该服务商——是否采用云端服务、如何保护数据，由使用者自行决定与配置（API key 亦由使用者自备）。
- **备份默认不碰健康数据**：OSS 备份脚本已排除全部 `records/`、`charts/` 与版权全文，需主动配置才会启用。
- **使用者的责任**：健康数据属敏感个人信息，请妥善保管本地目录与备份权限；若面向他人提供服务，请遵守当地个人信息保护法规。

由于本库不收集任何数据，也不运营任何服务端，因此不存在需向本项目方请求查询、导出或删除的个人数据。就本声明的问题或改进建议，欢迎提交 [GitHub Issue](https://github.com/bonesyear/tcm-tongue-system/issues)。

---

## 许可

本项目代码（`src/`、`tests/`、`scripts/`）采用 [GNU General Public License v3.0](LICENSE)。

知识库内容（`knowledge_base/`）版权说明见 [knowledge_base/README.md](knowledge_base/README.md)。
