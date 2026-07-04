#!/usr/bin/env bash
# Deferred binary installer; not the public launch installer.
# Public launch install uses root install.sh -> latest release uv tool install.
# This script is kept for future macOS arm64 release assets.
set -euo pipefail

REPO="tungoldshou/argos"
INSTALL_DIR="/Applications"
BIN_LINK="/usr/local/bin/argos"
APP_NAME="Argos.app"

ARCH=$(uname -m)
[ "$ARCH" = "arm64" ] || {
  echo "ERROR: Argos installer requires macOS arm64; got $ARCH."
  echo "       Use root install.sh, uv tool, or source checkout for the public launch path."
  exit 1
}
[ "$(uname -s)" = "Darwin" ] || {
  echo "ERROR: Argos installer requires macOS (Darwin); got $(uname -s)."
  exit 1
}

echo "→ Fetching latest release info..."
LATEST_JSON=$(curl -fsSL "https://api.github.com/repos/$REPO/releases/latest" 2>&1) || {
  echo "ERROR: Failed to fetch release info from GitHub (curl exit $?)."
  echo "       Check network: curl https://api.github.com/repos/$REPO/releases/latest"
  exit 1
}
TAG=$(echo "$LATEST_JSON" | python3 -c "import sys, json; print(json.load(sys.stdin).get('tag_name', '').lstrip('v'))" 2>/dev/null) || true
[ -n "$TAG" ] || {
  echo "ERROR: Could not parse tag_name from GitHub response."
  exit 1
}
TARBALL_URL=$(echo "$LATEST_JSON" | python3 -c "import sys, json; d=json.load(sys.stdin); [print(a['browser_download_url']) for a in d.get('assets', []) if a['name'].endswith('arm64-mac.tar.gz')]" 2>/dev/null | head -1)
[ -n "$TARBALL_URL" ] || {
  echo "ERROR: Could not find Argos-${TAG}-arm64-mac.tar.gz asset in latest release."
  exit 1
}
SHA256_URL=$(echo "$LATEST_JSON" | python3 -c "import sys, json; d=json.load(sys.stdin); [print(a['browser_download_url']) for a in d.get('assets', []) if a['name'] == 'SHA256SUMS']" 2>/dev/null | head -1)

TMP_DIR=$(mktemp -d -t argos-install.XXXXXX)
trap 'rm -rf "$TMP_DIR"' EXIT
TARBALL="$TMP_DIR/Argos-${TAG}-arm64-mac.tar.gz"
echo "→ Downloading Argos $TAG..."
curl -fsSL "$TARBALL_URL" -o "$TARBALL" || {
  echo "ERROR: Download failed (curl exit $?)."
  exit 1
}

[ -n "$SHA256_URL" ] || {
  echo "ERROR: Could not find SHA256SUMS asset in latest release."
  exit 1
}
echo "→ Verifying SHA256..."
SHA256_FILE="$TMP_DIR/SHA256SUMS"
curl -fsSL "$SHA256_URL" -o "$SHA256_FILE" || {
  echo "ERROR: Could not fetch SHA256SUMS."
  exit 1
}
EXPECTED=$(grep "Argos-${TAG}-arm64-mac.tar.gz" "$SHA256_FILE" | awk '{print $1}')
[ -n "$EXPECTED" ] || {
  echo "ERROR: Could not find checksum for Argos-${TAG}-arm64-mac.tar.gz."
  exit 1
}
ACTUAL=$(shasum -a 256 "$TARBALL" | awk '{print $1}')
if [ "$EXPECTED" != "$ACTUAL" ]; then
  echo "ERROR: SHA256 mismatch. Expected: $EXPECTED, Got: $ACTUAL"
  exit 1
fi
echo "   ✓ SHA256 verified"

echo "→ Installing to $INSTALL_DIR/$APP_NAME..."
if [ -w "$INSTALL_DIR" ]; then
  tar -xzf "$TARBALL" -C "$TMP_DIR/"
  rm -rf "$INSTALL_DIR/$APP_NAME"
  mv "$TMP_DIR/$APP_NAME" "$INSTALL_DIR/$APP_NAME"
else
  echo "   /Applications not writable, need sudo..."
  sudo tar -xzf "$TARBALL" -C "$TMP_DIR/"
  sudo rm -rf "$INSTALL_DIR/$APP_NAME"
  sudo mv "$TMP_DIR/$APP_NAME" "$INSTALL_DIR/$APP_NAME"
fi

BIN_PATH="$INSTALL_DIR/$APP_NAME/Contents/MacOS/argos"
if [ -f "$BIN_PATH" ]; then
  echo "→ Creating symlink $BIN_LINK → $BIN_PATH"
  if [ -w "$(dirname "$BIN_LINK")" ]; then
    ln -sf "$BIN_PATH" "$BIN_LINK"
  else
    sudo ln -sf "$BIN_PATH" "$BIN_LINK"
  fi
fi

echo ""
echo "✓ Argos $TAG installed at $INSTALL_DIR/$APP_NAME"
echo "  Run 'argos' from terminal, or double-click the app icon."
echo "  To uninstall: rm -rf $INSTALL_DIR/$APP_NAME && rm $BIN_LINK"
