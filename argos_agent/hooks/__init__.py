"""Hooks 系统(spec 2026-06-06):用户自定义生命周期钩子。"""
from __future__ import annotations

from argos_agent.hooks.config import (
    HookHandler,
    HookMatcherEntry,
    HooksConfig,
    HooksConfigError,
)
from argos_agent.hooks.runner import HookFireResult

__all__ = [
    "HooksConfig",
    "HookHandler",
    "HookMatcherEntry",
    "HooksConfigError",
    "fire",
    "get_config",
    "reload_config",
    "HookFireResult",
    # 测试需要(确认单例被替换):
    "_reset_config",
]


# 模块级配置单例(同 plan_mode._plan_mode_active 模式,spec §2.5)
_config: HooksConfig | None = None


def _reset_config() -> None:
    """清空单例(测试用)。"""
    global _config
    _config = None


def get_config() -> HooksConfig:
    """惰性加载 + 返回当前配置。模块级单例;`reload_config()` 改它。"""
    global _config
    if _config is None:
        _config = _load_or_empty()
    return _config


def _load_or_empty() -> HooksConfig:
    """加载 hooks.json;失败 → empty() + 静默吞(spec §3 不存在行)。
    真正的 HooksConfigError 在 reload_config() 抛(用户显式 /hooks reload)。"""
    from argos_agent.hooks.config import load, HooksConfigError
    try:
        return load()
    except HooksConfigError:
        return HooksConfig.empty()


def reload_config() -> HooksConfig:
    """重读 ~/.argos/hooks.json。坏配置 → 保旧 + 抛 HooksConfigError(spec §3)。"""
    from argos_agent.hooks.config import load, HooksConfigError
    global _config
    try:
        new_cfg = load()
    except HooksConfigError:
        # 保旧(spec §3 reload 行)
        if _config is None:
            _config = HooksConfig.empty()
        raise
    _config = new_cfg
    return _config


async def fire(*args, **kwargs):  # type: ignore[no-untyped-def]
    """触发 hook(转发到 runner.fire,避免循环 import)。"""
    from argos_agent.hooks.runner import fire as _fire
    return await _fire(*args, **kwargs)
