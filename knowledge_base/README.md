# 知识库配置说明

公开仓库不再附带原结构化知识库、整理/衍生笔记或别名词典。这里仅保留配置说明，不是替代知识库，也不会生成检索证据。

## 私有知识库

完整内容已保存在仓库外的私有目录，原版权说明保持不变。公私分离不等于取得公开再分发授权，也不改变既有公开历史。

使用现有 `TCM_KB_ROOT` 指向你**有权使用的私有知识库目录**：

```bash
# Linux / macOS 示例
export TCM_KB_ROOT=/absolute/path/to/private-kb

# Windows 示例：请在系统环境变量或项目 .env 中配置绝对路径
# TCM_KB_ROOT=C:\private\knowledge_base
```

`TCM_KB_ROOT` 是部署配置，不接受网页用户输入。Grep、RAG 和默认别名词典共用此根目录；相对路径按仓库根归一化。不要把私有目录路径、原始引文或笔记重新提交到公开仓库。

未配置或目录不存在时，检索按既有降级行为返回空结果或告警，不伪造知识库引用。公开测试使用 `tests/fixtures/knowledge_base/` 中的独立合成资料，不依赖私有内容。

## 本地 ZIP 导入与自建

没有现成知识库时，可按 [`docs/KB_AUTHORING.md`](../docs/KB_AUTHORING.md) 将自己的合法文献整理为 Markdown/YAML，或使用 [`templates/kb/`](../templates/kb/) 的非医学合成模板验证格式。打包 ZIP 后在「设置 → 知识库」导入，不需要在线下载或调用模型。

每次成功导入只覆盖 `<TCM_DATA_ROOT>/private_kb/` 这份程序管理的副本，再按需写回 `TCM_KB_ROOT`；**不会移动、覆盖或删除上述外部私有目录**。不要把唯一原稿放进导入副本。环境变量锁定时不改 `.env`，现有根继续生效。自定义内容只参与检索与引用，不自动修改医学规则，也不是模型训练。
