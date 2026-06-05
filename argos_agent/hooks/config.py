"""Hooks 配置 dataclass + 加载/校验/缓存(spec §2.2 / §2.4 / D11)。

- `HookHandler` / `HookMatcherEntry` / `HooksConfig` 全部 frozen dataclass
  (immutability CRITICAL,CLAUDE.md 灵魂)。
- `load()` 手写最小校验(避免引入 jsonschema 依赖);坏配置 → `HooksConfigError`。
- 模块级 `_config: HooksConfig | None` 单例;`get_config()` 惰性加载,
  `reload_config()` 重新读盘(坏配置 → 保旧 + 报错,spec §3 / D11)。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

from argos_agent.hooks.schema import KNOWN_EVENTS, VALID_HANDLER_TYPES


class HooksConfigError(Exception):
    """hooks 配置加载 / 校验失败。坏配置 → 报错,绝不部分加载(spec D11)。"""


@dataclass(frozen=True, slots=True)
class HookHandler:
    """单条 hook 命令(MVP 仅 'command' 类型,spec D 不上 prompt/agent)。"""
    type: str
    command: str
    timeout: int = 60000   # ms,默认 60s(spec §2.2)

    def __post_init__(self) -> None:
        if self.type not in VALID_HANDLER_TYPES:
            raise ValueError(
                f"HookHandler.type 必须是 {sorted(VALID_HANDLER_TYPES)} 之一,收到 {self.type!r}"
            )
        if not self.command or not self.command.strip():
            raise ValueError("HookHandler.command 不能为空")
        if self.timeout <= 0:
            raise ValueError(f"HookHandler.timeout 必须 > 0 ms,收到 {self.timeout}")


@dataclass(frozen=True, slots=True)
class HookMatcherEntry:
    """同事件下的一个 matcher 段:matcher 正则(可空) + hooks 列表(并行跑)。"""
    matcher: str | None
    hooks: tuple[HookHandler, ...]   # tuple 保 frozen(不用 list)


@dataclass(frozen=True, slots=True)
class HooksConfig:
    """完整 hooks 配置:version + 事件名 → matcher entries 列表。"""
    version: int = 1
    entries: Mapping[str, tuple[HookMatcherEntry, ...]] = field(default_factory=dict)

    @staticmethod
    def empty() -> "HooksConfig":
        """全等 fire no-op 的空配置(spec §4.1:配置不存在 → EmptyHooksConfig)。"""
        return HooksConfig(version=1, entries={})
