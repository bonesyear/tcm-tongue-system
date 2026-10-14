# 任务书：Web 端接入《使用手册》入口（/guide 路由 + 三处链接）

> 日期：2026-10-14 ｜ 设计已定稿，实现照做即可；发现与代码现实矛盾时在本文件末尾加「⚠ 待裁决」标注，不擅自推翻。
> 分工：手册 html（锚点、主题）**已由设计侧改好**，本任务只涉及 Flask 路由与模板链接。

## 1. 背景与目标

使用手册（`docs/user-guide.md` / `docs/user-guide.html`）已切换到 Web 工作流，
但 App 内没有任何入口能打开它。用户拍照时最需要对照手册（每部位有拍摄要点 + 示例图）。
目标：让用户在**拍照向导的当前部位步骤**一键打开手册对应小节（新标签页），并提供全局入口。

## 2. 已定的 UX 设计（勿重新讨论）

1. **手册以独立静态页形态供给**：`GET /guide` 直接返回 `docs/user-guide.html`
   （自包含单文件，暖纸主题已内置，锚点已注入）。不包 `base.html` 外壳——
   手册同时用于 GitHub 阅读与本地 docs 预览，保持单文件自包含；
   新标签页打开，看完关页即回 App，无需返回按钮。
2. **三层入口，主次分明**：
   - **主入口（情境帮助）**：向导页「拍摄纪律」卡，每条步骤显示对应该部位的深链
     「《舌底照》完整指南与示例图 ↗」，跳 `/guide#part-<部位>`。
   - **次入口（全局）**：appbar 导航右端加「手册」文字链 → `/guide`。
   - **首启入口**：welcome 页加「先读《使用手册》了解拍摄要求 ↗」→ `/guide`。
   - 详情页 / 趋势页 / 设置页**不加**，避免入口泛滥。
3. **所有手册链接一律 `target="_blank" rel="noopener"`**：向导中途不丢页面状态；
   新链接不得遮挡手机端的拍照区（用文字链，不用悬浮按钮）。

## 3. 手册侧已完成（设计侧交付，勿改文件）

`docs/user-guide.html` 已重导：自包含暖纸主题（对齐站点 tokens：
`#faf7f1` 底、宋体标题、朱砂 `#b0442a` 强调），并注入以下锚点 id：

| 锚点 | 小节 | 对应向导部位 |
|---|---|---|
| `sec-intro` | 一、系统简介 | — |
| `sec-dimensions` | 二、六大拍照维度 | — |
| `sec-parts` | 三、各维度拍摄指南 | — |
| `part-tongue-surface` | 3.1 舌面照 | 舌面 |
| `part-tongue-bottom` | 3.2 舌底照 | 舌底 |
| `part-face` | 3.3 头面部照 | 头面 |
| `part-eyes` | 3.4 目部照 | 目 |
| `part-ear` | 3.5 耳部照 | 耳 |
| `part-hands` | 3.6 手掌照 | 手 |
| `part-skin` | 3.7 皮肤照 | 皮肤 |
| `sec-inquiry` | 四、十五项问诊 | — |
| `sec-combos` | 五、每日拍照建议 | — |
| `sec-usage` | 六、使用方式（拍照向导） | — |
| `sec-report` | 七、报告示例 | — |
| `sec-notes` | 八、注意事项 | — |

## 4. 实现任务

### 4.1 `GET /guide` 路由（web/app.py）

- 用 `src/paths` 的仓库根推导定位 `docs/user-guide.html`，
  `send_file(..., mimetype="text/html")` 返回。
- 只读公开文档，**不需要** `WEB_ADMIN_TOKEN`；不改变现有绑定安全模型
  （默认 127.0.0.1，`--lan` 行为不变）。
- 文件缺失时返回 404 + 一行纯文本说明（可诊断，不静默）。

### 4.2 向导页主入口（web/wizard_store.py + web/templates/wizard.html）

- `wizard_store.py` 的 `PARTS` 每项补两个字段：
  `guide_anchor`（按 §3 表取值）、`guide_label`（手册小节名：
  舌面照 / 舌底照 / 头面部照 / 目部照 / 耳部照 / 手掌照 / 皮肤照）。
- 模板：「拍摄纪律」`<ul id="tips">` 下方加一条文字链
  `<a id="guide-link" target="_blank" rel="noopener">`，
  `render()` 里随当前部位更新：`href = "/guide#" + p.guide_anchor`，
  文案 `《${p.guide_label}》完整指南与示例图 ↗`。
- 样式：`font-size:13px`、`color:var(--cinnabar)`、`display:inline-block`、
  `margin-top:10px`，下划线 hover 即可；不新增按钮样式。

### 4.3 appbar 全局入口（web/templates/base.html）

- `<nav class="appnav">` 末尾（设置之后）加：
  `<a href="/guide" target="_blank" rel="noopener">手册</a>`。
- 该链接不参与 `page` active 高亮（手册是新标签静态页，无 active 态）。
- 注意窄屏（≤640px）下导航不溢出：允许换行，不得横向挤压品牌区。

### 4.4 welcome 首启入口（web/templates/welcome.html）

- 在现有引导动作区加一行：
  `<a href="/guide" target="_blank" rel="noopener">先读《使用手册》了解拍摄要求 ↗</a>`，
  样式同 4.2 的文字链。

## 5. 约束

- 不动向导流程逻辑、不动 `docs/user-guide.html`、不动 `src/` 核心。
- 遵循 AGENTS.md：失败可诊断、正常路径零告警；测试基线 353 保持全绿
  （新增路由请补一条 `test_web_app.py` 用例：`/guide` 返回 200 且含锚点 `part-tongue-bottom`）。
- `records/`、`.env` 永不入库。

## 6. 验收清单

1. `pytest tests/ -q` 全绿（含新用例）。
2. 手测：`GET /guide` → 200，`/guide#part-ear` 打开直接定位到「5. 耳部照」。
3. 向导页逐步切换 7 个部位，深链 href 与 §3 映射表一一对应，新标签打开。
4. appbar「手册」、welcome 链接均可达且新标签打开。
5. 手机窄屏（≤640px 模拟）：向导页链接不遮拍照区，appbar 不横向溢出。
