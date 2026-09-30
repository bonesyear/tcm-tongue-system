# Web 前端设计稿 · 交接文档（Kimi Work → Kimi Code）

> 日期：2026-09-30 ｜ 分支：`feat/web-design` ｜ 产出方：Kimi Work（页面设计）
> 消费方：Kimi Code（Flask 后端 + 模板接线）
> 本文件是跨 Agent 交接的落盘件（AGENTS.md §4）；**设计稿是规格，不是可运行产品**。

---

## 0. 分工边界

| 方 | 职责 |
|---|---|
| Kimi Work（已完成） | 视觉系统（tokens + 组件 CSS）、五页静态 mockup、交互态演示、ECharts 图表选型与配置样例 |
| Kimi Code（待做） | Flask 后端、`web/` 正式工程、把 mockup 转成模板 + 真实数据接线、`.env` 写回、测试 |

设计稿落地位置 `web/design/`；正式工程由 Kimi Code 在 `web/` 下另建
（建议 `web/app.py` + `web/templates/` + `web/static/`，静态资源可直接从
`web/design/assets/` 与 `web/design/vendor/` 拷贝演进，**不要**以 import 方式跨目录引用）。

---

## 1. 文件清单

```
web/design/
├── index.html            # 跳转页 → pages/index.html
├── dev-server.js         # 零依赖静态预览服务器（npm run dev -- --port 7100）
├── package.json          # 仅承载 dev 脚本，无依赖、无构建链
├── vendor/
│   └── echarts.min.js    # ECharts 5.6.0 全量本地版（锁定：一切 JS/CSS vendor 本地）
├── assets/
│   ├── tokens.css        # 设计令牌：色板 / 字体 / 圆角 / 阴影 / 纸纹（单一来源）
│   ├── base.css          # 全部共用组件（印章 logo、卡片、徽章、进度条、步骤条、弹层、表单…）
│   └── mock-data.js      # 演示数据，结构对齐真实记录形状 B 与周报 dict
├── pages/                # 五个页面 mockup（见 §3）
└── previews/             # 渲染验证截图（2026-09-30 实测，所见即所得）
```

预览：`cd web/design && npm run dev` → http://127.0.0.1:7100/ （或直接双击 pages/*.html，
无 fetch 依赖，file:// 也能跑）。

---

## 2. 设计令牌（tokens.css）——实现时必须消费变量，不得另起色值

| 令牌 | 值 | 用途 |
|---|---|---|
| `--paper` | `#faf7f1` | 页面暖纸底（AGENTS.md 锁定） |
| `--card` / `--card-sunken` | `#fffdf9` / `#f5f0e6` | 卡片面 / 凹陷区 |
| `--ink` / `--ink-2` / `--ink-3` | `#2e2a23` / `#6f6558` / `#a2937f` | 文字三级 |
| `--cinnabar` / `--cinnabar-deep` | `#b0442a` / `#93351f` | 朱砂点缀（锁定）、hover |
| `--sev-0/1/4/7` | `#4d7c58` / `#9a7b2d` / `#b05e21` / `#b0442a` | **分数四级（锁定）**：0 正常 / 1–3 轻 / 4–6 中 / 7–10 重 |
| `--sev-*-bg` | 对应浅底 | 徽章底色 |
| `--sev-none` | `#b9ac97` | 未覆盖/无数据（虚线徽章、灰点） |
| `--font-serif` / `--font-sans` | 宋体系 / 系统无衬线 | 标题宋体（锁定）、正文 sans |
| `--paper-texture` | feTurbulence data-URI | 纸纹，零图片资源（锁定） |

分数一律**双编码**：`.badge.sev-*`（彩色徽章）+ `.scorebar > i.sev-*`（同色进度条），
对应 JS 工具 `sevClass(score)` / `sevLabel(score)`（mock-data.js，可原样搬进正式工程）。

---

## 3. 页面 → 数据源映射

| 页面 | 文件 | 动态区域 | 后端数据源 |
|---|---|---|---|
| 记录列表（首页） | `pages/index.html` | 日历格（圆点=六维等级、数字=总偏离度）、近七日行、空库「载入示例数据」条 | 逐日：`DailyRecord` + `compute_dimension_deviation()`；空库判定：records 目录为空 |
| 单日详情（核心） | `pages/record.html` | 六维卡片（字段行 k/v/单分徽章）、原图对照、辨证报告卡、安全红线横幅、修正入口 | `DailyRecord` 三形状自动识别；评分走 `src/scoring.py`；报告=记录内 `diagnosis`（形状 A 约定）+ `prompt_template_version`；原图 `records/photos/<日期>/<部位>.jpg` |
| 趋势页 | `pages/trends.html` | 六维折线、舌象九轴雷达（首末对照）、九轴×逐日热力、趋势解读文字、好转/恶化/稳定 chips | **全部来自纯函数 dict**：`generate_weekly_report_data()` / `extract_tongue_metrics()` / `compute_dimension_deviation()`，**禁止**服务端 matplotlib（AGENTS.md 锁定） |
| 拍照向导 | `pages/wizard.html` | 七部位步骤条、拍摄纪律、双跳过按钮、当日已有记录三选条、危险信号拦截弹层 | 见 §4 |
| 设置页 | `pages/settings.html` | VISION_* 表单、LLM_* 表单、连通性测试结果位、绑定地址与管理口令、局域网只读态 | `.env` 读写（唯一存储）；首次启动未配置 VISION_API_KEY → 跳此页引导 |

