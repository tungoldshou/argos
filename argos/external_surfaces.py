"""Warnings for external surface files.

External surface config is discovered at ARGOS_CONFIG_DIR/mcp.json,
ARGOS_CONFIG_DIR/lsp.json, and ARGOS_CONFIG_DIR/hooks.json.
"""
from __future__ import annotations

from pathlib import Path

from argos import config
from argos.i18n import t

_SURFACE_KEYS: tuple[tuple[str, str], ...] = (
    ("hooks.json", "core2.external.hooks"),
    ("lsp.json", "core2.external.lsp"),
    ("mcp.json", "core2.external.mcp"),
)


def external_surface_warnings(argos_dir: Path | None = None) -> list[str]:
    base = argos_dir if argos_dir is not None else config.config_dir()
    out: list[str] = []
    for filename, key in _SURFACE_KEYS:
        path = base / filename
        if path.exists():
            out.append(t(key, path=path))
    return out
