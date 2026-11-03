#!/usr/bin/env bash
# 安全 push：保留凭据配置、校验目的地、独立核对远端 SHA。
set -euo pipefail

REMOTE="${1:-origin}"
BRANCH="${2:-main}"
GIT_BIN="${GIT_BIN:-git}"
git() {
  if [ "$GIT_BIN" = "git" ]; then
    command git "$@"
  else
    "$GIT_BIN" "$@"
  fi
}

if ! git rev-parse --git-dir >/dev/null 2>&1; then
  echo "❌ 当前目录不是 git 仓库" >&2
  exit 1
fi

VERSION="$(git version)"
VERSION_NUMBER="${VERSION##* }"
MAJOR="${VERSION_NUMBER%%.*}"
REST="${VERSION_NUMBER#*.}"
MINOR="${REST%%.*}"
if [ "$MAJOR" -lt 2 ] || { [ "$MAJOR" -eq 2 ] && [ "$MINOR" -lt 32 ]; }; then
  echo "❌ 需要 Git >= 2.32 才能隔离配置，当前为 $VERSION" >&2
  exit 1
fi

BYPASS_GLOBAL="$(mktemp)"
BYPASS_SYSTEM="$(mktemp)"
INCLUDE_DIR="$(mktemp -d)"
INCLUDE_INDEX=0
trap 'rm -f "$BYPASS_GLOBAL" "$BYPASS_SYSTEM"; rm -rf "$INCLUDE_DIR"' EXIT

# 复制非 URL 配置；include 指向临时净化副本，避免再次引入 URL 重写。
sanitize_config() {
  local level="$1" output="$2" source="${3:-}" key value include_source sanitized
  if [ -z "$source" ]; then
    case "$level" in
      --global) source="${GIT_CONFIG_GLOBAL:-$HOME/.gitconfig}" ;;
      --system) source="${GIT_CONFIG_SYSTEM:-/etc/gitconfig}" ;;
      *) echo "❌ include 缺少来源配置" >&2; exit 1 ;;
    esac
  fi
  : > "$output"
  local cmd=(git config "$level")
  if [ "$level" = "--file" ]; then
    cmd+=("$source")
  fi
  while IFS=' ' read -r key value; do
    case "$key" in
      url.*) continue ;;
      include.path|includeIf.*.path)
        [ -z "$value" ] && continue
        include_source="${value/#\~/$HOME}"
        case "$include_source" in
          /*|[A-Za-z]:[\\/]*|[A-Za-z]:/*) ;;
          *) include_source="$(dirname "$source")/$include_source" ;;
        esac
        if [ ! -f "$include_source" ]; then
          git config --file "$output" "$key" "$value"
          continue
        fi
        if [ "$INCLUDE_INDEX" -ge 8 ]; then
          echo "❌ include 文件数量或嵌套深度超过 8，拒绝继续" >&2
          exit 1
        fi
        INCLUDE_INDEX=$((INCLUDE_INDEX+1))
        sanitized="$INCLUDE_DIR/include.$INCLUDE_INDEX"
        sanitize_config --file "$sanitized" "$include_source"
        git config --file "$output" "$key" "$sanitized"
        continue
        ;;
    esac
    git config --file "$output" "$key" "$value"
  done < <("${cmd[@]}" --get-regexp .)
}

sanitize_config --global "$BYPASS_GLOBAL"
sanitize_config --system "$BYPASS_SYSTEM"
export GIT_CONFIG_GLOBAL="$BYPASS_GLOBAL"
export GIT_CONFIG_SYSTEM="$BYPASS_SYSTEM"

if git config --local --get-regexp '^url\..*\.insteadof$' >/dev/null 2>&1; then
  echo "❌ 仓库级 url.insteadOf 会改写推送目的地；请先在仓库配置中移除，不能用本脚本绕过" >&2
  exit 1
fi

DESTINATION="$(git remote get-url --push "$REMOTE")"
case "$DESTINATION" in
  https://github.com/*|git@github.com:*|ssh://git@github.com/*) ;;
  *)
    echo "❌ 推送目的地不是 github.com：$DESTINATION；拒绝继续" >&2
    exit 1
    ;;
esac

echo "▶ push $REMOTE $BRANCH（保留凭据助手，仅过滤 URL 重写）"
git -c http.version=HTTP/1.1 push "$REMOTE" "refs/heads/$BRANCH:refs/heads/$BRANCH"

LOCAL_SHA="$(git rev-parse --verify "refs/heads/$BRANCH^{commit}")"
if ! REMOTE_LINE="$(git ls-remote "$REMOTE" "refs/heads/$BRANCH")"; then
  echo "❌ 远端验证失败：ls-remote 无法读取 $REMOTE/$BRANCH" >&2
  exit 1
fi
REMOTE_SHA="${REMOTE_LINE%%[[:space:]]*}"
if [ -z "$REMOTE_SHA" ]; then
  echo "❌ 远端验证失败：$REMOTE/$BRANCH 不存在" >&2
  exit 1
fi

if [ "$LOCAL_SHA" != "$REMOTE_SHA" ]; then
  echo "❌ 验证失败：本地 ${LOCAL_SHA:0:7} ≠ 远端 ${REMOTE_SHA:0:7}" >&2
  exit 1
fi

echo "✅ 验证通过：本地 = 远端 = ${LOCAL_SHA:0:7}"
