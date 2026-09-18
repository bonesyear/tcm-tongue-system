# scripts/hooks/ —— 仓库 git hooks

## pre-push：Hermes 隐私守卫

**用途**：公开仓库 push 前自动阻断「使用者信息 / 凭证 / 真实凭证指纹」。三层检查：

| 层 | 检查内容 |
|---|---|
| ① 敏感词表 | 读仓库根的 `.privacy-words`（该文件**被 .gitignore 排除** —— 因为里面含真实姓名，绝不进仓库） |
| ② 凭证模式 | `sk-` / `sk-ant-` / `ghp_` / `github_pat_` / `LTAI` / `AKLT` / `AIza` / `BEGIN … PRIVATE KEY` |
| ③ 真实凭证指纹 | 读作者环境的多个 `.env` 路径（实际清单见 `scripts/hooks/pre-push` 顶部常量），取每个 KEY/TOKEN/SECRET/ID 变量值的前 14 字符，在**待推送的树**中比对（只比对前缀，不打印完整凭证） |

检查范围是**待推送的提交**（用 `local_sha` 的树，不看工作区），所以工作区里的临时文件不会误报。

> ⚠️ **检查时排除 `scripts/hooks/` 自身**：否则脚本里的凭证正则字面量与本文档里的模式列举会命中自己（"检测器检测自己"，实测踩过 —— 首次 push 即被自己的规则拦下）。

## 启用（每台新环境执行一次）

```bash
git config core.hooksPath scripts/hooks
chmod +x scripts/hooks/pre-push
```

## 维护 `.privacy-words`

出现新的敏感词（姓名、独特病程叙述、真实舌象值、联系方式）时追加到 `.privacy-words`，一行一个。**该文件不要提交**（已在 .gitignore）。

## 误报处理

确认是术语或说明性文字时可用 `git push --no-verify`，但应在提交信息或工作记录里写明豁免理由。

## 已验证（2026-09-18 实测）

| 场景 | 结果 |
|---|---|
| 干净提交 | ✅ 放行 |
| 提交中含真实姓名 | ✅ 拦截，并报出文件:行号 |
| 提交中含凭证指纹（假 key 探针） | ✅ 拦截，并报出变量名与前缀 |

## 与 skill 的关系

历史清理流程（filter-repo / force push / 服务端 dangling commit 的诚实边界）见 skill `public-repo-privacy`。**本 hook 只防"未来的推送"，不能清理已进入历史的内容。**
