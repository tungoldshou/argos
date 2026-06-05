"""Hooks 系统(spec 2026-06-06):用户自定义生命周期钩子。

对齐 Claude Code `~/.claude/hooks.json` 模型;独立于 `config.json`。
模块入口:
- `fire(event_name, payload, *, cwd, session_id) -> HookFireResult` 触发 hook
- `get_config() -> HooksConfig` 拿当前配置(惰性加载)
- `reload_config() -> HooksConfig` 重读盘(坏配置 → 保旧 + 报错)
详细文档见 spec。
"""
from __future__ import annotations

# 公开 API(实际实现后续 Task 补,本 Task 仅占位避免循环 import)
__all__ = [
    "HooksConfig",
    "HookHandler",
    "HookMatcherEntry",
    "HooksConfigError",
    "fire",
    "get_config",
    "reload_config",
]

# 模块级配置单例(同 plan_mode._plan_mode_active 模式,spec §2.5)
_config: "HooksConfig | None" = None


def get_config():  # type: ignore[no-untyped-def]
    """惰性加载 + 返回当前配置(下一 Task 实现)。"""
    raise NotImplementedError("hooks.get_config 将在 Task 3 实现")


def reload_config():  # type: ignore[no-untyped-def]
    """重读 ~/.argos/hooks.json(下一 Task 实现)。"""
    raise NotImplementedError("hooks.reload_config 将在 Task 3 实现")


async def fire(*args, **kwargs):  # type: ignore[no-untyped-def]
    """触发 hook(下一 Task 实现)。"""
    raise NotImplementedError("hooks.fire 将在 Task 5 实现")
