#!/usr/bin/env bash
# Argos Linux 打包:PyInstaller onefile → AppImage + .deb + .rpm 三种格式。
# spec §5 锁 AppImage 为主推(跨 glibc),.deb 走 apt 路线,.rpm 走 dnf 路线。
# 跑在 ubuntu-24.04 runner(本地装 fuse / dpkg-dev / rpm 即可)。
# Apple Silicon Mac 跑可加 ARGOS_TARGET=aarch64 出 ARM64 包。
set -euo pipefail
cd "$(dirname "$0")/.."   # 仓库根

# 版本号(spec §2.6):
# - 优先环境变量 ARGOS_VERSION(CI 从 git tag 解析用)
# - fallback 读 packaging/VERSION
if [ -z "${ARGOS_VERSION:-}" ]; then
  if [ -f packaging/VERSION ]; then
    ARGOS_VERSION=$(cat packaging/VERSION)
  else
    ARGOS_VERSION="0.0.0+unknown"
  fi
fi
export ARGOS_VERSION
echo "=== Building Argos $ARGOS_VERSION (linux) ==="

TARGET_ARCH="${ARGOS_TARGET:-x86_64}"
echo "   target arch: $TARGET_ARCH"

# 1. 确保 pyinstaller 在 venv
uv run python -c "import PyInstaller" 2>/dev/null || uv add --dev pyinstaller

# 2. 清理 dist(避免旧产物污染)
rm -rf dist build
mkdir -p dist

