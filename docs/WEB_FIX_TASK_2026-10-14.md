# Web 前端小修任务书（移交 Kimi Code）

> 2026-10-14 · Kimi Work 对 v1.7.4（HEAD `eb48f0e`）实机走查后的两条反馈。
> 走查结论：五页 + welcome 页保真度高，`pytest` 350 passed；仅以下两条小改，预计均为单文件级改动。
> 与 2026-09-30 那份大任务书无关的新增项，不改任何已定需求。

---

## 任务 1：设置页「辨证模型」端点提示文案与实际行为对齐（文案-only）

**现状矛盾**

- `web/templates/settings.html:131` 辨证模型端点 hint 写「必须是 OpenAI 兼容的 chat/completions 完整地址」。
- 但自 `108a99f` 起，`web/llm_client.py:19-30` 的 `normalize_chat_url()` 会对缺 `/chat/completions` 后缀的端点**自动补齐 + stderr 告警**。走查实测：`.env` 里存的是裸 `https://api.deepseek.com`，连通性测试通过（5.1s），服务日志有
  `[web][llm_client][warn] 端点 'https://api.deepseek.com' 缺少 /chat/completions 后缀，已自动补齐；建议把配置改全`。
- 文案比行为严格：用户裸填能跑通，但看到告警会困惑「到底要不要补」。

**改法**

- 只改 `settings.html:131` 这一条 hint，补一句自动补齐说明。参考措辞（语感以你为准，语义到位即可）：
  「必须是 OpenAI 兼容的 chat/completions 地址；缺 /chat/completions 后缀时会自动补齐并在服务日志告警，建议填全（形如 https://…/v1/chat/completions）」。
- **不要动 `:88` 视觉模型的 hint**——`scripts/vision_client.py:110-111` 对 `VISION_BASE_URL` 不做规整、原样使用，「只填到 /v1 会 404」对视觉侧属实。
- `:130` 输入框 placeholder 已是完整地址示例，无需改。

**验收**：页面渲染无破版；`pytest tests/ -q` 全绿。

---

## 任务 2：趋势页空周时提供「跳到最近有记录的一周」（小功能）

**现状**

- `web/templates/trends.html:32-33`：当周无记录时只渲染一句「该周没有任何记录。先从『拍照』页完成一天的望诊记录。」
- 趋势页默认打开本周；真实使用是隔几天才记一次，首次打开大概率撞上空卡，容易误判为故障（走查时靠 `?week=2026-06-25` 直达才看到图表）。

**改法**

- `web/app.py:185-196` `trends()`：当周无记录（`week` 为空）且库内存在任意记录时，用 `records_store.list_dates(daily_dir)`（`web/records_store.py:170`，返回**降序**日期列表，取 `[0]` 即最新）得到最近记录日期，作为 `latest_with_records` 传入模板。
- `trends.html` 空态卡内、现有文案之后追加一条跳转链接，语义参考：「最近一次记录在第 N 周（YYYY-MM-DD 所在周），去看看 →」，href 为 `?week=<该日期>`。
- 样式复用现有按钮/链接类与 tokens，**不引入新组件、新 CSS 变量**；窄屏不折行难看即可。
- 边界：全库无记录时维持现状（继续引导去拍照）；当周有记录时不出现该链接。

**验收**

- `pytest tests/ -q` 全绿；如适合，为空周跳转补一个小测试。
- 手测两场景：① 本周空、库内有历史记录 → 显示链接，点击落在正确周；② 全库空 → 维持原文案。

---

## 协作约定（照 AGENTS.md §2）

- 一条分支即可：`fix/web-ux-2026-10-14`；两个改动都小，同分支两 commit 或合并一个均可。
- commit 风格 `fix(web): 中文描述`；任务 2 涉及可见行为，按仓库既有习惯处理 VERSION / CHANGELOG。
- `records/`、`.env` 永不入库；完成标准 = pytest 全绿 + 真实路径手测通过，不只编译/导入成功。
