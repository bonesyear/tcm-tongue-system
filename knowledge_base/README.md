# 中医望诊知识库

本目录存放中医著作提炼后的结构化知识，供 DeepSeek 辨证时加载使用，
并作为 `src/retrieval/` 混合检索（Grep + 同义词 + RAG）的语料库。

## 目录结构

```
knowledge_base/
├── README.md                                    ← 本文件
├── synonym_map.yaml                             ← 临床口语 → 标准术语 别名词典（检索展开用）
├── diagnostics/
│   ├── diagnostic-framework.md                  ← 许家栋三观/四证/六病完整辨证框架
│   ├── smartphone-visual-diagnostics.md          ← 六大拍照维度+十五项问诊→许家栋框架映射
│   └── constitution-types.md                    ← 九种体质分类与判定标准
├── formulas/
│   └── formula-system.md                         ← 方机体系/治法法则/药证/选方逻辑
├── diet-lifestyle/
│   └── diet-therapy.md                          ← 食疗方案（四气五味+忌口）
```

> ⚠️ 本仓库不含已出版著作的全文内容。如有本地研究用参考文件（已加入 `.gitignore`，不入版本库），请遵守相关版权法规。

## 使用方式

- 辨证：加载 diagnostics/ 和 formulas/ 相关内容作为系统知识上下文。
- 检索：`from src.retrieval import retrieve` 统一入口（Grep 优先，低命中补 RAG）。

## ⚠️ 版权说明

本仓库知识库文件为基于中医经典学术体系的整理/衍生笔记，仅作个人学习研究用途，
请勿以任何形式再分发（公开仓库、共享存储、转交他人）。
