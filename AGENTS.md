# AGENTS.md — 给在本仓库工作的 AI Agent 的协议

> 本文件是人与多个 Agent（Kimi Code / Kimi Work / 其他）协作的交接协议。
> 任何 Agent 接到本仓库任务时**先读本文档**，再动代码。

---

## 0. 仓库现状

- 版本见根目录 `VERSION`；变更历史见 `CHANGELOG.md`（最新条目与之保持一致，
  pre-push hook 强制）。动手前先读 `README.md` 与 `CHANGELOG.md` 顶部。
  v1.5.0 含一次 breaking change：框架键名去名化（「经方六经辨证」体系），
  接入方与解析层必须按新键名对齐。
- 测试必须全绿（数量随开发变化，不写死——KNOWN_ISSUES #19）。改动完成后运行：
  ```bash
  python3 -m pytest tests/ -q
  ```
  `tests/conftest.py` 的共享 fixture 强制隔离 HOME、模型环境和数据目录；
  新增测试必须使用临时数据与 mock，禁止依赖真实 `.env`、健康记录或外部模型。
- 设计哲学（不可违背）：
  - **诊断体系以《经方探源》为主、《中医诊断学》为辅**（2026-10-21 主人拍板）：
    辨证框架（三观→四证→六病/方证对应/红线）以探源为准绳；中诊只做
    舌象体征的词汇与量化层。新增词条/判据先标出处再入库
    （台账：`docs/VOCAB_PROVENANCE_2026-10-16.md`），不得伪托。
  - `src/` 核心模块（dimensions/indicators/record/observations/scoring/alerts/text_analysis/confidence/governance/retrieval）**仅用标准库**，
    不 import 任何 LLM SDK、不发起 HTTP 请求、不绑任何框架。
  - **未标定辅助模式（2026-10-27 主人定策）**：项目无法取得真实医学标定数据，
    照片体征判读交由用户自配置的视觉模型，welcome 与手册披露非诊断、模型误差和
    人工复核责任；不把医学数据集或医学人员签认作为当前辅助模式的交付前置。
    现有权重/总分/剂量规则仍是未验证经验规则，不得让模型自评充当医学真值。
    医学规则变更须由主人明确决定并写迁移；如未来具备独立标定材料，再按
    `docs/GOVERNANCE_2026-10-27.md` 校验，不能用结构校验或 AI 输出冒充医学批准。
  - 失败要**可诊断**（stderr 告警），不静默吞错；同时正常路径**零告警**。
  - 无遥测、无统计上报。

## 1. 当前任务：Web 前端层（全部 5 切片已合入）

`web/` 目录已建立，做**完整望诊工作流的 Web 入口**。需求经 16 轮决策锁定，
**不要再重新讨论以下条目**；发现硬伤（与代码现实矛盾）时按 §4 上报，不擅自推翻：

进度：切片 1（骨架 + 设置页）、2（记录列表 + 单日详情）、3（修正流）、
4（拍照向导）、5（趋势页 + 辨证报告）已合入 main。
切片规格见 2026-09-30 实现任务书（一日任务书，仅本地，不入库）。

### 产品形态
- 完整工作流在页面上走：拍照/上传（七部位：舌面/舌底/头面/目/耳/手/皮肤）→
  vision 模型识图 → 结构化记录 → 评分 → 辨证 LLM 出报告。
- 使用者是**从 GitHub clone 后自托管的陌生人**，各自配置自己的 LLM key。
  数据一律留本机。

### 技术栈（已定，勿更换）
- 后端 **Flask**（`web/requirements.txt` 独立声明，不污染核心库依赖）。
- 前端 **vanilla HTML/JS + 本地下载的 ECharts**，无 node 构建链。
  **所有 JS/CSS/字体必须 vendor 到本地**——目标环境是局域网，手机不一定能上外网 CDN。
