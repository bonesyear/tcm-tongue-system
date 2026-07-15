# 中医望诊知识库

本目录存放中医著作提炼后的结构化知识，供 DeepSeek 辨证时加载使用，
并作为 `src/retrieval/` 混合检索（Grep + 同义词 + RAG）的语料库。

## 目录结构（实际存在）

```
knowledge_base/
├── README.md                                    ← 本文件
├── jingfang_tanyuan_full.md                     ← 《经方探源》全文（~9000 行）⚠️ 见下方版权说明
├── synonym_map.yaml                             ← 临床口语 → 标准术语 别名词典（检索展开用）
├── diagnostics/
│   ├── diagnostic-framework.md                  ← 许家栋三观/四证/六病完整辨证框架 ✅
│   ├── smartphone-visual-diagnostics.md          ← 六大拍照维度+十五项问诊→许家栋框架映射 ✅
│   └── constitution-types.md                    ← 九种体质分类与判定标准 ✅
├── formulas/
│   └── formula-system.md                         ← 方机体系/治法法则/药证/选方逻辑 ✅
├── diet-lifestyle/
│   └── diet-therapy.md                          ← 食疗方案（四气五味+忌口） ✅
```

## 使用方式

- 辨证：加载 diagnostics/ 和 formulas/ 相关内容作为系统知识上下文。
- 检索：`from src.retrieval import retrieve` 统一入口（Grep 优先，低命中补 RAG）。

## ⚠️ 版权说明

`jingfang_tanyuan_full.md` 为许家栋《经方探源：经典经方医学概述》
（人民卫生电子音像出版社，2020，ISBN 9787117306492）全文录入，
**仅限本地个人学习研究使用**：

- 已加入 `.gitignore`，不进入版本库；
- 已从 `scripts/backup_to_oss.sh` 的备份集排除，不上传云端；
- 请勿以任何形式再分发（公开仓库、共享存储、转交他人）。

其余文件为基于该书体系整理/衍生的结构化笔记，同样建议仅作个人研究用途。
