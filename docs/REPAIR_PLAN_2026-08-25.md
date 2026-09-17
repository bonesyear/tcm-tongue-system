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
- ✅ **轮次 2 完成**（2026-09-17，commit `cbbd58f`）：辨证层 #5/#8/#9/#10/#12/#16 + 方案 A 项 2~11 + 新增 #19（`_match_score` 平局取最高分）→ **198 passed**（191+7）｜8 项实测逐条通过｜ruff `F,E722` 全过｜独立 diff 审查通过
  - 实测：`湿润偏滑`→**7**（原 0）/ `湿润`→0 / `滑燥并见`→8 / `苔润不燥`→0｜`非典型黄染`→**7**（不再被"非"误否定）/ `无黄染`→0｜`含桂枝10g`/`小柴胡汤加减`→True 而 `今日复诊, 无方`→False（无误报）｜形状 A 缺键→`{}`｜`HIGH1`/`HIGH_2`→None｜danger_flags 字符串 `"true"`→`['daiyang']`｜形状 A `舌质润燥`→`偏干`｜`body_luster` 不在 rules 且 `TONGUE_BODY_LUSTER_MAP` 已删
  - **端到端回归**：8/28 真实 C 档案舌诊分 **5.5 → 6.0**（`coating_moisture`=7 生效，湿盛信号不再被掩盖）✅
  - **取舍记录（#5 副作用）**：`非黄染` 字面=无黄染，但移除"非"后按 fail-loud 判为 **7 分**（异常）。**写作规范**：否定一律用「无/不/未/没」，**不要写"非"**（档案值避免"非典型X"式表述）
  - **新发现（既有词表缺口，非本轮引入）**：`body_color` 的 `"红": 7` 使正常描述 **"红润" 被判 7 分**（`"红润"` 不在 map，靠"红"命中）。`"淡红"`→0 不受影响（最长匹配优先）→ **写档案用"淡红"，勿写"红润"**；是否补 `"红润": 0` 词条待轮次 3 一并定
- ⏳ **轮次 3（原"文档层"已取消并入轮次 2）**：见文末「轮次 3：评分覆盖扩展」（K3 建议，待用户签分值）

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

**待评估**：C 规范设计（键名/粒度）、实现路线（新增 C 路径 vs C→B 转换层）、自然语言值 + 关键词评分的复用/否定词风险、历史档案迁移取舍、与轮次 2 的先后 —— **已发 K3 征询建议（2026-09-17，报告 `/tmp/kimi_shapeC_advice.md`），采纳要点如下。**

**关键提醒**：形状 C 落地前，轮次 2 的评分层改动（方案 A 等）对实际数据仍是空转 —— **顺序：C → 历史迁移 → 轮次 2**（K3 确认）。

### K3 建议（已决议采纳，实施以此为准）

**① C 规范：扁平版，键名严格复用 `_DIMENSION_INDICATORS` 的规范指标名**

- 维度顶层键用规范英文名：`tongue`/`head_face`/`eye`/`ear`/`hand`/`skin`（与 `VisionDimension.english_name` 一致）；`face`/`palm` 仅作**兼容别名**
- 指标键 = 规范指标名（`body_color`/`tooth_marks`/`body_size`/`coating_thickness`…），**不是** `body_shape`/`teeth_marks`（历史漂移勿沿用）
- **HEAD_FACE 必须带前缀**（`face_color`/`lip_color`/`nose_color`）——该维度跨面/唇/鼻三子域，省前缀会撞名
- C 路径因此是**恒等映射**：`"C": ["body_color"]`
- 粒度：值为**当前状态短语**；**历史对比/括号夹注不进指标值**（放 `lessons` 或 `*_note`）
- 缺失维度不写该键（与 `is_covered`、`_dig` 缺失即空串天然兼容）

**② 实现路线：原生加 C 路径，不写转换层、不动 vision_client**

