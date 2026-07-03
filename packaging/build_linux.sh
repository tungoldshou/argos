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
echo "=== Building Argos $ARGOS_VERSION (linux) ==="

TARGET_ARCH="${ARGOS_TARGET:-x86_64}"
echo "   target arch: $TARGET_ARCH"

uv run python -c "import PyInstaller" 2>/dev/null || uv add --dev pyinstaller

rm -rf dist build
mkdir -p dist

PYI_ARGS=(
  --clean --noconfirm
  --target-arch "$TARGET_ARCH"
  --name argos
  --onefile
  --console
  --add-data "argos/memory/schema.sql:argos/memory"
  --add-data "packaging/VERSION:packaging"
  --add-data "packaging/Info.plist:packaging"
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

BIN=dist/argos
[ -f "$BIN" ] || { echo "FATAL: 缺 $BIN"; exit 1; }
chmod +x "$BIN"
file "$BIN" || true

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

if [ ! -x /usr/local/bin/appimagetool ] && [ ! -x ./appimagetool ]; then
  echo "   下载 appimagetool..."
  if [ "$TARGET_ARCH" = "x86_64" ]; then
    curl -fsSL -o /tmp/appimagetool \
      "https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage" \
      || { echo "FATAL: appimagetool download failed"; exit 1; }
  else
    curl -fsSL -o /tmp/appimagetool \
      "https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-aarch64.AppImage" \
      || { echo "FATAL: appimagetool download failed"; exit 1; }
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
  "$APPIMAGETOOL" Argos.AppDir "Argos-${ARGOS_VERSION}-${ARCH_DIR}.AppImage" 2>&1 || {
    echo "FATAL: appimagetool failed"
    exit 1
  }
  cd ..
  if [ -f "dist/Argos-${ARGOS_VERSION}-${ARCH_DIR}.AppImage" ]; then
    chmod +x "dist/Argos-${ARGOS_VERSION}-${ARCH_DIR}.AppImage"
    shasum -a 256 "dist/Argos-${ARGOS_VERSION}-${ARCH_DIR}.AppImage"
  fi
else
  echo "FATAL: appimagetool not found"
  exit 1
fi

[ -f "dist/Argos-${ARGOS_VERSION}-${ARCH_DIR}.AppImage" ] || {
  echo "FATAL: AppImage missing"
  exit 1
}

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
Description: Argos — 诚实可靠的百眼终端编码智能体
 Argos is the hundred-eyed terminal coding agent (TUI) with a self-built CodeAct
 engine, a verify hard-gate, and an opt-in OS sandbox.
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
  echo "FATAL: dpkg-deb not found" >&2
  exit 1
fi

echo "=== Pack .rpm ==="
command -v rpmbuild >/dev/null 2>&1 || {
  echo "FATAL: rpmbuild not found" >&2
  exit 1
}
RPMBUILD_DIR=dist/rpmbuild
rm -rf "$RPMBUILD_DIR"
mkdir -p "$RPMBUILD_DIR"/{BUILD,RPMS,SOURCES,SPECS,SRPMS}
cat > "$RPMBUILD_DIR/SPECS/argos.spec" <<EOF
Name: argos-agent
Version: ${ARGOS_VERSION}
Release: 1%{?dist}
Summary: Argos — the hundred-eyed agent (CodeAct + verify gate)
License: MIT
URL: https://github.com/tungoldshou/argos
Requires: glibc, libstdc++
%description
Argos is the hundred-eyed terminal coding agent with a self-built CodeAct
engine, a verify hard-gate, and an opt-in OS sandbox.
%install
mkdir -p %{buildroot}/usr/bin
cp ${BIN} %{buildroot}/usr/bin/argos
chmod 755 %{buildroot}/usr/bin/argos
%files
/usr/bin/argos
EOF
rpmbuild --define "_topdir $RPMBUILD_DIR" -bb "$RPMBUILD_DIR/SPECS/argos.spec" || {
  echo "FATAL: rpmbuild failed" >&2
  exit 1
}
RPM_ARCH=$([ "$TARGET_ARCH" = "x86_64" ] && echo x86_64 || echo aarch64)
if ls "$RPMBUILD_DIR"/RPMS/"${RPM_ARCH}"/argos-agent-*.rpm 2>/dev/null; then
  cp "$RPMBUILD_DIR"/RPMS/"${RPM_ARCH}"/argos-agent-*.rpm dist/
  mv dist/argos-agent-${ARGOS_VERSION}-1.*."${RPM_ARCH}".rpm \
     "dist/argos-${ARGOS_VERSION}-1.${RPM_ARCH}.rpm"
  [ -f "dist/argos-${ARGOS_VERSION}-1.${RPM_ARCH}.rpm" ] || {
    echo "FATAL: RPM asset missing" >&2
    exit 1
  }
  shasum -a 256 "dist/argos-${ARGOS_VERSION}-1.${RPM_ARCH}.rpm" 2>/dev/null || \
    sha256sum "dist/argos-${ARGOS_VERSION}-1.${RPM_ARCH}.rpm"
else
  echo "FATAL: RPM missing" >&2
  exit 1
fi

echo "=== Linux build done ==="
ls -la dist/ 2>/dev/null || true
