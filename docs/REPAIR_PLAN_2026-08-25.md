# 修改执行规划（tcm-tongue-system，2026-08-25 定案）

> 来源：Kimi 代码审查（docs/CODE_REVIEW_2026-08-25_KIMI.md，18 条问题）+ "干燥/润泽"专项审查（方案 A）。
> 状态：**已定案，待 kimi 额度重置后执行**。执行时按文件域分 3 轮，域内按严重度。
> 铁律：每轮改完跑全量测试（159）+ 相关实测；kimi 修复后须 review diff + 独立复验再提交。

## 总览

- 已消条目：#4（.env 注释）、#18（docstring）、增量 A/B（load_key 合并/assert 文案）
- 跳过：#17（prompt emoji，收益低）
- 待修：**14 条**，分 3 轮
- 执行顺序：轮次 1（vision_client.py）→ 轮次 2（辨证层）→ 轮次 3（文档层）

## 执行进度

- ✅ **轮次 1 完成**（2026-09-17）：`vision_client.py` #1/#2/#3/#6/#7 + 方案 A 项 1（prompt 舌质润燥粗判，含"不判舌神/荣枯"否定指令）+ 新建 `tests/test_vision_client.py`（14 函数/20 用例，全 mock）→ **179 passed**（159+20）｜ classify 实测输出"舌面" ｜ 参数/未知 mode 退出码 2 ｜ ruff `F,E722` 全过 ｜ 独立 diff 审查通过
  - 附带完成 K3 补充：`assert key` → 显式 RuntimeError（`-O` 安全）
  - **轮次 1 补修（自查发现，同日）**：项 1 原 prompt 未声明 JSON 键名 → 模型自造键 `"舌质润燥粗判"`（值里混入括号说明）。已修为**键名固定 `舌质润燥`、值只填单词**，实测确认输出 `"舌质润燥": "润泽"` ✅
  - ⚠️ **轮次 2 注意**：record.py A 路径改名必须用 `["舌质润燥"]`（与 prompt 键名严格一致，已实测对齐）；中间态期间该字段不被解析（空转，无错误）
  - 残留风格告警（非项目标准，可选后续）：`S110`/`BLE001`（HTTP body 读取的 `except Exception: pass`，设计取舍）、`UP041`（`socket.timeout` 可用 `TimeoutError` 替代）、`I001`（import 排序）、`EXE001`（shebang 不可执行）
- ⏳ **轮次 2 待执行**：辨证层 #5/#8/#9/#10/#12 + 方案 A 项 2~11 + 文档层 #16（K3 修订：并入轮次 2 末尾）；#11 降级为可选，#15 已删除
- ⏳ 轮次 3：已取消（并入轮次 2）

---

## 轮次 1 — scripts/vision_client.py（6 条）

| 序 | # | 问题 | 改动要点 | 验证 |
|---|---|---|---|---|
| 1 | #2 | API/网络错误无处理→KeyError 裸崩 | call() 捕获 HTTPError/URLError/socket.timeout；无 choices 检查；抛 RuntimeError 带状态码/摘要 | mock 4xx/5xx/缺 choices 断言非 KeyError |
| 2 | #3 | 命令行参数无边界检查 | 入口校验 len(sys.argv)；classify≥3/observe≥4；不足 exit(2)+用法 | subprocess 缺参断言退出码 2 |
| 3 | #1 | 文件句柄未关闭 | `with open(img_path,"rb") as f:` 包住 b64 读取 | 代码审查 |
| 4 | #6 | 图片 MIME 写死 jpeg | 扩展名→MIME（.png/.jpg/.jpeg/.webp），未知回退 jpeg | 各扩展名断言 payload url 前缀 |
| 5 | #7 | classify 不校验输出类别 | 输出 strip 取首行匹配 PROMPTS keys；不匹配回退"其他"+stderr 警告 | mock 未知类别断言回退 |
| 6 | #14 | 无测试覆盖 | 新建 tests/test_vision_qwen.py：正常/HTTP错误/参数/key未设/.env注释/MIME/类别 | 新增+全量通过 |

**中断风险**：完成 #2/#3 即可安全发布；#2 前中断 → API 失败仍裸崩（最坏）。

## 轮次 2 — 辨证层（confidence + scoring + record，7 条）

| 序 | # | 问题 | 改动要点 | 验证 |
|---|---|---|---|---|
| 1 | #5 | 否定词"非"误杀"非正常" | _NEGATION_RE 移除"非"（无/不/未/没 已够） | "非正常红润/非典型黄染"不否定断言 |
| 2 | #8 | has_formula_content key 白名单漏检 | 保留白名单+兜底扫描剂量模式 \d+[g克]/经方名 | {"description":"含桂枝10g"}判有方 |
| 3 | #9 | fallback 返回整个 diag | 形状 A 找不到键返回 {}（或显式历史 key 尝试） | shape A 缺键不污染 |
| 4 | #10 | 英文词边界不严（HIGH1→HIGH） | 只认空格/连字符/CJK/结尾为边界 | HIGH1/HIGH_2 → None |
| 5 | #11 | 舌诊均值缺测试 | body=7+coating=7 其余 0 → score==7.0 | 新增断言（#5 后做） |
| 6 | #12 | danger_flags 形状 A 无测试 | shape A fixture daiyang.triggered=true → ["daiyang"] | 新增测试 |
| 7 | #13 | 干燥/润泽方案 A 落地（见下） | 11 项落地清单 | 见专项 |