- 视觉：**浅色主题 only**。方向 = 现代暖纸底卡片 + 中医点缀：
  暖纸色背景（`#faf7f1`）、宋体标题、朱砂点缀（`#b0442a`）、
  分数用「彩色徽章 + 进度条」双编码（0 正常绿 `#4d7c58` / 1-3 轻 `#9a7b2d` /
  4-6 中 `#b05e21` / 7-10 重 `#b0442a`）、印章式 logo。
  背景纹理用纯 CSS/SVG data-URI（如 feTurbulence 纸纹），零图片资源。
  （曾出过 4 版风格稿均不满意已废弃，不要沿旧方向，按上面文字规格做。）

### 页面清单
0. **使用前须知页**（`/welcome` 门禁）：GPL 许可 + 免责声明 + 自配模型影响
  三勾选确认，POST 得 cookie 后放行；v1.7.0 合入。
1. **记录列表**（首页）：日历/列表，当日覆盖维度与总分一眼可见。
2. **单日详情**（核心页）：六维观察 + 评分 + 原图对照 + 修正入口。
3. **趋势页**：ECharts 消费 `scripts/generate_weekly_report.py` 里
   `generate_weekly_report_data()` / `extract_tongue_metrics()` /
   `compute_dimension_deviation()` 的 dict 输出（纯函数可 import），
   **不要**服务端生成 matplotlib PNG。
4. **拍照向导**：分步向导（一步一个部位，承载拍摄纪律：舌底禁闪光灯等），
   每步可声明正常、跳过、拒绝或无法拍摄，均写入独立 `declarations`，不写假观察；
   danger_flags 触发时**拦截式提示**。
5. **设置页**：视觉 LLM（`VISION_*`）与辨证 LLM（新增 `LLM_*`）在线配置，
   写回 `.env`（唯一存储）；含连通性测试；首次启动未配置则跳转引导。
   非回环监听必须先设口令（`WEB_ADMIN_TOKEN`），否则拒绝启动。
   局域网在设置页通过 POST 验证后取得会话；未认证时设置页只读，
   记录、趋势和照片均不可读，口令不得放入 URL 或页面脚本。

### 关键语义
- **双模型均可选**（2026-10-23 起，设置页开关写回 .env）：
  - `VISION_DISABLED=1` → 拍照页进**手动录入模式**（全指标选项化录入，
    草稿状态 `manual`，记录打 `manual_entry` 审计；`photo_coverage` 只认
    真实识图）。skip 后改主意允许真实录入覆盖（真实值优先于声明）。
  - `LLM_DISABLED=1` → 详情页报告区改**本地规则速览**（`web/local_report.py`：
    体质格局/四证聚类/饮食宜忌/问诊优先，确定性聚类+项目内置规则映射，
    不读取当前知识库，不构成库内引用，非辨证结论）。
  - 模式语义：启用且配置齐全走模型；关闭走本地；未配置未关闭时，
    记录已有模型期内容照旧展示、全无则走本地。
  - 设置页表单用隐藏标记 `FORM_VISION/FORM_LLM` 识别来源（BASE_URL 被
    环境变量锁定时输入框 disabled 不提交，不能靠它判断表单）。
- **修正**：改观察值 → 自动重评分 → 覆盖保存，旧版自动备份到 `records/_backup/`，
  JSON 里打 `manually_corrected: true` + 时间戳。保存前必须复用
  `scripts/input_validator.py` 的 `validate_record()`。
- 记录形状有三种（A 中文键 / B `observations` / C 顶层英文键），
  `DailyRecord` 自动识别；**写回必须形状感知**（路径以 `src/indicators.py` 注册表为准）。
- 新记录推荐形状 B v2（`schema_version=2`）：`observation_meta` 保存采集来源/
  方式/raw/certainty/evidence/value，`declarations` 与观察分离，`derived_meta`
  随输入变化重算；无比例尺/未暴露只记 unknown，不计真实覆盖。
- 辨证报告存进记录 JSON（形状 A 的 `diagnosis` 约定）+
  记 `prompt_template_version`。
