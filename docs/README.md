# 文档索引

本目录保留现有文件名和链接，不做破坏历史引用的大规模迁移。按下列入口查找，新增文档应归入相应类别。

## 使用与配置

- [Web 快速上手](web-quickstart.md)
- [完整使用手册](user-guide.md)（[HTML 版](user-guide.html)）
- [从中医著作到知识库](kb-guide.md)（[HTML 版](kb-guide.html)）
- [自建知识库规范](KB_AUTHORING.md)
- [医学治理与边界](GOVERNANCE_2026-10-27.md)
- [已知问题](KNOWN_ISSUES.md)
- [审查闭环索引](REVIEW_CLOSURE_2026-11-03.md)

## 架构与证据

- [检索架构](architecture/retrieval-design.md)
- [Web 设计交接](web-design-handoff.md)
- [术语出处台账](VOCAB_PROVENANCE_2026-10-16.md)

## 审查记录

- `AUDIT_*.md`：底层模型、原著和教材设计审查。
- `REVIEW_*.md`：版本审查及附录。
- `DESIGN_REVIEW_*.md`、`DOMAIN_REVIEW_*.md`：早期设计与领域审查。
- [结构与架构审查](STRUCTURE_REVIEW_2026-11-03.md)

这些是历史证据，不应因版本更新而改写原结论；后续修正以迁移记录为准。

## 迁移记录

- [B01–B03](MIGRATION_2026-10-26_B01-B03.md)、[B04](MIGRATION_2026-10-26_B04.md)、[B05](MIGRATION_2026-10-26_B05.md)、[B06](MIGRATION_2026-10-26_B06.md)
- [B07](MIGRATION_2026-10-27_B07.md)、[B09](MIGRATION_2026-10-27_B09.md)、[B10](MIGRATION_2026-10-27_B10.md)、[B11](MIGRATION_2026-10-27_B11.md)、[B12](MIGRATION_2026-10-27_B12.md)、[B14](MIGRATION_2026-10-27_B14.md)
- [KNOWN21 并发写入](MIGRATION_2026-10-27_KNOWN21.md)
- [B13](MIGRATION_2026-10-28_B13.md)、[B15](MIGRATION_2026-10-28_B15.md)、[B16](MIGRATION_2026-10-28_B16.md)、[B17](MIGRATION_2026-10-28_B17.md)、[B18](MIGRATION_2026-11-03_B18.md)、[B19](MIGRATION_2026-11-03_B19.md)
- [知识库公私分离](MIGRATION_2026-11-03_KB_SPLIT.md)
- [ZIP 导入](MIGRATION_2026-11-03_KB_IMPORT.md)
- [运行链与无库展示](MIGRATION_2026-11-03_KB_RUNTIME_REVIEW.md)
- [三类知识库](MIGRATION_2026-11-03_KB_CATEGORIES.md)
- [事务与类别硬化](MIGRATION_2026-11-03_KB_HARDENING.md)
- [分类重置](MIGRATION_2026-11-03_KB_RESET.md)
- [公开历史清理与默认禁用](MIGRATION_2026-11-03_EXTERNAL_DEFAULT_OFF.md)
- [B21–B22 路由与报告结构优化](MIGRATION_2026-11-03_B21-B22.md)
- [B23 部署与复原验收](MIGRATION_2026-11-03_B23.md)
- [B25 工作区治理与部署边界验收](MIGRATION_2026-11-04_B25.md)
- [综合知识库导入入口](MIGRATION_2026-11-04_COMPOSITE_IMPORT.md)
- [知识库路径收进技术详情](MIGRATION_2026-11-04_KB_PATH_DETAILS.md)
- [系统审查：知识库隔离、照片回滚与选档修复](MIGRATION_2026-11-04_REVIEW_HARDENING.md)
- [统一知识库检索视图](MIGRATION_2026-11-04_KB_UNIFIED.md)
- [B26 正式报告链路与缺类隔离](MIGRATION_2026-11-04_B26.md)
- [B27 统一视图一致性与缓存清理](MIGRATION_2026-11-04_B27.md)
- [B28 受管统一视图与并发恢复](MIGRATION_2026-11-04_B28.md)
- [B29 统一视图归属与缓存完整性](MIGRATION_2026-11-04_B29.md)
- [单一综合回退根修正与系统验收](MIGRATION_2026-11-05_KB_SINGLE_SHARED_ROOT.md)

## 新增文档约定

- 迁移记录使用 `MIGRATION_YYYY-MM-DD_<主题>.md`，说明行为变化、兼容性和验证结果。
- 审查记录使用 `AUDIT_` 或 `REVIEW_`，保留原始发现，不伪装成已修复。
- 不提交一日任务书 `*_TASK_*.md`，也不提交私有知识库、真实病案或本机配置。
