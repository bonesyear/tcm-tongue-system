# 任务书：实现望诊 Web 前端工程（移交 Kimi Code）

> 日期：2026-09-30 ｜ 委托方：主人 ｜ 撰写方：Kimi Work（页面设计已完成并合并入 main）
> 你的任务：**把 `web/design/` 的静态设计稿实现为可运行的 Flask Web 工程**。
> 设计稿是**规格**，不是参考风格——版式、配色、组件、交互语义以其为准，不要重新设计。

---

## 0. 开工前必读（按顺序）

1. `AGENTS.md` —— 仓库协作协议。§0 设计哲学、§2 协作规则、§3 常见坑**全部适用**于你。
2. `docs/web-design-handoff.md` —— 设计交接规格：文件清单、设计令牌表、
   **页面 → 数据源映射**、锁定交互语义、ECharts 配置要点、验收状态。
3. `web/design/README.md` + `web/design/pages/*.html` —— 五个页面的成品 mockup，
   `web/design/previews/` 有实测渲染截图（目标效果以截图为准）。
4. `docs/KNOWN_ISSUES.md` §5 —— 判读陷阱表，其中「值夹带注记」「点刺/腻腐需肉眼」
   「闪光灯禁令」等直接影响 UI 文案与交互。

---

## 1. 技术栈与硬约束（锁定，勿更换）

- 后端 **Flask**，依赖独立声明在 `web/requirements.txt`，**不污染根目录核心库依赖**。
- 前端 **vanilla HTML/JS + 本地 vendor 的 ECharts**（`web/design/vendor/echarts.min.js`
  已备好，拷入 `web/static/` 使用），**无 node 构建链**；所有 JS/CSS/字体必须本地化
  （目标环境是离线局域网，手机无外网 CDN）。
- `src/` 核心模块只读消费（`DailyRecord` / `scoring` / `dimensions` /
  `scripts/generate_weekly_report.py` 的纯函数），**不得修改其对外契约**；
  确需变更时先按 AGENTS.md §4 在 `docs/` 写动机与迁移说明，落盘上报，不擅自改。
- 服务**默认绑 127.0.0.1**，显式开关才绑 0.0.0.0；无遥测、无上报，数据全留本机。
- 配置唯一存储 = 项目根 `.env`；读写注意 **`.env` 是「原始 bytes → 严格 UTF-8」解码**，
  不要用平台默认编码重开文件（会产生告警）。

## 2. 视觉与组件（锁定）

- 浅色主题 only；色板/字体/圆角/阴影/纸纹**只允许消费** `web/design/assets/tokens.css`
  的 CSS 变量（暖纸 `#faf7f1`、朱砂 `#b0442a`、分数四级 `#4d7c58/#9a7b2d/#b05e21/#b0442a`），
  实现时把 `tokens.css` + `base.css` 拷入 `web/static/` 演进，禁止另起色值。
- 分数一律**双编码**：彩色徽章 + 同色进度条（0 正常 / 1–3 轻 / 4–6 中 / 7–10 重）；
  「未覆盖/无数据」用虚线灰徽章，与 0 分严格区分。
- 页面节奏用 `.stack` 容器（base.css），不写裸 spacer div。
- 印章式 logo 为内联 SVG；背景纹理为 CSS/SVG data-URI，**零图片资源**。

## 3. 页面清单与数据源（详见交接文档 §3，此处为纲要）

| 页面 | 模板来源 | 关键数据源 |
|---|---|---|
| 记录列表（首页） | `pages/index.html` | 逐日 `DailyRecord` + `compute_dimension_deviation()`；空库显示「载入示例数据」 |
| 单日详情 | `pages/record.html` | `DailyRecord` 三形状自动识别；`src/scoring.py` 评分；原图 `records/photos/<日期>/<部位>.jpg`；辨证报告存记录 JSON（形状 A `diagnosis` 约定）+ `prompt_template_version` |
| 趋势 | `pages/trends.html` | **只用纯函数 dict**：`generate_weekly_report_data()` / `extract_tongue_metrics()` / `compute_dimension_deviation()`，禁止服务端 matplotlib |
| 拍照向导 | `pages/wizard.html` | 七部位分步；vision 识图走 `scripts/vision_client.py`（封闭词表 prompt，与 `src/scoring.py` 逐键对齐） |
| 设置 | `pages/settings.html` | `VISION_*` 现状键名（见 `scripts/vision_client.py`）+ 新增 `LLM_*`；连通性测试；`WEB_ADMIN_TOKEN` |

## 4. 关键语义（锁定，逐条落实）