- 当日已有记录再走向导：给「补充未覆盖维度 / 重新分析（旧版自动备份）/ 取消」三选。
- 照片存 `records/photos/<日期>/<部位>.jpg`（不入 git），详情页展示原图供肉眼复核。
- 服务**默认绑 127.0.0.1**，显式开关才绑 0.0.0.0。
- 空库首次启动提供「载入示例数据」按钮（`tests/fixtures/2026-06-25_analysis.json`
  可作 demo，其 `formula` 是合成数据）。

## 2. 协作规则（多 Agent 共用本仓库）

1. **分支隔离**：每个任务一条分支，命名 `feat/…` / `fix/…` / `docs/…`，
   完成后合并回 main。**同一时刻只允许一个 Agent 在本工作区干活**；
   需要并行时用 `git worktree add ../tcm-<任务> -b <分支>`。
2. **动仓库前先** `git status -sb` + 读 `docs/KNOWN_ISSUES.md`，
   确认没有别人留下的半成品。
3. **声称完成的标准**：`pytest tests/ -q` 全绿 + 真实调用路径跑通
   （不是只编译/导入成功）。做不到的不要标完成。
4. **提交风格**跟随仓库历史：`fix(scope): 中文描述`（conventional commits）。
   只 commit 相关文件；`records/`、`charts/`、`.env` 永不在提交内。
5. **改了文档描述的行为，同步改文档**；新增已知问题要更新 `docs/KNOWN_ISSUES.md`
   （其维护约定见该文件附录）。
6. 不擅自升级核心库（`src/`）的对外契约；确需变更时先在 `docs/` 写清动机与迁移说明。
7. **一日任务书不入库**：跨 Agent 派工单（`docs/*_TASK_*.md`）只供本地使用，
   已入 gitignore；完成后由 CHANGELOG 吸收其实质内容。写任务书时在文首注明
   「仅本地使用，不要提交进 git」。

## 3. 常见坑（前人以身试法）

- v1.5.0 键名已换：按旧键名写代码会静默落空——先用 `DailyRecord` 的形状探测确认。
- 评分词表外的措辞在新 `assess*` 接口返回 `unknown`（旧 `score*` 为兼容仍返回 0）：
  接视觉模型的 prompt 必须使用 `src/indicators.py` 注册表的封闭词表
  （评分规则见 `src/scoring.py`），换模型必须重新标定。
- 新预警用 `src.alerts.evaluate_alert(s)` / `danger_flags_for()`：`screening` 不等于确诊，
  `unknown` 不等于 `not_triggered`；旧 `detect_danger()` 空列表不代表已排除。
- `.env` 严格按 UTF-8 读取（允许起始 BOM），引号与转义需读写一致；非法换行拒绝。
  完整读—改—写—回读使用线程/进程锁，知识库导入、重置与模式切换共用同一配置锁。
  Web 每请求只取一次配置快照，禁止用 `os.environ + importlib.reload` 传模型配置；
  `VISION_BASE_URL` 必填，不再回退默认第三方端点。私有历史配置路径须显式 opt-in。
- 模型出站统一走 `web.safe_fetch`：仅 HTTP(S)、同源重定向、响应限量和总时限；
  已存 key 只在同源端点复用。测试 mock `web.safe_fetch.urlopen`，默认拒绝未 mock HTTP。
- 记录/草稿写回必须携带同次读取的文件版本，经 `io_utils` 条件写入/删除；
  多文件事务在同一 `write_lock` 中完成。版本冲突返回 409，不得裸 `os.replace`
  覆盖目标；详见 `docs/MIGRATION_2026-10-27_KNOWN21.md`。
- 问诊统一经 `DailyRecord.get_inquiry_answers()` 读取，契约总数为 17；观察写入复用
  `records_store.validate_field_value()`，正式清空用 `action=clear` 并留修正审计。
  识图异常类型/词表外值保留 `_raw` 并列 `_type_errors`，注记单独放 `_notes`；不得转成已确认观察。
  文本规范化走 `src/textnorm.py`，不对整串盲目 NFKC。详见 `docs/MIGRATION_2026-10-27_B14.md`。
