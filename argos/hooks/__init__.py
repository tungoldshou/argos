from __future__ import annotations

from argos.hooks.config import (
    HookHandler,
    HookMatcherEntry,
    HooksConfig,
    HooksConfigError,
)
from argos.hooks.runner import HookFireResult

__all__ = [
    "HooksConfig",
    "HookHandler",
    "HookMatcherEntry",
    "HooksConfigError",
    "fire",
    "get_config",
    "reload_config",
    "HookFireResult",
    "_reset_config",
]


_config: HooksConfig | None = None


def _reset_config() -> None:
    global _config
    _config = None


def get_config() -> HooksConfig:
    global _config
    if _config is None:
        _config = _load_or_empty()
    return _config


def _load_or_empty() -> HooksConfig:
    from argos.hooks.config import load
    return load()


def reload_config() -> HooksConfig:
    from argos.hooks.config import load, HooksConfigError
    global _config
    try:
        new_cfg = load()
    except HooksConfigError:
        raise
    _config = new_cfg
    return _config


async def fire(*args, **kwargs):  # type: ignore[no-untyped-def]
    from argos.hooks.runner import fire as _fire
    return await _fire(*args, **kwargs)
