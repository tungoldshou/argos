#!/usr/bin/env bash
# build_desktop.sh — 构建 Argos 桌面壳 (.app bundle)
#
# 用法:
#   ./packaging/build_desktop.sh [--debug]
#
# 依赖:
#   - Node.js (npm/npx)
#   - Rust toolchain (cargo)
#   - @tauri-apps/cli (项目 devDependency, 通过 npx 调用)
#
# 产物:
#   desktop/shell/src-tauri/target/release/bundle/macos/Argos.app
#
# 签名状态:
#   Tauri 默认使用 ad-hoc 签名 (codesign -s -)。
#   ad-hoc 签名可本地运行,但无法通过 Gatekeeper 公证。
#   正式分发需要:
#     1. Apple Developer ID 证书
#     2. codesign --deep --options runtime --sign "Developer ID Application: ..."
#     3. xcrun notarytool submit ... --wait
#   详见 packaging/desktop.md。
#
# 版本同步纪律:
#   版本单源: packaging/VERSION
#   /ship 发版时同步更新:
#     packaging/VERSION
#     desktop/shell/src-tauri/tauri.conf.json  (.version)
#     desktop/shell/package.json               (.version)
#   不要手动改三处——用 /ship 脚本统一操作。

set -euo pipefail

SHELL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../desktop/shell" && pwd)"
BUILD_MODE="${1:-}"

echo "=== Argos 桌面壳构建 ==="
echo "Shell dir: $SHELL_DIR"
echo "Build mode: ${BUILD_MODE:-release}"
echo ""

# 1. 安装 Node 依赖
echo "[1/3] npm ci (安装 Node 依赖)..."
cd "$SHELL_DIR"
npm ci

# 2. TypeScript 编译 (前端 dist)
echo "[2/3] npx tsc (TypeScript 编译)..."
npx tsc

# 3. Tauri build
echo "[3/3] npx tauri build..."
if [[ "$BUILD_MODE" == "--debug" ]]; then
    npx tauri build --debug
    APP_PATH="$SHELL_DIR/src-tauri/target/debug/bundle/macos/Argos.app"
else
    npx tauri build
    APP_PATH="$SHELL_DIR/src-tauri/target/release/bundle/macos/Argos.app"
fi

echo ""
echo "=== 构建完成 ==="
echo "产物路径: $APP_PATH"
echo ""

# 4. 校验产物
if [[ ! -d "$APP_PATH" ]]; then
    echo "ERROR: .app bundle 未找到: $APP_PATH" >&2
    exit 1
fi

echo "--- codesign -dv ---"
codesign -dv "$APP_PATH" 2>&1

echo ""
echo "--- CFBundleIdentifier 校验 ---"
BUNDLE_ID=$(defaults read "$APP_PATH/Contents/Info.plist" CFBundleIdentifier 2>/dev/null \
    || /usr/libexec/PlistBuddy -c "Print :CFBundleIdentifier" "$APP_PATH/Contents/Info.plist")
echo "CFBundleIdentifier: $BUNDLE_ID"
if [[ "$BUNDLE_ID" != "app.argos.shell" ]]; then
    echo "ERROR: bundle id 不符,期望 app.argos.shell,得到 $BUNDLE_ID" >&2
    exit 1
fi
echo "bundle id OK"

echo ""
echo "完成。.app: $APP_PATH"