- 医学安全校验必须覆盖 `DailyRecord.get_formula_material()` 的结构化方剂与报告段落；
  LOW 禁具体方剂，非 HIGH 禁具体剂量。Web 写入口不得按 emoji 过滤 errors；
  `records_store.validate_candidate()` 传入 `previous_raw`，只阻断本次新增错误，存量错误转 warning。
  A/B 混合 `danger_flags` 读取取并集但写入校验拒绝。详见 `docs/MIGRATION_2026-10-28_B13.md`。
- 红线裁决统一走 `src/danger_review.py`：`danger_token` 绑定当前触发与证据，
  首次/过期确认返回 409；`dismiss` 不等于 `not_triggered`，`clear` 只在证据消失时追加。
  merge 不允许 dismiss 未触及旧项；裁决历史纳入报告指纹。详见 `docs/MIGRATION_2026-10-28_B15.md`。
- 恢复只走当前代 pristine 与 restore 安全备份，不按本地时间选最早备份；报告保留。
  上传必须经 `photo_store` 清洗并暂存，提交成功才转正并备份旧图，禁止直接 `file.save` 覆盖。
  普通备份按每日 20 份保留，删除必须管理员 POST `confirm=DELETE`，同时清理关联数据。
  锁按目录生效，不能嵌套不同目录写锁；跨目录提交要可回滚。详见 `docs/MIGRATION_2026-10-28_B16.md`。
- 知识库检索用户输入必须走 `retrieve()`（内部 re.escape）；`search()` 吃原始正则。
  KB_ROOT/词典与索引缓存共用归一化路径；RAG 低分噪声不返回，AND 按真实文件复核。
  选档统一走 `src/daily_files.py`，副本与特殊路径共用 scandir；首页限量摘要、月历
  复用按文件签名失效的缓存。week_id 用滚动窗口起止日期，正常 0 不等于无观测。
  详见 `docs/MIGRATION_2026-10-28_B17.md`。
- 前端请求须检查 HTTP/JSON/重定向并显示失败；设置开关走 `/settings/toggle`，不携带
  整张表单。上传回调固定发起部位，识图与提交有在途锁；warnings 用 sessionStorage
  一次性传入详情页。问诊再次点击已选项只撤销该题。窄屏轨道保持 minmax(0,1fr)，
  ECharts 随窗口 resize；原生 dialog 不加冗余角色/手工焦点陷阱。
- `TCM_TIMEZONE` 由 `web/time_utils.py` 用 ZoneInfo 解析；Web 从当前配置快照传入写入口，
  新时间戳带偏移。向导 POST 固定草稿日期，仅恢复已存在且不超过一天的草稿；提交按
  草稿日期。连续记录从今天/昨天起算并排除未来日期。详见 `docs/MIGRATION_2026-11-03_B18.md`。
- Web 模块统一使用顶层导入（`import records_store` / `from safe_fetch import …`），
  禁止混用 `web.records_store` / `from web import …`，避免双模块实例导致 mock、缓存和配置分叉。
  `lifecycle_store.py` 仅属于 Web 层，路径为 `web/lifecycle_store.py`。
  知识库路由在 `web/kb_routes.py`；候选检索在 `web/kb_evidence.py`；报告生成在
  `web/report_store.py`；`web/trends_store.py` 只保留周报实现和兼容转发。
- Web 所有请求先校验 Host；写请求要求与当前请求同源，或凭有效会话兼容传统浏览器；
  `/welcome` POST 测试需加 `Origin: http://localhost`。局域网口令只走
  `/settings/login` POST，勿放入 URL/JS；非回环无口令配置必须拒绝。
