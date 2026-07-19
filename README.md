# 中医望诊系统（TCM Tongue System）

基于经典经方学术体系的多维度中医望诊辨证系统。

**纯 Python 数据模型库**——不绑定任何 LLM Agent 框架（Hermes / Codex / 其他均可接入）。

当前版本：**v1.3.3**。详见 [CHANGELOG.md](CHANGELOG.md)。

---

## 这是什么

一套望诊领域的 Python 模块，负责：

- **维度规范**：六维望诊（舌/头面/目/耳/手/皮肤）的枚举定义与中英双向适配
- **记录解析**：兼容两种 LLM 输出格式（中文键 vs 英文键）的统一数据层
- **定性→定量评分**：从自然语言描述到 0-10 分的映射引擎
- **置信度与安全边界**：覆盖度→置信度→方剂建议安全控制
- **知识检索**：Grep 优先 + 别名词典展开 + RAG 兜底的混合检索
- **结构化知识库**：7 个 Markdown/YAML 文件，涵盖辨证框架、方剂体系、体质分型、食疗等

**它不做什么**：不调 LLM API、不处理图片上传、不发 HTTP 请求。这些由外层 Agent 负责。

---

## 架构

```
你的 Agent（Hermes / Codex / 自定义）
  │
  ├─ 拍照片 → Vision API → 结构化望诊数据
  ├─ 把数据扔给 src/record.py → 解析归一
  ├─ 调 scoring.py / confidence.py → 评分 + 安全边界
  ├─ 拿 templates/adaptive_analysis_prompt.md → 塞进 LLM 做辨证
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

1. **拍照 → Vision API**：调你用的 Vision 模型（OpenAI GPT-4V / Claude Vision / 豆包等），用 `templates/adaptive_analysis_prompt.md` 作为 system prompt，让它产出结构化 JSON
2. **JSON → 数据层**：`DailyRecord.parse()` 吃进去
3. **评分 + 置信度**：调 `scoring` / `confidence` 模块
4. **辨证 → LLM**：把评分结果 + 知识库检索结果塞进 prompt，调 LLM 出辨证结论
5. **（可选）图表**：`scripts/generate_weekly_report.py` 生成周报趋势图

如果你用 **Codex CLI**，直接在项目里 `import src.dimensions` 就行，Codex 能用标准 Python 库，不需要任何适配。

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
- **LLM 无关**：不 import 任何 LLM SDK，不硬编码 provider 或 endpoint

---

## 许可

本项目代码（`src/`、`tests/`、`scripts/`）采用 [GNU General Public License v3.0](LICENSE)。

知识库内容（`knowledge_base/`）版权说明见 [knowledge_base/README.md](knowledge_base/README.md)。
