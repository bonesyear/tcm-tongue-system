# scripts/hooks/ — 仓库 git hooks

## pre-push：隐私与版本守卫

公开仓库 push 前，按 `git rev-list <local_sha> --not --remotes=<remote>` 计算**真正新增的提交**，不依赖某个 remote SHA 是否存在，也不只检查 tip。根提交、附注标签、force push 和 worktree 都走同一套检查。

| 检查 | 当前行为 |
|---|---|
| 提交内容 | 扫描新增提交各版本中的文件内容，不只检查最后提交；后续删除不能掩盖中间提交 |
| 文本变体 | UTF-8 / UTF-16、JSON Unicode 转义、大小写折叠、文件名、提交和附注标签消息 |
| 凭证 | 匹配常见 API key/私钥模式；从配置的环境文件中取 KEY/TOKEN/SECRET/PASS/PWD/CREDENTIAL/ID 类值的指纹 |
| 二进制 | 常见图片仍做原始字节检查；不能确认编码的内容 fail closed，不静默放行 |
| 日志 | 只给规则编号、变量名和经过脱敏的位置，不打印敏感词、完整密钥或命中行 |
| 版本 | 比对 `VERSION` 与 CHANGELOG 最新 `## vX.Y.Z`；拒绝未归类的 `## Unreleased` 段 |

`privacy_scan.py` 只对**扫描器自身的正则定义**做精确剔除，防止自匹配；`scripts/hooks/` 目录和其他文件没有整目录豁免。

### 敏感词表

默认词表为主工作树 `.privacy-words`，由 common git dir 定位，linked worktree 也能找到；可用 `PRIVACY_WORDS_FILE` 指定其他文件。文件被 `.gitignore` 排除，不要提交。

- 每行一个词，支持 UTF-8 BOM、首尾空白与 `#` 注释行；空行忽略。
- **缺失或不可读时拒绝放行**，不会打印“未发现敏感信息”后放行。没有敏感词的环境可显式创建空文件或指定空词表。
- `_PRIVACY_ENV_FILES` 可提供指纹配置路径：JSON 字符串数组，或 `os.pathsep` 分隔的列表；也兼容旧的空白分隔。默认检查项目 `.env` 与若干用户配置路径，缺失文件跳过。
- 指纹只取长度至少 20 的值的前 14 字符，不在日志中输出完整凭证或片段。

### 启用

```bash
git config core.hooksPath scripts/hooks
chmod +x scripts/hooks/pre-push
```

### 验证

```bash
python3 -m pytest tests/test_pre_push.py tests/test_oss_backup.py tests/test_push_script.py -q
```

测试使用临时仓库、临时 bare remote、合成敏感词和本地 stub。不会执行真实 GitHub 推送、OSS 上传或历史修改。

### 误报处理

确认是术语或说明性文字时可用 `git push --no-verify`，但应记录豁免理由。含敏感内容的提交必须从历史中 amend / rebase 清除；新增删除提交不能清除历史。历史清理流程见 skill `public-repo-privacy`，hook 只防未来推送，不能清理已经进入历史的内容。