- 视觉端点 temperature 有服务端下限（如 DashScope 钳到 0.6），传 0 ≠ 确定性输出。
- 部署使用 `web/server.py` 的 Waitress（8 线程、64 连接、通道超时 300 秒、backlog 32）；
  依赖只在 `web/requirements.txt` 声明，不污染核心库。同日报告经 `trends_store` 非阻塞锁
  去重，生成中返回 409，异常释放锁。通道超时不替代模型总时限。
- 知识库已公私分离：原内容完整保留在仓库外的私有目录，公开仓仅保留配置说明。
  通过 `TCM_KB_ROOT` 指向有权使用的目录；测试只用 `tests/fixtures/knowledge_base/` 合成资料，
  不依赖私有副本。公开历史按 F90 接受并登记，不重写、不 force push；远端可见性另行处理。
  图片按主人决定保留现版，不强制 AI 标识/C2PA。分离迁移见
  `docs/MIGRATION_2026-11-03_KB_SPLIT.md`，逐项闭环见 `docs/REVIEW_CLOSURE_2026-11-03.md`。
- 知识库分 `constitution`（中医体质辨证）、`diet`（食疗）、`formula`（方剂）三类。
  专用变量分别为 `TCM_KB_CONSTITUTION_ROOT`、`TCM_KB_DIET_ROOT`、`TCM_KB_FORMULA_ROOT`，
  新 clone 默认不读取外部旧库，程序管理的 `private_kb/` 副本自动启用；
  `TCM_KB_STRICT_CATEGORIES=1` 禁止综合回退，默认关闭。分类 ZIP 必须含 `kb.yaml`（`schema_version: 1`、匹配 `category`），
  导入只覆盖 `<TCM_DATA_ROOT>/private_kb/<类别>/`，**严禁移动、覆盖或删除其他类别或外部原库**。
  设置页在分类卡片后的综合知识库折叠卡片内提供综合导入及分类模式控件，默认折叠，用于调试及保证兼容性；`composite` 导入仍写 `TCM_KB_ROOT`，替换综合副本时保留分类子目录，拒绝保留目录名，成功后刷新页面同步回退状态。
  配置写回失败须同时回滚 `.env` 和目录。自建格式见 `docs/KB_AUTHORING.md`；自定义内容只影响
  检索与候选参考，不改医学规则、不是训练。
- 分类重置只处理 `<TCM_DATA_ROOT>/private_kb/<类别>/`，禁止按当前配置根删除外部目录。
  `TCM_KB_<类别>_DISABLED=1` 优先于综合回退，重置后对应信息不可显示。每次新 ZIP 完整校验后
  重置本类旧副本并清除停用；配置失败按事务前字节恢复配置与目录。重置备份只放
  `.kb-reset-backup-*`，不得提交。
- Web 报告必须从同次 `cfg` 快照显式传递各类根，统一经 `inspect_kb_categories()` 获取状态；
  报告保存 `kb_categories` 及兼容字段，任一类根/版本变化触发过期。`kb_refs` 只是候选参考，
  不等于模型实际引用。缺体质库隐藏体质/辨证内容，缺食疗库隐藏饮食，缺方剂库隐藏方药及
  完整方药报告；即使旧记录已有内容也不得绕过。缺方剂时的方名/剂量、缺食疗的结构化饮食、
  缺体质的结构化辨证输出还须写入前拒绝，不能只靠 prompt。本地速览使用内置规则计算，但只有
  对应类别 `ready` 才展示。无库/无命中/失败必须在模型输入和页面披露。
  类别未配置或停用时状态根为空，不得把被忽略的外部旧根显示为当前目录。
  B25 部署验收与配置并发修复见 `docs/MIGRATION_2026-11-04_B25.md`。

## 4. 与「另一个 Agent」的交接方式

- 跨 Agent 的长期决策**落盘到 `docs/`，不落对话**。对话记忆只属于单个 Agent。
- 发现协议与现实矛盾（本文档写错了、需求与代码冲突）：
  在本文件对应小节末尾加「⚠ 待裁决」标注并写明证据，不要静默按错的做。