- `_DIMENSION_INDICATORS` 每指标加一行 `"C": [指标名]`（≈40 行机械改动）；`get_observation` 的回落链（record.py:242）天然支持三形状
- 形状检测（record.py:188-196）：`observations`→B；`doubao_vision_analysis`→A；否则顶层含任一维度键（含别名）→C；都没有→维持默认 B
- `_dimension_root`（record.py:214-229）加 C 分支 + 别名 `{face→head_face, palm→hand}`
- `get_pattern_differentiation` 认 `pattern_update`；`get_formula` 加别名列表（`formula_adjust`/`formula_with_dosage`）
- ⚠️ `get_inquiry_coverage`（record.py:308-325）需 C 分支：C 的 `inquiry` 是 `{问题: 回答字符串}`，现有 `item.get("asked")` 会算成 0，应按"**非空字符串值计数**"
- validator：`_DICT_FIELDS`（input_validator.py:45-47）补 `tongue`/`head_face`/`eye`/`ear`/`hand`/`skin`/`pattern_update`

**③ 评分可行性（已推演）**：`'边缘轻度齿痕(无明显加重)'` → 最长匹配"轻度"(2字) > "无"(1字)，前置小句无否定词 → 命中 4 分，**不误杀** ✅
- 但两条边角风险须入测试：①夹注若写"前期重度→现轻度"会命中"重度"=7 **高估**（→ 这就是"值只写当前状态"约定的理由）②"稍腻"别塞进 `coating_moisture`（低估，fail-safe 可接受）

**④ 步骤**：record.py → validator → 模板/文档 → 测试（新 fixture + 检测优先级/别名/08-28 真实值三条断言/inquiry 扁平计数/pattern_update/端到端 validator）
**④ 风险**：07-09 后档案多数**无 `danger_flags`**，现有 validator 缺失放行（打印"✅ 无触发"）→ C 落地后在真实档案首次暴露，建议至少加 warning

**⑤ 历史迁移**：**用户决策（2026-09-17）：不做迁移**——旧档案不为 C 做兼容，C 只对 2026-09-17 起的新档案生效；旧档案保持原样不删除（临床健康记录），但沿用既有"系统解析不到"状态。后果：周报趋势在 07-09~09-17 段断档（用户接受）。
  - K3 原建议备查：手工逐份改（8 份）优于通用脚本（三种样式各异 + 整句拆分需医学判断）
**⑥ 顺序**：C → 历史迁移 → 轮次 2；方案 A 项 2（`舌质荣枯`→`舌质润燥`）落地时 **C 的 `body_luster` 路径须同 commit 对齐**
**工作量**：约 **1-1.5 个工作日**（record.py+validator 120-180 行 0.5 天 / 测试 0.5 天 / 模板文档 0.5 小时 / 迁移 1-2 小时）

### 端到端验证发现（2026-09-17，8/28 档案按 C 规范重写后实测）

**验证结果**：档案重写为 C 后 → validator 形状 C / 覆盖 6/6 / 问诊 5/5 / **0 错误 0 警告**；评分链路通（舌诊 5.5 分、置信度 HIGH、allows_formula=True、辨证与方剂可读）✅

**但实测抓到两个 K3 静态分析未发现的问题**：

1. **同长度关键词取首词 → 湿盛信号被掩盖（评分低估）**
   - 现象：`coating_moisture="湿润偏滑"` → **0 分**（对照：`"滑"`→7 分 ✅、`"湿润"`→0 分）
   - 根因：`scoring.py:265` `len(kw) > len(best_kw)` —— 同长度时取 dict 遍历**最先**命中的词；TONGUE_MOISTURE_MAP 中 `"润":0` 先于 `"滑":7` → "润"胜出
   - 影响：**湿盛（滑=7）系统性被正常（润=0）掩盖**——对湿盛型舌象（苔偏滑）正是关键信号
   - 处置建议：**轮次 2 增加条目**——同长度时取**最高分**（或按 map 严重度排序），而非遍历首词
