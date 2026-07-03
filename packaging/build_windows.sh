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
echo "=== Building Argos $ARGOS_VERSION (windows) ==="

zip_with_powershell() {
  local src="$1"
  local dest="$2"
  powershell.exe -NoProfile -Command \
    "Compress-Archive -Path '$src' -DestinationPath '$dest' -Force"
}

rm -rf dist build
mkdir -p dist

uv run python -c "import PyInstaller" 2>/dev/null || uv add --dev pyinstaller

PYI_ARGS=(
  --clean --noconfirm
  --name argos
  --onefile
  --console
  --add-data "argos/memory/schema.sql;argos/memory"
  --add-data "packaging/VERSION;packaging"
  --add-data "packaging/Info.plist;packaging"
  --collect-submodules smolagents
  --collect-submodules textual
  --collect-submodules argos
  --collect-data-files textual
  --collect-data-files smolagents
  --copy-metadata argos-agent
  --exclude-module langchain
  --exclude-module langgraph
  --exclude-module fastapi
  --exclude-module uvicorn
  argos/__main__.py
)
uv run pyinstaller "${PYI_ARGS[@]}"

BIN=dist/argos.exe
[ -f "$BIN" ] || { echo "FATAL: 缺 $BIN"; exit 1; }
file "$BIN" 2>/dev/null || true

cd dist
zip_with_powershell "argos.exe" "Argos-${ARGOS_VERSION}-x86_64-windows.zip"
cd ..
SHASUM=shasum
command -v sha256sum >/dev/null 2>&1 && SHASUM=sha256sum
$SHASUM "dist/Argos-${ARGOS_VERSION}-x86_64-windows.zip" 2>/dev/null || true

if command -v candle >/dev/null 2>&1 && command -v light >/dev/null 2>&1; then
  echo "=== Pack .msi (WiX 简化方案) ==="
  cat > dist/argos.wxs <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<Wix xmlns="http://schemas.microsoft.com/wix/2006/wi">
  <Product Id="*" Name="Argos" Version="${ARGOS_VERSION}" Manufacturer="tungoldshou" Language="1033">
    <Package InstallerVersion="500" Compressed="yes" InstallScope="perMachine"/>
    <MediaTemplate EmbedCab="yes"/>
    <Directory Id="INSTALLFOLDER" Name="Argos">
      <Component Id="MainExecutable" Guid="*">
        <File Id="ArgosExe" Source="dist/argos.exe" KeyPath="yes"/>
      </Component>
    </Directory>
    <Feature Id="ProductFeature" Title="Argos" Level="1">
      <ComponentRef Id="MainExecutable"/>
    </Feature>
  </Product>
</Wix>
EOF
  candle -out dist/argos.wixobj dist/argos.wxs 2>&1 || echo "WARN: candle 失败,跳 .msi"
  if [ -f dist/argos.wixobj ]; then
    light -out "dist/Argos-${ARGOS_VERSION}-x86_64.msi" dist/argos.wixobj 2>&1 || \
      echo "WARN: light 失败,跳 .msi"
    if [ -f "dist/Argos-${ARGOS_VERSION}-x86_64.msi" ]; then
      cd dist
      zip_with_powershell "Argos-${ARGOS_VERSION}-x86_64.msi" "Argos-${ARGOS_VERSION}-x86_64.msi.zip"
      cd ..
      $SHASUM "dist/Argos-${ARGOS_VERSION}-x86_64.msi.zip" 2>/dev/null || true
    fi
  fi
else
  echo "WARN: candle/light 不在 PATH(windows-latest 默认无 WiX 3),跳 .msi 产物(仅 .exe zip)"
fi

echo "=== Windows build done ==="
ls -la dist/ 2>/dev/null || true