**中断风险**：#5 前中断 → 评分误杀"非正常"（影响辨证，最坏）；#5/#8/#9 完成 → 安全边界已修。

### #13 方案 A 落地清单（11 项）

1. `vision_client.py` PROMPTS["舌面"] 加"舌质润泽/干燥（粗判：润泽/偏干/干燥/干裂）"
2. `record.py` body_luster A 路径 ["舌质荣枯"] → ["舌质润燥"]（B 路径保留）
3. `scoring.py` DIMENSION_RULES[TONGUE] **移除 body_luster**（不再 score()）
4. `scoring.py` TONGUE_BODY_LUSTER_MAP 保留+注释"已降级仅历史兼容"
5. `scoring.py` 评分基线注释删"荣润"示例
6. `scoring.py` TONGUE_RADAR_METRIC_KEYS 加注释（照片光线干扰、静态不可判神气）
7. `tests/test_scoring.py` 删/改 test_body_luster_scoring（分数 0/不存在）
8. `tests/test_scoring.py` 正常舌象 fixture 删 body_luster 或期望 0
9. `tests/test_record.py` 补"舌质润燥"路径解析测试
10. `tests/fixtures/2026-06-25_analysis.json` score 期望更新（**历史评分口径变化**，正确方向）
11. `templates/multi_dim_record_template.json` "舌质荣枯"→"舌质润燥"

语义：干燥/润泽**评分层降级**（不计分、不进雷达图），**辨证层保留**（LLM prompt 参考，津亏/湿盛辅助信号）。双计：结构化输入不双计（独立字段），纯文本重复计分是既有已知局限。

## 轮次 3 — 文档层（2 条）

| # | 问题 | 改动 |
|---|---|---|
| 15 | confidence.py:9 引用不存在的 dimension-overlap-analysis.md | 改指 templates/adaptive_analysis_prompt.md §3.1 |
| 16 | record.py:23 / dimensions.py:13 引用 /codebase-design | 删除或改指实际文档 |

**中断无运行时风险**。

---

## 依赖关系

```
#14 测试 ← #2/#3/#6/#7 修完
#11 测试 ← #5 之后
#13 ← 独立已定案
```

## 验证总要求

- 每轮：pytest tests/ -q 全量通过；vision_client.py 改动后实测 `python3 scripts/vision_client.py classify <图>` 输出"舌面"
- 提交前：kimi 报告后自行 git diff review + 独立复验（测试/实测/ruff check --select F,E722）
- 每轮独立 commit（不混批次）

---

## K3 复核待办（2026-08-28 补充）

**背景**：2026-08-25 的审查/规划/修复全部由 K2.7（kimi-code/kimi-for-coding）完成——当日 config 默认模型为 K2.7。2026-08-28 已将 `default_model` 改为 `kimi-k3`（config.toml 16:44 修改）。

**已豁免复核**：增量修复（load_key/assert/docstring）+ 卫生清理——已通过 159 测试/实测/ruff/diff review 客观验证，与模型无关。

**待 K3 复核（判断层）**：18 条问题清单准确性、规划 v2 轮次设计、方案 A 落地清单 11 项、增量确认结论。K2.7 有错判前科（#4 注释行误读判断被实测推翻）。

**执行方式**（配额恢复后，预计 2026-09 中旬）：
```
开新会话（勿 resume 旧会话——旧会话绑定 K2.7）
kimi -m kimi-k3 -p "读 docs/CODE_REVIEW_2026-08-25_KIMI.md 与 docs/REPAIR_PLAN_2026-08-25.md，复核：①18条问题是否准确、有无遗漏重大问题 ②规划轮次是否合理 ③方案A落地清单有无漏洞"
```
复核结论追加到本文件。复核通过后才按轮次 1→2→3 执行修复。

---

## K3 复核修订（2026-09-17 完成，执行以本节为准）

**复核报告**：`docs/K3_REVIEW_2026-09-17.md`（kimi-k3 新会话，只读复核）
**总评：需修订后执行**——K3 整体确认方向，但**推翻 K2.7 的 4 处判断**（印证"K2.7 有错判前科"）。

### 清单修订

| # | K2.7 原判 | K3 复核结论 | 处置 |
|---|---|---|---|
| **#15** | 引用的 dimension-overlap-analysis.md 不存在 | ❌ **确凿误判**——文件存在（`docs/architecture/`），§5.2 正是置信度映射表 | **整条删除** |
| **#11** | 缺"多异常取均值"测试 | ❌ **前提不成立**——`test_scoring.py:176-194`（双异常均值 7.0）+ `test_weekly_report.py:49-50`（5.5）已覆盖；改累加封顶必红 | **降级为可选冗余** |
| **#9** | 两个 get_* 方法 fallback 返回整个 diag | ⚠️ **范围多算一半**——仅 `get_pattern_differentiation`（`record.py:263`）；`get_formula`（`:277`）默认已返回 `{}` | 范围收窄为 1 个方法 |
| **#4** | .env 注释行被误读 | ⚠️ 原判本不成立（`startswith` 免疫行首 `#`），真实风险=行内注释；已修（`vision_client.py:22/28`） | 已完成；审查报告"总体结论"仍列 #4 为最值得修——**已加注消解矛盾** |

