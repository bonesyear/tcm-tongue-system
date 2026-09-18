#!/usr/bin/env bash
# 安全 push 到 GitHub —— 绕过全局镜像重写 + push 后自动验证
#
# 用法：bash scripts/push.sh [remote] [branch]     默认 origin main
#
# ── 背景（2026-09-18 实测踩过，两个独立坑）──────────────────────────────
# 坑① 凭据文件格式
#   全局/本机 git 可能配了 URL 重写（url.<base>.insteadOf），把 github.com
#   指向第三方镜像（如 gh-proxy.com）。镜像站点没有凭据 → push 失败。
#   ⚠️ 绝不能给镜像站点配 GitHub token —— 那等于把 token 交给第三方。
#   本脚本用「临时 GIT_CONFIG_GLOBAL」屏蔽全局配置，直连 github.com，
#   不改动用户的 ~/.gitconfig。
#
# 坑② ~/.git-credentials 的格式
#   必须是：  https://x-access-token:<TOKEN>@github.com
#   写成     https://<TOKEN>@github.com  （缺 password 段）会因匹配失败而返回空，
#   表现为 "fatal: could not read Username for 'https://github.com'"。
#
# ── 纪律（本轮教训）─────────────────────────────────────────────────────
#   git commit 成功但 git push 失败时，两者输出都"看起来正常"，
#   极易误以为已推送 → 因此本脚本在 push 后**自动核对本地与远端 SHA**。
set -uo pipefail

REMOTE="${1:-origin}"
BRANCH="${2:-main}"

if ! git rev-parse --git-dir >/dev/null 2>&1; then
  echo "❌ 当前目录不是 git 仓库" >&2; exit 1
fi

# 检查凭据文件格式（只提示，不打印内容）
CRED="$HOME/.git-credentials"
if [ -f "$CRED" ]; then
  if ! grep -q '^https://x-access-token:.*@github\.com' "$CRED" 2>/dev/null; then
    echo "⚠️  $CRED 中未发现 'x-access-token:<token>@github.com' 格式的条目" >&2
    echo "    若非此格式，helper 可能返回空 → 见脚本头部「坑②」" >&2
  fi
else
  echo "⚠️  未找到 $CRED —— 若 push 要求输入用户名，请先配置凭据（见脚本头部）" >&2
fi

# 临时配置：只保留 credential.helper=store，屏蔽全局的 insteadOf
BYPASS="$(mktemp)"; trap 'rm -f "$BYPASS"' EXIT
printf '[credential]\n\thelper = store\n' > "$BYPASS"

echo "▶ push $REMOTE $BRANCH（直连 github.com，绕过全局镜像重写）"
if ! GIT_CONFIG_GLOBAL="$BYPASS" git -c http.version=HTTP/1.1 push "$REMOTE" "$BRANCH"; then
  echo "❌ push 命令失败（见上方输出）" >&2; exit 1
fi

# ── push 后自动验证 ──
LOCAL="$(git rev-parse HEAD)"
git fetch --quiet "$REMOTE" "$BRANCH" 2>/dev/null || true
REMOTE_SHA="$(git rev-parse "$REMOTE/$BRANCH" 2>/dev/null || echo '?')"

echo
if [ "$LOCAL" = "$REMOTE_SHA" ]; then
  echo "✅ 验证通过：本地 = 远端 = ${LOCAL:0:7}"
else
  echo "❌ 验证失败：本地 ${LOCAL:0:7} ≠ 远端 ${REMOTE_SHA:0:7}" >&2
  echo "   push 可能未真正生效 —— 请检查凭据/网络后重试" >&2
  exit 1
fi
