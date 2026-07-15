#!/bin/bash
# ============================================================
# 中医望诊系统 — OSS 版本备份脚本
# 策略：仅在内容变化时备份，始终覆盖旧版，只保留最新
#
# 安全约定（见 docs/CODE_REVIEW_2026-07-12.md 风险 A/B/D）：
#   - 不上传任何个人健康数据：records/（日报+周报）与 charts/ 全部排除
#   - 不上传《经方探源》全书原文（版权物）：
#     knowledge_base/jingfang_tanyuan_full.md 排除
#   - 临时打包文件用 mktemp 创建并 trap 清理，避免 /tmp 固定路径竞态
#
# 路径与配置：
#   - 仓库根默认取脚本所在目录的上级，可用 TCM_SYSTEM_DIR 覆盖
#   - OSS bucket 可用 TCM_OSS_BUCKET 覆盖（默认 smin-oss）
#   - 哈希命令自动选择 md5sum（Linux）/ shasum（macOS）
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SYSTEM_DIR="${TCM_SYSTEM_DIR:-$(dirname "$SCRIPT_DIR")}"
MANIFEST_FILE="${SYSTEM_DIR}/.backup_manifest"
OSS_BUCKET="${TCM_OSS_BUCKET:-smin-oss}"
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
trap 'rm -f "$TMP_TAR"' EXIT

# --- 1. 读取或生成版本号 ---
if [ -f "$VERSION_FILE" ]; then
    VERSION=$(head -1 "$VERSION_FILE" | xargs)
    echo "📌 当前版本: ${VERSION}"
else
    VERSION="$(date +%Y%m%d-%H%M%S)"
    echo "$VERSION" > "$VERSION_FILE"
    echo "📌 新建版本: ${VERSION}"
fi

# --- 2. 计算当前内容哈希（排除集与打包一致） ---
CURRENT_HASH=$(find "$SYSTEM_DIR" \
    -type f \
    -not -path '*/.backup_manifest' \
    -not -path '*/records/*' \
    -not -path '*/charts/*' \
    -not -path '*/knowledge_base/jingfang_tanyuan_full.md' \
    -not -path '*/.git/*' \
    -not -path '*/__pycache__/*' \
    -not -path '*/.pytest_cache/*' \
    -not -path '*/.venv/*' \
    -exec $HASH_CMD {} \; | sort -k2 | $HASH_CMD | awk '{print $1}')

echo "🔑 当前内容哈希: ${CURRENT_HASH}"

# --- 3. 与上次备份对比 ---
if [ -f "$MANIFEST_FILE" ]; then
    LAST_HASH=$(grep "^hash=" "$MANIFEST_FILE" | cut -d= -f2)
    if [ "$CURRENT_HASH" = "$LAST_HASH" ]; then
        echo "⏭️  内容无变化，跳过备份。"
        exit 0
    fi
    echo "🔄 检测到内容变化，开始备份..."
else
    echo "🆕 首次备份..."
fi

# --- 4. 打包（排除模式同时兼容 GNU tar 与 BSD tar） ---
echo "📦 打包中..."
tar -czf "$TMP_TAR" \
    --exclude='*/.backup_manifest' \
    --exclude='*/records' \
    --exclude='*/records/*' \
    --exclude='*/charts' \
    --exclude='*/charts/*' \
    --exclude='*/knowledge_base/jingfang_tanyuan_full.md' \
    --exclude='*/.git' \
    --exclude='*/.git/*' \
    --exclude='*/__pycache__' \
    --exclude='*/__pycache__/*' \
    --exclude='*/.pytest_cache' \
    --exclude='*/.pytest_cache/*' \
    --exclude='*/.venv' \
    --exclude='*/.venv/*' \
    -C "$(dirname "$SYSTEM_DIR")" "$(basename "$SYSTEM_DIR")/"

TAR_SIZE=$(du -h "$TMP_TAR" | awk '{print $1}')
echo "   打包完成: ${TAR_SIZE}"

# --- 5. 上传到 OSS（覆盖） ---
echo "☁️  上传到 OSS..."
ossutil cp -f "$TMP_TAR" "$OSS_PATH"

# --- 6. 写入清单 ---
cat > "$MANIFEST_FILE" << EOF
version=${VERSION}
hash=${CURRENT_HASH}
timestamp=$(date -Iseconds)
size=${TAR_SIZE}
EOF

echo ""
echo "✅ 备份完成！"
echo "   OSS 路径: ${OSS_PATH}"
echo "   版本:     ${VERSION}"
echo "   大小:     ${TAR_SIZE}"
echo "   哈希:     ${CURRENT_HASH}"
echo ""
echo "💡 旧版本已被覆盖，OSS 上只保留最新版。"
echo "💡 已排除：records/、charts/（健康数据）与《经方探源》全文（版权物）。"
