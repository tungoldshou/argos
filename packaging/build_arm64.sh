#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

if [ -z "${ARGOS_VERSION:-}" ]; then
  if [ -f packaging/VERSION ]; then
    ARGOS_VERSION=$(cat packaging/VERSION)
  else
    ARGOS_VERSION="0.0.0+unknown"
  fi
fi
ARGOS_VERSION="${ARGOS_VERSION#v}"
export ARGOS_VERSION
echo "=== Building Argos $ARGOS_VERSION ==="

uv run python -c "import PyInstaller" 2>/dev/null || uv add --dev pyinstaller

ARCH=$(uv run python -c "import platform; print(platform.machine())")
[ "$ARCH" = "arm64" ] || { echo "FATAL: venv 不是 arm64(是 $ARCH)"; exit 1; }

uv run pyinstaller --clean --noconfirm packaging/argos.spec

BIN=dist/argos
file "$BIN"
shasum -a 256 "$BIN"

echo "=== Wrap into Argos.app bundle ==="
APP_DIR="dist/Argos.app"
mkdir -p "$APP_DIR/Contents/MacOS"
mkdir -p "$APP_DIR/Contents/Resources"
cp dist/argos "$APP_DIR/Contents/MacOS/argos"
chmod +x "$APP_DIR/Contents/MacOS/argos"
VERSION="$ARGOS_VERSION"
cp packaging/Info.plist "$APP_DIR/Contents/Info.plist"
if ! sed -i '' "s/<string>0\.1\.0<\/string>/<string>$VERSION<\/string>/g" "$APP_DIR/Contents/Info.plist" 2>/dev/null; then
  sed -i.bak "s/<string>0\.1\.0<\/string>/<string>$VERSION<\/string>/g" "$APP_DIR/Contents/Info.plist"
  rm -f "$APP_DIR/Contents/Info.plist.bak"
fi
printf 'APPL????' > "$APP_DIR/Contents/PkgInfo"
echo "   ✓ $APP_DIR/Contents/MacOS/argos + Info.plist"
ls -la "$APP_DIR/Contents/"

echo "=== smoke: argos --selftest(不连网,验整机装配) ==="
"$BIN" --selftest
echo "=== 打包完成: $APP_DIR ==="
