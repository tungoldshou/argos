from __future__ import annotations

from argos.lsp.config import (
    BUILTIN_DEFAULT_CONFIG,
    LspConfig,
    LspConfigError,
    LspServerConfig,
)

__all__ = [
    "LspConfig",
    "LspServerConfig",
    "LspConfigError",
    "get_manager",
    "get_config",
    "reload_config",
    "get_diagnostics",
    "_reset_config",
]

_config: LspConfig | None = None
_manager = None  # type: ignore[var-annotated]


def _reset_config() -> None:
    global _config, _manager
    _config = None
    _manager = None


def get_config() -> LspConfig:
    global _config
    if _config is None:
        from argos.lsp.config import load
        try:
            _config = load()
        except LspConfigError:
            _config = BUILTIN_DEFAULT_CONFIG
    return _config


def reload_config() -> LspConfig:
    from argos.lsp.config import load
    global _config
    new_cfg = load()
    _config = new_cfg
    return new_cfg


def get_manager():  # type: ignore[no-untyped-def]
    global _manager
    if _manager is None:
        from argos.lsp.manager import LspManager
        _manager = LspManager(get_config())
    return _manager


def get_diagnostics(file: str):  # type: ignore[no-untyped-def]
    if _manager is None:
        return None
    return _manager.get_diagnostics(file)  # type: ignore[union-attr]
