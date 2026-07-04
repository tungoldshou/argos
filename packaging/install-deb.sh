#!/usr/bin/env bash
# Deferred binary installer; not the public launch installer.
# Public launch install uses root install.sh -> GitHub source uv tool install.
# This script is kept for future Linux .deb release assets.
set -euo pipefail

REPO="tungoldshou/argos"

[ "$(uname -s)" = "Linux" ] || {
  echo "ERROR: Argos .deb installer requires Linux; got $(uname -s)."
  echo "       Use root install.sh, uv tool, or source checkout for the public launch path."
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

DEB_URL=$(echo "$LATEST_JSON" | python3 -c "
import sys, json
d = json.load(sys.stdin)
for a in d.get('assets', []):
    if a['name'].endswith('.deb'):
        print(a['browser_download_url']); break
" 2>/dev/null | head -1)
[ -n "$DEB_URL" ] || {
  echo "ERROR: 未找到 .deb 资产 in latest release;Argos 暂未发 Linux .deb 版本。"
  echo "       Fallback:"
  echo "         git clone https://github.com/tungoldshou/argos"
  echo "         cd argos && uv sync && uv run argos"
  exit 1
}
DEB_NAME=$(basename "$DEB_URL")

SHA256_URL=$(echo "$LATEST_JSON" | python3 -c "
import sys, json
d = json.load(sys.stdin)
for a in d.get('assets', []):
    if a['name'] == 'SHA256SUMS':
        print(a['browser_download_url']); break
" 2>/dev/null | head -1)

TMP_DIR=$(mktemp -d -t argos-install-deb.XXXXXX)
trap 'rm -rf "$TMP_DIR"' EXIT
DEB_PATH="$TMP_DIR/$DEB_NAME"
echo "→ Downloading Argos $TAG (.deb)..."
curl -fsSL "$DEB_URL" -o "$DEB_PATH" || {
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
EXPECTED=$(grep "$DEB_NAME" "$SHA256_FILE" | awk '{print $1}')
[ -n "$EXPECTED" ] || {
  echo "ERROR: Could not find checksum for $DEB_NAME."
  exit 1
}
ACTUAL=$(sha256sum "$DEB_PATH" | awk '{print $1}')
if [ "$EXPECTED" != "$ACTUAL" ]; then
  echo "ERROR: SHA256 mismatch. Expected: $EXPECTED, Got: $ACTUAL"
  exit 1
fi
echo "   ✓ SHA256 verified"

echo "→ Installing $DEB_NAME..."
if [ "$(id -u)" = "0" ]; then
  dpkg -i "$DEB_PATH" || apt-get install -f -y
else
  echo "   需要 sudo 装..."
  sudo dpkg -i "$DEB_PATH" || sudo apt-get install -f -y
fi

echo ""
echo "✓ Argos $TAG installed."
echo "  Run 'argos --version' to verify;or 'argos' to launch."
echo "  To uninstall: sudo apt remove argos-agent"
