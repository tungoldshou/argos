"""Hooks 配置 dataclass + 加载/校验/缓存(spec §2.2 / §2.4 / D11)。

- `HookHandler` / `HookMatcherEntry` / `HooksConfig` 全部 frozen dataclass
  (immutability CRITICAL,CLAUDE.md 灵魂)。
- `load()` 走 config_base.read_json_file 抽样板(任务);坏配置 → `HooksConfigError`。
- 模块级 `_config: HooksConfig | None` 单例在 `hooks/__init__.py`(load_or_empty 包 try/except
  静默回 empty,reload 坏配置保旧+抛;与本模块 load() 行为正交)。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

from argos import config_base
from argos.hooks.schema import KNOWN_EVENTS, VALID_HANDLER_TYPES


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


# ── 加载 / 校验(spec §2.2 / §3 / D11)────────────────────────────────────

HOOKS_CONFIG_PATH: Path = Path.home() / ".argos" / "hooks.json"


def _validate_event_name(event_name: str) -> None:
    if event_name not in KNOWN_EVENTS:
        raise HooksConfigError(
            f"未知事件名 (event) {event_name!r};允许: {sorted(KNOWN_EVENTS)}"
        )


def _parse_handler(raw: dict) -> HookHandler:
    if not isinstance(raw, dict):
        raise HooksConfigError(f"hook handler 必须是 dict,收到 {type(raw).__name__}")
    if "type" not in raw:
        raise HooksConfigError("hook handler 缺 'type' 字段")
    if "command" not in raw:
        raise HooksConfigError("hook handler 缺 'command' 字段")
    timeout = raw.get("timeout", 60000)
    try:
        return HookHandler(type=raw["type"], command=raw["command"], timeout=timeout)
    except ValueError as e:
        raise HooksConfigError(f"hook handler 非法: {e}") from e


def _parse_entry(raw: dict) -> HookMatcherEntry:
    if not isinstance(raw, dict):
        raise HooksConfigError(f"matcher entry 必须是 dict,收到 {type(raw).__name__}")
    if "hooks" not in raw:
        raise HooksConfigError("matcher entry 缺 'hooks' 字段")
    raw_hooks = raw["hooks"]
    if not isinstance(raw_hooks, list) or not raw_hooks:
        raise HooksConfigError("matcher entry 'hooks' 必须是非空 array")
    matcher = raw.get("matcher")
    if matcher is not None and not isinstance(matcher, str):
        raise HooksConfigError(f"matcher 必须是 string 或省略,收到 {type(matcher).__name__}")
    # 加载期 matcher 编译校验(spec D14:长度 / ReDoS / re.error)
    # matcher 为 None / 空串 / '*' 的语义化处理归 _MATCHER_USED_EVENTS 路径,
    # 校验只对"真要编译"的字符串生效——空串虽能 compile 但语义无意义,这里拒。
    if matcher is not None and matcher != "" and matcher != "*":
        from argos.hooks.matcher import validate_matcher
        validate_matcher(matcher)
    handlers = tuple(_parse_handler(h) for h in raw_hooks)
    return HookMatcherEntry(matcher=matcher, hooks=handlers)


def load(path: Path | None = None) -> HooksConfig:
    """加载 + 校验 ~/.argos/hooks.json。文件不存在 → empty()(spec §3)。

    任务:JSON 读 + 解析走 config_base.read_json_file(OSError 行为保持原"显式抛"语义)。
    hooks 专属的"未知 event 名 / matcher ReDoS 校验"留在本函数(领域校验不抽)。

    Args:
        path: 显式路径(测试用);None 时读 HOOKS_CONFIG_PATH。

    Returns:
        HooksConfig 实例。

    Raises:
        HooksConfigError: JSON 坏字 / 字段类型错 / version 不匹配 / 未知 event。
    """
    p = path or HOOKS_CONFIG_PATH
    data = config_base.read_json_file(p, ErrorCls=HooksConfigError)
    if data is None:
        # 文件不存在 → 走 empty()(spec §3)
        return HooksConfig.empty()
    if "version" not in data:
        raise HooksConfigError("hooks.json 缺 'version' 字段")
    if data["version"] != 1:
        raise HooksConfigError(
            f"hooks.json version={data['version']} 不匹配(host 仅支持 v1)"
        )
    raw_hooks = data.get("hooks", {})
    if not isinstance(raw_hooks, dict):
        raise HooksConfigError("'hooks' 必须是 object(事件名 → matcher entries)")
    entries: dict[str, tuple[HookMatcherEntry, ...]] = {}
    for event_name, raw_entries in raw_hooks.items():
        _validate_event_name(event_name)
        if not isinstance(raw_entries, list):
            raise HooksConfigError(f"事件 {event_name!r} 的 entries 必须是 array")
        entries[event_name] = tuple(_parse_entry(e) for e in raw_entries)
    return HooksConfig(version=1, entries=entries)