# 3. PyInstaller onefile(目标 arch 默认 amd64)
#    注:不用 packaging/argos.spec(macOS arm64 only);Linux 走 inline --add-data
PYI_ARGS=(
  --clean --noconfirm
  --target-arch "$TARGET_ARCH"
  --name argos
  --onefile
  --console
  --add-data "argos_agent/memory/schema.sql:argos_agent/memory"
  --add-data "packaging/VERSION:packaging"
  --add-data "packaging/Info.plist:packaging"
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

BIN=dist/argos
[ -f "$BIN" ] || { echo "FATAL: 缺 $BIN"; exit 1; }
chmod +x "$BIN"
file "$BIN" || true   # 期望 ELF 64-bit LSB executable

# 4. AppImage(主推,跨 glibc)
echo "=== Pack AppImage ==="
APPIMAGE_DIR=dist/Argos.AppDir
rm -rf "$APPIMAGE_DIR"
mkdir -p "$APPIMAGE_DIR/usr/bin" \
         "$APPIMAGE_DIR/usr/share/applications" \
         "$APPIMAGE_DIR/usr/share/icons/hicolor/256x256/apps"
cp "$BIN" "$APPIMAGE_DIR/usr/bin/argos"

cat > "$APPIMAGE_DIR/usr/share/applications/argos.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=Argos
GenericName=AI Agent
Exec=argos %F
Icon=argos
Terminal=true
Categories=Development;Utility;
EOF

# 简单占位 PNG(spec §D18 占位即可;v1.1 补真品牌)
# 1×1 透明 PNG(最小合法 PNG)
python3 - <<'PY'
import struct, zlib, sys
def png_1x1():
    sig = b'\x89PNG\r\n\x1a\n'
    ihdr = b'IHDR' + struct.pack('>II', 1, 1) + b'\x08\x06\x00\x00\x00'
    idat = b'IDAT' + zlib.compress(b'\x00\x00\x00\x00\x00')
    iend = b'IEND'
    def chunk(t, d):
        return struct.pack('>I', len(d)) + t + d + struct.pack('>I', zlib.crc32(t + d) & 0xffffffff)
    return sig + chunk(ihdr[:4], ihdr[4:]) + chunk(idat[:4], idat[4:]) + chunk(iend, b'')
for p in [
    'dist/Argos.AppDir/usr/share/icons/hicolor/256x256/apps/argos.png',
    'dist/Argos.AppDir/argos.png',
]:
    with open(p, 'wb') as f:
        f.write(png_1x1())
PY

cat > "$APPIMAGE_DIR/AppRun" <<'EOF'
#!/usr/bin/env bash
exec "$(dirname "$0")/usr/bin/argos" "$@"
EOF
chmod +x "$APPIMAGE_DIR/AppRun"

# appimagetool(若没装,下到 /tmp)
if [ ! -x /usr/local/bin/appimagetool ] && [ ! -x ./appimagetool ]; then
  echo "   下载 appimagetool..."
  if [ "$TARGET_ARCH" = "x86_64" ]; then
    curl -fsSL -o /tmp/appimagetool \
      "https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage" \
      || { echo "WARN: appimagetool 下载失败,跳 AppImage"; }
  else
    curl -fsSL -o /tmp/appimagetool \
      "https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-aarch64.AppImage" \
      || { echo "WARN: appimagetool 下载失败,跳 AppImage"; }
  fi
  if [ -f /tmp/appimagetool ]; then
    chmod +x /tmp/appimagetool
    APPIMAGETOOL=/tmp/appimagetool
  fi
else
  APPIMAGETOOL=$(command -v appimagetool || echo /tmp/appimagetool)
fi

if [ -x "${APPIMAGETOOL:-/nonexistent}" ] || ([ -f "${APPIMAGETOOL:-/nonexistent}" ] && [ -x "${APPIMAGETOOL:-/nonexistent}" ]); then
  cd dist
  ARCH_DIR=$([ "$TARGET_ARCH" = "x86_64" ] && echo x86_64 || echo aarch64)
  "$APPIMAGETOOL" Argos.AppDir "Argos-${ARGOS_VERSION}-${ARCH_DIR}.AppImage" 2>&1 || \
    echo "WARN: appimagetool 失败,跳 AppImage 产物"
  cd ..
  if [ -f "dist/Argos-${ARGOS_VERSION}-${ARCH_DIR}.AppImage" ]; then
    chmod +x "dist/Argos-${ARGOS_VERSION}-${ARCH_DIR}.AppImage"
    shasum -a 256 "dist/Argos-${ARGOS_VERSION}-${ARCH_DIR}.AppImage"
  fi
else
  echo "WARN: 无 appimagetool,跳 AppImage 产物"
fi

# 5. .deb(走 dpkg-deb,免 fpm)
echo "=== Pack .deb ==="
DEB_DIR=dist/argos-deb
rm -rf "$DEB_DIR"
mkdir -p "$DEB_DIR/DEBIAN" "$DEB_DIR/usr/bin" "$DEB_DIR/usr/share/applications" \
         "$DEB_DIR/usr/share/icons/hicolor/256x256/apps"

cat > "$DEB_DIR/DEBIAN/control" <<EOF
Package: argos-agent
Version: ${ARGOS_VERSION}
Section: utils
Priority: optional
Architecture: amd64
Maintainer: tungoldshou <tungoldshou@users.noreply.github.com>
Description: Argos — 诚实可靠的终端编码超级智能体
 Argos is a terminal super-agent (TUI) with self-built CodeAct engine,
 verify hard-gate, and OS sandbox.
Depends: libc6, libstdc++6
EOF
cp "$BIN" "$DEB_DIR/usr/bin/argos"
chmod 755 "$DEB_DIR/usr/bin/argos"
cp "$APPIMAGE_DIR/usr/share/applications/argos.desktop" \
   "$DEB_DIR/usr/share/applications/argos.desktop" 2>/dev/null || true
cp "dist/Argos.AppDir/usr/share/icons/hicolor/256x256/apps/argos.png" \
   "$DEB_DIR/usr/share/icons/hicolor/256x256/apps/argos.png" 2>/dev/null || true

if command -v dpkg-deb >/dev/null 2>&1; then
  DEB_ARCH=$([ "$TARGET_ARCH" = "x86_64" ] && echo amd64 || echo arm64)
  dpkg-deb --build --root-owner-group "$DEB_DIR" "dist/argos_${ARGOS_VERSION}_${DEB_ARCH}.deb"
  shasum -a 256 "dist/argos_${ARGOS_VERSION}_${DEB_ARCH}.deb" 2>/dev/null || \
    sha256sum "dist/argos_${ARGOS_VERSION}_${DEB_ARCH}.deb"
else
  echo "WARN: dpkg-deb 不在 PATH(非 ubuntu 主机),跳 .deb 产物"
fi

# 6. .rpm(走 rpmbuild)
echo "=== Pack .rpm ==="
if command -v rpmbuild >/dev/null 2>&1; then
  RPMBUILD_DIR=dist/rpmbuild
  rm -rf "$RPMBUILD_DIR"
  mkdir -p "$RPMBUILD_DIR"/{BUILD,RPMS,SOURCES,SPECS,SRPMS}
  cat > "$RPMBUILD_DIR/SPECS/argos.spec" <<EOF
Name: argos-agent
Version: ${ARGOS_VERSION}
Release: 1%{?dist}
Summary: Argos — terminal super-agent (CodeAct + verify gate)
License: MIT
URL: https://github.com/tungoldshou/argos
Requires: glibc, libstdc++
%description
Argos is a terminal super-agent with self-built CodeAct engine, verify
hard-gate, and OS sandbox.
%install
mkdir -p %{buildroot}/usr/bin
cp ${BIN} %{buildroot}/usr/bin/argos
chmod 755 %{buildroot}/usr/bin/argos
%files
/usr/bin/argos
EOF
  rpmbuild --define "_topdir $RPMBUILD_DIR" -bb "$RPMBUILD_DIR/SPECS/argos.spec" || \
    echo "WARN: rpmbuild 失败,跳 .rpm 产物"
  RPM_ARCH=$([ "$TARGET_ARCH" = "x86_64" ] && echo x86_64 || echo aarch64)
  if ls "$RPMBUILD_DIR"/RPMS/"${RPM_ARCH}"/argos-agent-*.rpm 2>/dev/null; then
    cp "$RPMBUILD_DIR"/RPMS/"${RPM_ARCH}"/argos-agent-*.rpm dist/
    # 重命名对齐 spec
    mv dist/argos-agent-${ARGOS_VERSION}-1.*."${RPM_ARCH}".rpm \
       "dist/argos-${ARGOS_VERSION}-1.${RPM_ARCH}.rpm" 2>/dev/null || true
    shasum -a 256 dist/argos-*.rpm 2>/dev/null || sha256sum dist/argos-*.rpm
  fi
else
  echo "WARN: rpmbuild 不在 PATH(非 fedora/rhel 主机),跳 .rpm 产物"
fi

echo "=== Linux build done ==="
ls -la dist/ 2>/dev/null || true