2. **9 个舌部指标不参与评分（既有设计缺项）** ⚠️ 原稿误列 `coating_thickness`（K3 实证纠正，见下）
   - 实证（`scoring.py:140-150`）：`DIMENSION_RULES[TONGUE]` 含 **9** 个指标 —— body_color / **coating_thickness** / coating_moisture / tooth_marks / petechiae / sublingual_varicosity / fissure / body_size / body_luster；舌部指标实为 **18** 个（`record.py:47-66`）
   - **无规则 9 个**：`coating_color` / `coating_greasy` / **`coating_peeling`** / `coating_distribution` / `prickles` / `body_dynamics` / `sublingual_color` / `sublingual_thickness` / `sublingual_petechiae`
   - 影响：**剥落斑（随访对象[REDACTED]的核心观察点）在评分与周报趋势中完全不体现**
   - **K3 意见（2026-09-17，报告 `docs/K3_SCORING_ADVICE_2026-09-17.md`）**：**应补**。统一原则 = 「评分层只收**静态照片可客观判读**的指标；需动态观察或对光线敏感的主观判断降级到辨证层」——方案 A 是该原则的**减法**（移除 body_luster），发现 2 是**加法**（补 7 个形态指标），`body_dynamics` 排除是同一原则的**对称应用**（静态照片判不了舌体动态），三者互不冲突
   - 处置：**单列轮次 3「评分覆盖扩展」**（map 草稿见 K3 报告 ② 节；分值需用户临床签认后执行）
   - **回归冲突点（K3 实证指出，执行时必须处理）**：`tests/test_scoring.py:130-132` 的 `test_tongue_score_sparse_not_diluted` 用纯文本 `"青紫"` 断言 `score==10`；若 `sublingual_color` 收 `"青紫": 8`，纯文本输入下两指标同命中 → 均值 9.0 → 测试红。**解法（K3 倾向 ①）**：① 该测试改结构化 dict 入参（"稀疏不稀释"用 dict 表达更准）；② map 不收"青紫"仅收"紫暗/瘀紫"。另：`test_normal_tongue_scores_zero` fixture 补新指标正常值；周报 fixture 期望分（`test_weekly_report.py:49-50` 期望 5.5）若文本含"腻/剥/黄"会变 → 跑全量核对后更新期望并注明"评分口径扩展导致的历史期望变化"。

---

## 轮次 3：评分覆盖扩展（K3 建议 2026-09-17，待用户签分值）

**前置**：轮次 2 完成（方案 A 先落地，同区域编辑避免冲突）→ 本平台。

**统一原则（写入代码注释与文档）**：评分层只收**静态照片可客观判读**的指标；需动态观察或对光线/拍摄条件敏感的主观判断，降级到辨证层。

### 3.1 `_match_score` 平局规则（发现 1）

`src/scoring.py:260-267` —— 同长度关键词取**分值最高者**（fail-loud：宁可高估不漏估）：

```python
if best_kw is None or len(kw) > len(best_kw) \
        or (len(kw) == len(best_kw) and rules[kw] > rules[best_kw]):
```

K3 已对全部 13 个 map 做平局共现审计：仅两类场景（正常词+异常词并存 → 取高分正确；两个不同异常词并存 → 只见于历史夹注这一数据违规）→ **无新增误判**；现有测试无"同长度双命中"构造 → 预计零回归。备选（map 显式排序/关键词权重/字段枚举化）均劣于改算法（K3 评估）。

### 3.2 新增 7 个指标评分规则（K3 map 草稿，待临床签认）

| 指标 | map 草稿（0=正常基线，越高越异常） | 依据 |
|---|---|---|
| `coating_peeling` | `{"剥落":6,"剥脱":6,"花剥":6,"地图舌":7,"镜面":9}` | **最高优先**（随访对象[REDACTED]核心观察点）；结构性形态，静态照片完全可判 |
| `coating_greasy` | `{"稍腻":3,"腻":5,"厚腻":8,"腐苔":7}` | 苔质附着形态可判；"不腻"由否定守卫归零 |
| `coating_color` | `{"白":0,"黄":3,"灰":6,"黑":7,"灰黑":8}` | 颜色是最可靠维度（"灰黑"靠最长匹配压过"灰"） |
| `prickles` | `{"点刺":5,"芒刺":6}` | 凸起红点，分辨率敏感 → 分值保守 |
| `sublingual_color` | `{"淡紫":0,"紫暗":6,"青紫":8}` | 前提=拍了舌下照（注意上方回归冲突点） |
| `sublingual_thickness` | `{"增粗":5,"怒张":7}` | 粗细形态可判 |
| `sublingual_petechiae` | 复用 `PETECHIAE_MAP` | 零新增成本 |