---

## 4. 关键交互与语义（锁定项，实现不得走样）

1. **分数语义**：徽章/进度条按单分 0–10；列表与日历的「总偏离度」为六维之和（0–60），
   其等级色按**均值**（total/6）映射四级——⚠ 此为设计新增口径，代码库暂无「总分」定义，
   若主人不认可可在 review 时改。
2. **降级/退出评分层的字段**（`prickles` 点刺、`palm_temp` 掌温）：不打分，UI 用
   虚线「参考项」徽章 + title 说明（record.html 有样例），来源 KNOWN_ISSUES §2 #5/#18。
3. **修正流程**：字段行 hover 出 ✎ → 行内编辑态 → 保存前**必须**过
   `scripts/input_validator.py` 的 `validate_record()`；保存触发自动重评分、覆盖写回
   （**形状感知**，参考 `src/record.py` `_DIMENSION_INDICATORS`）、旧版备份
   `records/_backup/`、记录打 `manually_corrected: true` + 时间戳。
4. **拍照向导双跳过**：「跳过（声明正常）」计入覆盖度 /「跳过（未覆盖）」不计分，
   两者都需在记录中显式标注，**不得伪造观察值**（KNOWN_ISSUES #10 定策）。
   拍摄纪律文案含锁定项：舌底/手掌**禁闪光灯**。
5. **danger_flags 拦截**：弹层为**拦截式**（overlay + modal），文案须含 flag 中文名、
   体征、禁忌与「肉眼复核」出口；九项键名与中文名对照已做成字典 `DANGER_FLAGS`
   （mock-data.js，键对齐 `templates/multi_dim_record_template.json`，
   名对齐 `templates/adaptive_analysis_prompt.md` §4.5）。两个出口按钮：
   「误判，去修正观察值」「已肉眼复核，保留警示」。
6. **当日已有记录再走向导**：三选条「补充未覆盖维度 / 重新分析（旧版自动备份）/ 取消」。
7. **设置页**：`VISION_*`（现状键名，见 `scripts/vision_client.py`）+ 新增 `LLM_*`
   （辨证模型）；每个字段下标注对应环境变量名；连通性测试按钮 + 结果位（成功/未测试/失败）；
   绑定默认 127.0.0.1，选 0.0.0.0 须先设 `WEB_ADMIN_TOKEN`，否则局域网只读（演示态在页底）。
8. **空库首启**：首页顶部「载入示例数据」条（demo 数据源：
   `tests/fixtures/2026-06-25_analysis.json`，其 `formula` 为合成数据，UI 须保留合成标注）。

---

## 5. ECharts 配置样例（trends.html 内可直接移植）

- **六维偏离度折线**：六条 smooth 线，y 轴固定 0–10，`connectNulls:false`
  （无观测断线，不补零）——对应 KNOWN_ISSUES 的「正常 0 与无数据须可区分」原则。
- **舌象九轴雷达**：轴集合 = `TONGUE_RADAR_METRIC_KEYS` 九键（src/scoring.py:326），
  首/末日两条 series 对照。
- **九轴×逐日热力**：visualMap 暖纸→朱砂连续色；**无观测格留空**（mock 中 06-23 演示）。
- 图表色板从 tokens 取（朱砂/橙/金/绿/灰），不要 ECharts 默认蓝紫。

---

## 6. 视觉系统要点（前 4 版风格稿已废弃，勿回退）

- 浅色主题 only；暖纸底 + 卡片浮起（暖调阴影）；
- 印章式 logo：朱砂方印 + 白文「望」（每页顶栏内联 SVG，`-3deg` 微倾）；
- 标题一律宋体（`.serif` / `--font-serif`），正文系统 sans；
- 朱砂只用于点缀与「重」级警示，不大面积铺色；
- 全部纹理为 CSS/SVG data-URI，零图片资源（局域网离线可用）。

---

## 7. 验收状态

- 五页均经内置浏览器实测渲染通过（2026-09-30，截图存 `web/design/previews/`）；
- 危险拦截弹层、修正编辑态、空库引导、局域网只读等**交互态均以静态演示形式**内置在页面中；
- 本分支只含 `web/design/` 与本文档，未触碰 `src/` / `scripts/` / `tests/`；
  `pytest tests/ -q` 294 基线不受影响（提交前已复跑确认）。
