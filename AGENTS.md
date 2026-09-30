# AGENTS.md — 给在本仓库工作的 AI Agent 的协议

> 本文件是人与多个 Agent（Kimi Code / Kimi Work / 其他）协作的交接协议。
> 任何 Agent 接到本仓库任务时**先读本文档**，再动代码。

---

## 0. 仓库现状（2026-09-30）

- 版本 **v1.6.0**（2026-09-30）：新增 `web/` Web 层——五页静态设计稿 +
  Flask 骨架/设置页（切片 1 已合入）。
  更早的 v1.5.0 含一次 breaking change：框架键名去名化（「经方六经辨证」体系），
  接入方与解析层必须按新键名对齐。动手前先读 `README.md` 与 `CHANGELOG.md` 顶部。
- 测试基线 **309 passed**（含 web 层）。改动完成后必须保持全绿：
  ```bash
  python3 -m pytest tests/ -q
  ```
- 设计哲学（不可违背）：
  - `src/` 核心模块（dimensions/record/scoring/confidence/retrieval）**仅用标准库**，
    不 import 任何 LLM SDK、不发起 HTTP 请求、不绑任何框架。
  - 失败要**可诊断**（stderr 告警），不静默吞错；同时正常路径**零告警**。
  - 无遥测、无统计上报。

## 1. 当前任务：Web 前端层（切片 1 已合入，2–5 待开工）

`web/` 目录已建立，做**完整望诊工作流的 Web 入口**。需求经 16 轮决策锁定，
**不要再重新讨论以下条目**；发现硬伤（与代码现实矛盾）时按 §4 上报，不擅自推翻：

进度：切片 1（Flask 骨架 + 设置页）已合入 main；后续切片 = 记录列表/单日详情 →
修正 → 拍照向导 → 趋势页（顺序见 `docs/WEB_IMPLEMENTATION_TASK_2026-09-30.md`）。

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
1. **记录列表**（首页）：日历/列表，当日覆盖维度与总分一眼可见。
2. **单日详情**（核心页）：六维观察 + 评分 + 原图对照 + 修正入口。
3. **趋势页**：ECharts 消费 `scripts/generate_weekly_report.py` 里
   `generate_weekly_report_data()` / `extract_tongue_metrics()` /
   `compute_dimension_deviation()` 的 dict 输出（纯函数可 import），
   **不要**服务端生成 matplotlib PNG。
4. **拍照向导**：分步向导（一步一个部位，承载拍摄纪律：舌底禁闪光灯等），
   每步可「跳过（声明正常）」或「跳过（未覆盖）」；danger_flags 触发时**拦截式提示**。
5. **设置页**：视觉 LLM（`VISION_*`）与辨证 LLM（新增 `LLM_*`）在线配置，
   写回 `.env`（唯一存储）；含连通性测试；首次启动未配置则跳转引导。
   局域网开启需口令（`WEB_ADMIN_TOKEN`），未设则局域网对设置页只读。

### 关键语义
- **修正**：改观察值 → 自动重评分 → 覆盖保存，旧版自动备份到 `records/_backup/`，
  JSON 里打 `manually_corrected: true` + 时间戳。保存前必须复用
  `scripts/input_validator.py` 的 `validate_record()`。
- 记录形状有三种（A 中文键 / B `observations` / C 顶层英文键），
  `DailyRecord` 自动识别；**写回必须形状感知**（参考 `src/record.py` 的 `_DIMENSION_INDICATORS`）。
- 新记录推荐形状 B；辨证报告存进记录 JSON（形状 A 的 `diagnosis` 约定）+
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

## 3. 常见坑（前人以身试法）

- v1.5.0 键名已换：按旧键名写代码会静默落空——先用 `DailyRecord` 的形状探测确认。
- 评分词表外的措辞会被静默读作 0 分：接视觉模型的 prompt 必须用封闭词表
  （与 `src/scoring.py` 逐键对齐），换模型必须重新标定。
- `.env` 读取是「原始 bytes → 严格 UTF-8」，非 UTF-8 会打告警——别用平台默认编码重开文件。
- 知识库检索用户输入必须走 `retrieve()`（内部 re.escape）；`search()` 吃原始正则。
- 视觉端点 temperature 有服务端下限（如 DashScope 钳到 0.6），传 0 ≠ 确定性输出。

## 4. 与「另一个 Agent」的交接方式

- 跨 Agent 的长期决策**落盘到 `docs/`，不落对话**。对话记忆只属于单个 Agent。
- 发现协议与现实矛盾（本文档写错了、需求与代码冲突）：
  在本文件对应小节末尾加「⚠ 待裁决」标注并写明证据，不要静默按错的做。
