#!/usr/bin/env bash
set -euo pipefail

ARGOS_INSTALL_REF="${ARGOS_INSTALL_REF:-}"
ARGOS_REPO_URL="${ARGOS_REPO_URL:-https://github.com/tungoldshou/argos.git}"
ARGOS_RELEASES_URL="${ARGOS_RELEASES_URL:-https://api.github.com/repos/tungoldshou/argos/releases/latest}"

if [ -z "$ARGOS_INSTALL_REF" ]; then
  echo "Resolving latest Argos release..."
  LATEST_JSON="$(curl -fsSL "$ARGOS_RELEASES_URL")" || {
    echo "Could not resolve the latest Argos release."
    echo "For development installs, rerun with ARGOS_INSTALL_REF=main."
    exit 1
  }
  ARGOS_INSTALL_REF="$(printf '%s\n' "$LATEST_JSON" | sed -n 's/.*"tag_name"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -n 1)"
fi

if [ -z "$ARGOS_INSTALL_REF" ]; then
  echo "Could not find a release tag in the latest Argos release response."
  echo "For development installs, rerun with ARGOS_INSTALL_REF=main."
  exit 1
fi

if ! command -v uv >/dev/null 2>&1; then
  echo "Installing uv..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
fi

if ! command -v uv >/dev/null 2>&1; then
  echo "uv installation finished, but uv is not on PATH."
  echo "Open a new shell or add $HOME/.local/bin to PATH, then rerun this script."
  exit 1
fi

PACKAGE_SPEC="argos-agent @ git+${ARGOS_REPO_URL}@${ARGOS_INSTALL_REF}"

echo "Installing Argos from ${ARGOS_REPO_URL}@${ARGOS_INSTALL_REF}..."
uv tool install --force "$PACKAGE_SPEC"

TOOL_BIN="$(uv tool dir --bin)"
"$TOOL_BIN/argos" --version
if ! command -v argos >/dev/null 2>&1; then
  echo "Argos installed at $TOOL_BIN/argos."
  echo "Run 'uv tool update-shell' if 'argos' is not on PATH."
fi
echo "Run 'argos setup' to configure Argos."