**其余 14 条逐条核实成立**（行号因 load_key 重构漂移）；**功能忠实度 3 条结论复核无误**；**无重大遗漏**。

### K3 新发现的 2 条补充（并入既有轮次）

1. `vision_client.py:52` 用 `assert` 做运行时校验 → `python -O` 下失效且报错体验差 → **并入 #2/#3 一起修**
2. `record.py:295` `flag.get("triggered") is True` 严格布尔 → LLM 若输出字符串 `"true"` 会静默不触发（**fail-open**）→ 加注释或宽松化（实际风险低）

### 轮次修订

| 修订 | 内容 |
|---|---|
| 轮次 3 合并 | 删 #15 后仅剩 #16 → **并入轮次 2 末尾**（单条注释不值得独立一轮） |
| 方案 A 项 1 归位 | 改的是 `vision_client.py` PROMPTS 却排在轮次 2 → **挪入轮次 1**（否则轮次 1 结束时该文件非终态） |
| 文件名修正 | #14 测试应命名 **`tests/test_vision_client.py`**（两份文档残留旧名 test_vision_qwen.py） |
| 依赖图 | `#11 ← #5` 随降级删除；`#14 ← #2/#3/#6/#7` 保持 |

**已知取舍**（K3 认可）：轮次 1（vision P1/P2）整体先于辨证层 P0（#5/#8/#9）——文件域分组 vs 严格严重度优先的取舍；每轮独立 commit + 全量测试 + 中断风险分析可辩护。

### 方案 A 清单修订

| 项 | 修订 |
|---|---|
| 项 1 | **保留"明确不判神气/荣枯"否定指令**（勿只写"粗判"）；建议键名用"舌质润燥度"（避免与既有"舌苔润燥"一字之差混淆）→ 挪轮次 1 |
| 项 2 | 补历史兼容说明：实测 `records/daily` 60 个文件全为形状 B（无实际影响）；**项 2 与项 11 必须同 commit**（validator SCHEMA 数据驱动自 `_DIMENSION_INDICATORS`，模板键与 A 路径不同步会造成校验漂移） |
| 项 4 | **建议直接删除 `TONGUE_BODY_LUSTER_MAP`**（从 rules 移除后无消费者=死代码；词汇表为荣枯体系，与新润燥词汇不匹配，"历史兼容"名不副实）；若坚持保留，须同步改 `scoring.py:111` 头注释 |
| 项 10 | 前提不成立 → 改"**先跑全量测试验证**"：fixture `luster="荣润"`=0 分且分母只计 v>0（`scoring.py:323`）→ **预计无需改 fixture** |

**双计结论复核**：成立（结构化输入两字段独立；纯文本重复计分为既有已注释局限）。

---

**修订完成 → 可按轮次 1→2→3 执行**（执行前提：kimi 额度；每轮 159 测试全过 + 实测 + diff review + 独立 commit）。

---

## 新增议题：档案解析层失联 → 形状 C（2026-09-17 发现，用户已决策方向）

**发现路径**：K3 轮次 1 审查报告 ④ 项指出"PROMPTS 其余部位键名与 record.py A 路径对不上" → 顺线实证 → 发现更深问题。

**实证事实**：

| 检查 | 结果 |
|---|---|
| `input_validator.py records/daily/2026-08-28_analysis.json` | 判定"形状 B"、**望诊维度覆盖 0/6**（解析不到） |
| 档案形状扫描（60 个） | 仅 3 个 B 形状（06-25/06-29/07-03）；**07-09 之后全部为自由格式**（顶层键 40+ 种；tongue 子键两套风格并存：扁平英文键 vs 自然语言整句） |
| 后果 | `record.py`/`scoring.py`/`confidence.py`/周报 **对 07-09 之后真实数据完全失效**，仅对 `tests/fixtures` 生效 |
| 不影响 | 辨证质量（辨证由 LLM 直接读 observe 输出，不经解析层） |

**用户决策**：方向 **B** = 扩展 record.py 支持实际档案结构（新增"形状 C"），而非改写档案为 B 形状、也非放弃解析层。

**待评估**：C 规范设计（键名/粒度）、实现路线（新增 C 路径 vs C→B 转换层）、自然语言值 + 关键词评分的复用/否定词风险、历史档案迁移取舍、与轮次 2 的先后 —— 已发 K3 征询建议（输出 `/tmp/kimi_shapeC_advice.md`）。

**关键提醒**：形状 C 落地前，轮次 2 的评分层改动（方案 A 等）对实际数据仍是空转 —— 顺序上 C 应优先于轮次 2（待 K3 确认）。
