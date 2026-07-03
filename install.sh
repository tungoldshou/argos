#!/usr/bin/env bash
set -euo pipefail

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

if uv tool list | grep -q "^argos-agent "; then
  uv tool upgrade argos-agent
else
  uv tool install argos-agent
fi

TOOL_BIN="$(uv tool dir --bin)"
"$TOOL_BIN/argos" --version
if ! command -v argos >/dev/null 2>&1; then
  echo "Argos installed at $TOOL_BIN/argos."
  echo "Run 'uv tool update-shell' if 'argos' is not on PATH."
fi
echo "Run 'argos setup' to configure Argos."
