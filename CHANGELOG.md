# 更新日志

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
- **风险 B（版权）**：《经方探源》全文 `jingfang_tanyuan_full.md` 从备份
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
  - 问诊项：15 项许家栋六病辨证核心问诊骨架，全部可跳过
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
- 新增 knowledge_base/diet-lifestyle/diet-therapy.md：基于许家栋《经方探源》体系的食疗方案（四气五味概述、九种体质食疗映射、药物与食物禁忌、六病代表方饮食建议）
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
- 基于许家栋经方学术体系的三观→四证→六病辨证路径
- 支持舌诊/面诊/目诊/手诊/皮肤诊/唇口诊多维度照片采集
- Doubao 视觉模型部位识别+望诊分析
- DeepSeek V4 自适应辨证引擎（LOW/MEDIUM/HIGH 三档置信度）
- 周报趋势分析（舌象雷达图、关键指标趋势线）
- 飞书机器人集成
