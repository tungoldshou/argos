#!/usr/bin/env bash
# Argos arm64 单 binary 打包(spec §10,替代旧 tauri build)。
# 用项目 arm64 venv(uv 管理);跑在仓库根。
set -euo pipefail
cd "$(dirname "$0")/.."   # 仓库根

# 版本号来源(spec §2.6):
# - 优先环境变量 ARGOS_VERSION(从 git tag 解析,CI 用)
# - fallback 读 packaging/VERSION
if [ -z "${ARGOS_VERSION:-}" ]; then
  if [ -f packaging/VERSION ]; then
    ARGOS_VERSION=$(cat packaging/VERSION)
  else
    ARGOS_VERSION="0.0.0+unknown"
  fi
fi
export ARGOS_VERSION
echo "=== Building Argos $ARGOS_VERSION ==="

# 1. 确保 pyinstaller 在 venv 里。
uv run python -c "import PyInstaller" 2>/dev/null || uv add --dev pyinstaller

# 2. 验证 arm64(踩过 x86_64 Rosetta 坑)。
ARCH=$(uv run python -c "import platform; print(platform.machine())")
[ "$ARCH" = "arm64" ] || { echo "FATAL: venv 不是 arm64(是 $ARCH)"; exit 1; }

# 3. 打包(用 spec)。
uv run pyinstaller --clean --noconfirm packaging/argos.spec

# 4. 验产物架构 + 端到端自检。
BIN=dist/argos
file "$BIN"                          # 必须 Mach-O arm64
shasum -a 256 "$BIN"
echo "=== smoke: argos --selftest(不连网,验整机装配) ==="
"$BIN" --selftest                    # 期望打印 [selftest] ... OK,退出 0
echo "=== 打包完成: $BIN ==="