**仍排除**：`body_dynamics`（静态照片不可判，与方案 A 同原则的对称应用）、`coating_distribution`（异常语义已被 peeling/thickness 覆盖，边际价值低）、`body_luster`（方案 A 已定移除）。

### 3.3 雷达图

`TONGUE_RADAR_METRIC_KEYS`（`scoring.py:188-197`）增加 `"舌苔剥落": "coating_peeling"` → 8 轴变 9 轴，同步周报模板（`generate_weekly_report.py:141-162`）与图表说明。理由：否则剥落只在维度均分里体现，趋势图仍看不到这个核心观察点。

**工作量**：3.1 ≈ 0.5-1 小时（1 行 + 4-6 测试）；3.2+3.3 ≈ 1 个工作日（7 map + 雷达/周报 + 15-20 测试 + fixture 核对 + 全量回归）+ 临床签认时间。

**历史趋势断点**：口径扩展后旧分与新分不可直接比较（8/28 档案 5.5 → 预计 6.5+，因 `湿润偏滑`→7、剥落→6 生效）。**用户决策（2026-09-17）：老档案不用在意** → 不做口径变更标注、不追溯重算、周报按新口径自然输出。

---

## 轮次 2 后深查发现（2026-09-17，用户追问"有遗留问题吗"）

### 已修（本轮自查发现并修复）

**备份文件污染周报** —— 重写 C 档案时创建的备份 `records/daily/2026-08-28_analysis.v1.bak.json` 被 `generate_weekly_report.py:112,121` 的 `glob("{date}*analysis*.json")` + `sorted()[-1]`（"取字典序最新"）选中（`v1.bak` 字典序排在 `analysis.json` 之后）→ 周报读到**旧格式档案**：舌诊偏离度 **0.0**（应 6.0）、误报 `safety_violation: "LOW 置信度下不应输出方剂"`。
**已修**：备份移至 `records/_backup/2026-08-28_analysis_v1_旧格式.json`（非 `.json` 结尾 + 移出 daily）→ 重跑周报验证：偏离度 **6.0**、`claimed=HIGH/covered=6/consistent=true`、无 safety_violation ✅

**根因是系统缺陷（未修，建议新增条目）**：周报 glob 过宽 + "字典序最新"启发式脆弱——任何同日期前缀的 json（`.bak`/副本/中间文件）都会参与竞争且可能胜出。建议：① 优先精确匹配 `{date}_analysis.json`；② 排除 `*.bak*`/`*copy*`/`*tmp*`；③ 多份命中时**打印警告**而非静默选一。

### 轮次 1 审查遗留 3 点（K3 提过、尚未处置；非轮次 2 引入）

1. `vision_client.py:122` **observe 无效 part-key 静默回退**（`PROMPTS.get(part, PROMPTS["其他"])` 无警告）——K3 建议打印可用类别列表
2. `tests/test_vision_client.py` 缺 **JSONDecodeError / timeout 用例**；"舌质润燥"键名指令**零测试**
3. 其余 6 部位（舌底/头面/目部/耳部/手部/皮肤）**PROMPTS 未声明键名** → 与 `record.py` A 路径键名不保证对齐。**影响已降低**（形状 C 落地后档案由 assistant 按 C 规范手写，observe 输出仅供辨证参考）；若将来做"observe 输出自动转档案"必须先修

### 既有、按决策不动

- 旧档案 validator `rc=1` 共 8 个（覆盖 0/6、置信度声称与实际不符）——"老档案不用在意"，不迁移
- `body_color` 词表缺口 `"红润"` → 7 分（既有，非本轮引入）→ 轮次 3 一并定
- 档案计数口径：`records/daily/*_analysis.json` 顶层 **11** 个（另有子目录/图片，`records` 未纳入 git 无法用 git 复核）；曾记"60 个"疑为含图片与子目录的口径，**无删除痕迹**
