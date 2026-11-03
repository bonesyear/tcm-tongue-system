#!/bin/bash
# ============================================================
# 中医望诊系统 — OSS 版本备份脚本
# 策略：仅在内容变化时备份，始终覆盖旧版，只保留最新
#
# 安全约定：
#   - 只打包 git 跟踪且经敏感路径筛选的文件；敏感文件即使被跟踪也不进入包
#   - 必须显式设置 TCM_OSS_BUCKET，未设置直接拒绝，不默认上传作者桶
#   - records/、charts/、.env、.privacy-words、_books、电子书等始终排除
#   - 临时文件用 mktemp 创建并 trap 清理；清单损坏可诊断并原子重写
#
# 路径与配置：
#   - 仓库根默认取脚本所在目录的上级，可用 TCM_SYSTEM_DIR 覆盖
#   - OSS bucket 由 TCM_OSS_BUCKET 显式指定（无默认值）
#   - 哈希命令自动选择 md5sum（Linux）/ shasum（macOS）
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SYSTEM_DIR="${TCM_SYSTEM_DIR:-$(dirname "$SCRIPT_DIR")}"
MANIFEST_FILE="${SYSTEM_DIR}/.backup_manifest"
OSS_BUCKET="${TCM_OSS_BUCKET:-}"
if [ -z "$OSS_BUCKET" ]; then
    echo "❌ 未设置 TCM_OSS_BUCKET，拒绝上传；请显式选择自己的备份桶" >&2
    exit 2
fi
OSS_PATH="oss://${OSS_BUCKET}/hermes/tcm-tongue-system/tcm-tongue-system-latest.tar.gz"
VERSION_FILE="${SYSTEM_DIR}/VERSION"

# --- 0. 可移植哈希命令（macOS 无 md5sum） ---
if command -v md5sum >/dev/null 2>&1; then
    HASH_CMD="md5sum"
elif command -v shasum >/dev/null 2>&1; then
    HASH_CMD="shasum -a 256"
else
    echo "❌ 找不到 md5sum / shasum，无法计算内容哈希" >&2
    exit 1
fi

TMP_TAR="$(mktemp -t tcm-backup.XXXXXX)"
TMP_MANIFEST=""
cleanup() {
    rm -f "$TMP_TAR"
    if [ -n "$TMP_MANIFEST" ]; then
        rm -f "$TMP_MANIFEST"
    fi
}
trap cleanup EXIT

# --- 1. 读取或生成版本号 ---
if [ -f "$VERSION_FILE" ]; then
    VERSION=$(head -1 "$VERSION_FILE" | xargs)
    echo "📌 当前版本: ${VERSION}"
else
    VERSION="$(date +%Y%m%d-%H%M%S)"
    echo "$VERSION" > "$VERSION_FILE"
    echo "📌 新建版本: ${VERSION}"
fi

# --- 2. 已跟踪文件白名单与内容哈希（相对路径，不受上层目录名影响） ---
tracked_files() {
    git -C "$SYSTEM_DIR" ls-files -z |
    while IFS= read -r -d '' path; do
        case "$path" in
            .env.example)
                printf '%s\0' "$path"
                continue
                ;;
            .env|.env.*|.privacy-words|_books/*|*.epub|*.pdf|docs/*_TASK_*.md|\
            .claude/*|records/*|charts/*|knowledge_base/jingfang_tanyuan_full.md)
                continue
                ;;
        esac
        printf '%s\0' "$path"
    done
}

CURRENT_HASH=$(tracked_files | (cd "$SYSTEM_DIR" && xargs -0 $HASH_CMD) \
    | sort -k2 | $HASH_CMD | awk '{print $1}')

echo "🔑 当前内容哈希: ${CURRENT_HASH}"

# --- 3. 与上次备份对比 ---
LAST_HASH=""
if [ -f "$MANIFEST_FILE" ]; then
    LAST_HASH=$(grep "^hash=" "$MANIFEST_FILE" | cut -d= -f2 || true)
    if [ -z "$LAST_HASH" ]; then
        echo "⚠️ 备份清单缺少 hash，按需要重新备份处理" >&2
    fi
fi
if [ -n "$LAST_HASH" ] && [ "$CURRENT_HASH" = "$LAST_HASH" ]; then
    echo "⏭️  内容无变化，跳过备份。"
    exit 0
fi
if [ -f "$MANIFEST_FILE" ]; then
    echo "🔄 检测到内容变化，开始备份..."
else
    echo "🆕 首次备份..."
fi

# --- 4. 只打包白名单文件；即使敏感文件被跟踪也不进入压缩包 ---
echo "📦 打包中..."
tracked_files | tar -czf "$TMP_TAR" -C "$SYSTEM_DIR" --null -T -

TAR_SIZE=$(du -h "$TMP_TAR" | awk '{print $1}')
echo "   打包完成: ${TAR_SIZE}"

# --- 5. 上传到 OSS（覆盖） ---
echo "☁️  上传到 OSS..."
ossutil cp -f "$TMP_TAR" "$OSS_PATH"

# --- 6. 原子写入清单 ---
TMP_MANIFEST="$(mktemp "${MANIFEST_FILE}.tmp.XXXXXX")"
cat > "$TMP_MANIFEST" << EOF
version=${VERSION}
hash=${CURRENT_HASH}
timestamp=$(date -Iseconds)
size=${TAR_SIZE}
EOF
mv -f "$TMP_MANIFEST" "$MANIFEST_FILE"
TMP_MANIFEST=""

echo ""
echo "✅ 备份完成！"
echo "   OSS 路径: ${OSS_PATH}"
echo "   版本:     ${VERSION}"
echo "   大小:     ${TAR_SIZE}"
echo "   哈希:     ${CURRENT_HASH}"
echo ""
echo "💡 旧版本已被覆盖，OSS 上只保留最新版。"
echo "💡 已排除：records/、charts/（健康数据）与《经方探源》全文（版权物）。"
