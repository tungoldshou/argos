#!/usr/bin/env bash
# Argos Windows 打包:PyInstaller onefile → .exe zip 主推 + .msi (可选 WiX 简化方案)。
# 跑在 windows-latest runner(spec D3 锁 .msi 失败仅警告,仅 .exe zip 兜底)。
# 注:本脚本在 windows-latest 跑;若本地 macOS 跑只是 syntax check,不能真产 .exe。
set -euo pipefail
cd "$(dirname "$0")/.."   # 仓库根

# 版本号(spec §2.6):CI ARGOS_VERSION > packaging/VERSION > unknown
if [ -z "${ARGOS_VERSION:-}" ]; then
  if [ -f packaging/VERSION ]; then
    ARGOS_VERSION=$(cat packaging/VERSION)
  else
    ARGOS_VERSION="0.0.0+unknown"
  fi
fi
export ARGOS_VERSION
echo "=== Building Argos $ARGOS_VERSION (windows) ==="

# 1. 清理 dist
rm -rf dist build
mkdir -p dist

# 2. 确保 pyinstaller 在 venv
uv run python -c "import PyInstaller" 2>/dev/null || uv add --dev pyinstaller

# 3. PyInstaller onefile(Windows 注意:用 ; 作 add-data 分隔符,不是 :)
PYI_ARGS=(
  --clean --noconfirm
  --name argos
  --onefile
  --console
  --add-data "argos_agent/memory/schema.sql;argos_agent/memory"
  --add-data "packaging/VERSION;packaging"
  --add-data "packaging/Info.plist;packaging"
  --collect-submodules smolagents
  --collect-submodules textual
  --collect-submodules argos_agent
  --collect-data-files textual
  --collect-data-files smolagents
  --copy-metadata argos-agent
  --exclude-module langchain
  --exclude-module langgraph
  --exclude-module fastapi
  --exclude-module uvicorn
  argos_agent/__main__.py
)
uv run pyinstaller "${PYI_ARGS[@]}"

BIN=dist/argos.exe
[ -f "$BIN" ] || { echo "FATAL: 缺 $BIN"; exit 1; }
file "$BIN" 2>/dev/null || true   # 期望 PE32+ executable

# 4. zip 打包(主推)
cd dist
zip "Argos-${ARGOS_VERSION}-x86_64-windows.zip" argos.exe
cd ..
SHASUM=shasum
command -v sha256sum >/dev/null 2>&1 && SHASUM=sha256sum
$SHASUM "dist/Argos-${ARGOS_VERSION}-x86_64-windows.zip" 2>/dev/null || true

# 5. .msi 简化方案(可选;spec D3 锁失败不卡,仅警告)
#    走 WiX (candle/light);若不在 PATH 跳(仅警告)
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
      zip "Argos-${ARGOS_VERSION}-x86_64.msi.zip" "Argos-${ARGOS_VERSION}-x86_64.msi"
      cd ..
      $SHASUM "dist/Argos-${ARGOS_VERSION}-x86_64.msi.zip" 2>/dev/null || true
    fi
  fi
else
  echo "WARN: candle/light 不在 PATH(windows-latest 默认无 WiX 3),跳 .msi 产物(仅 .exe zip)"
fi

echo "=== Windows build done ==="
ls -la dist/ 2>/dev/null || true
