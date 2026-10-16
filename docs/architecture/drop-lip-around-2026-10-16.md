# 废弃头面诊「口周」指标（2026-10-16）

> 按 AGENTS.md §2.6：核心库（`src/`）对外契约变更的动机与迁移说明。
> 决策人：主人拍板（2026-10-16 对话确认）。

## 变更

从 `_DIMENSION_INDICATORS`（`src/record.py`）移除头面诊 `lip_around`（口周），
连带移除 web 展示/修正选项与两个记录模板中的对应键。头面诊指标 9 → 8。

## 动机

1. **无出处**：两本参考书（《中医诊断学》《经方探源》）均无「口周」专项论述，
   词表出处台账（`docs/VOCAB_PROVENANCE_2026-10-16.md`）中标【验】。
2. **低频**：历史使用中无独立诊断价值记录。
3. **冗余**：口周发暗/疱疹等信息在头面照中人眼可判，可由「唇色」及
   知识库体质辨识文本（`knowledge_base/diagnostics/constitution-types.md`
   仍保留「口周暗沉」等表述，属辨证层语料，不受本变更影响）兜住。

## 迁移说明

- **历史档案不迁移**（仓库既定原则）：旧记录 JSON 中的 `lips.around` / `唇周`
  键原样保留在文件中，不删不改。
- 移除后 `DailyRecord.get_observation()` 不再读出该键——它本就不参与评分，
  丢弃观测视图中的该字段对分数、趋势、覆盖度**零影响**。
- 辨证 prompt 由观察值驱动，旧档的口周值不再进证据矩阵；如需找回，
  原始 JSON 仍在档案里，可人工查阅。
- 形状 C 模板与多维记录模板同步移除对应键；新记录不再产生该字段。

## 兼容性验证

`tests/fixtures/2026-06-25_analysis.json`（含 `around: "口周轻度暗沉"`）
作为遗留档案回归用例保留：加载、详情页渲染、validator 校验均须通过
（`test_web_correction.py::test_legacy_lip_around_record_still_loads`）。