1. **修正**：改观察值 → 自动重评分 → 覆盖保存；旧版自动备份 `records/_backup/`；
   JSON 打 `manually_corrected: true` + 时间戳；**保存前必须过**
   `scripts/input_validator.py` 的 `validate_record()`。
2. **形状感知写回**：记录形状有三种（A 中文键 / B `observations` / C 顶层英文键），
   读取靠 `DailyRecord` 自动识别；**写回必须保持原形状**（参考 `src/record.py`
   `_DIMENSION_INDICATORS`）。新记录一律写形状 B。
3. **降级字段**：`prickles`（点刺）、`palm_temp`（掌温）已退出评分层——UI 展示为
   「参考项」，不打分、不入总分；识图值需用户肉眼确认（文案见 mockup）。
4. **双跳过**：「跳过（声明正常）」计入覆盖度 /「跳过（未覆盖）」不计分；
   均须显式标注，**绝不伪造观察值**。
5. **danger_flags 拦截式弹层**：九项键名/中文名/禁忌文案字典在
   `web/design/assets/mock-data.js` 的 `DANGER_FLAGS`（键对齐
   `templates/multi_dim_record_template.json`）；两出口：「误判去修正」「已复核保留警示」。
6. **当日已有记录再走向导**：三选「补充未覆盖维度 / 重新分析（旧版自动备份）/ 取消」。
7. **设置页**：首次启动未配置 `VISION_API_KEY` → 跳转引导；局域网访问未设
   `WEB_ADMIN_TOKEN` 时设置页只读。
8. **总分口径**（设计新增，主人已认可）：列表/日历「总偏离度」= 六维之和（0–60），
   等级色按均值（÷6）映射四级。

## 5. 切片顺序与验收（每片独立提交，保持测试全绿）

| # | 分支建议 | 内容 | 验收 |
|---|---|---|---|
| 1 | `feat/web-skeleton` | Flask app 骨架、`web/requirements.txt`、vendor 静态资源、基础模板（tokens/base 拷入）、**设置页**（.env 读写、连通性测试、首启引导、局域网只读） | `pytest tests/ -q` 294 全绿；`flask run` 起服务，设置页真实写入 `.env` 并可读回；未配置时访问首页跳转设置 |
| 2 | `feat/web-records` | 记录列表 + 单日详情（只读）：三形状识别、六维卡、原图对照、辨证报告展示、安全红线横幅 | 用 `tests/fixtures/2026-06-25_analysis.json` 载入后能完整展示；空库出「载入示例数据」 |
| 3 | `feat/web-correction` | 修正入口：行内编辑、validator 拦截、形状感知写回、自动备份与 `manually_corrected` | 对 demo 记录改一个字段：旧版进 `_backup/`、JSON 打标、页面分数随之重算；非法值被 validator 拦下 |
| 4 | `feat/web-wizard` | 拍照向导 + vision 识图：分步、双跳过、照片落盘 `records/photos/<日期>/`、danger 拦截弹层 | 走完整向导生成一条形状 B 记录；人为构造触发 danger_flags 的响应对拦截弹层截图验证 |
| 5 | `feat/web-trends` | 趋势页（ECharts 接纯函数 dict）+ 辨证 LLM 报告生成与写回 | 趋势页图表与 mockup 一致；报告写入记录 JSON 且带 `prompt_template_version` |

**通用完成标准**（AGENTS.md §2.3）：`pytest tests/ -q` 全绿 **且** 真实调用路径跑通
（起服务、浏览器走一遍），不是只编译/导入成功。

## 6. 提交与卫生

- 提交风格 `fix(scope): 中文描述` / `feat(scope): …`（conventional commits，跟随仓库历史）。
- 只 commit 相关文件；`records/`、`charts/`、`.env` **永不提交**。
- `records/photos/` 不入 git（确认 `.gitignore` 覆盖，缺则补）。
- 每片完成后合并回 main；同一时刻只允许一个 Agent 在本工作区干活。
- 新发现的坑或与本任务书矛盾之处：按 AGENTS.md §4 处理——更新 `docs/KNOWN_ISSUES.md`
  或在对应文档加「⚠ 待裁决」标注并写证据，**不要静默按错的做**。

## 7. 明确不做

- 不重新设计视觉（前 4 版风格稿已废弃，主人已对当前设计稿验收签字）。
- 不引入前端框架 / 构建链 / CDN 外链。
- 不改 `src/` 契约、不动 `tests/` 断言语义。
- 不做移动端 App、不做多用户与账号体系（自托管单用户，局域网口令已是全部边界）。
