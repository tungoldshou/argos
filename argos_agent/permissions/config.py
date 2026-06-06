"""PermissionsConfig dataclass + JSON 加载/校验/单例(spec §2.5, D3 / D19 / D20)。"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, Mapping, Sequence

from argos_agent.permissions.schema import VALID_LEVELS

_log = logging.getLogger("argos.permissions")

# 默认路径
CONFIG_PATH: Final[Path] = Path(os.path.expanduser("~/.argos/permissions.json"))


# ReDoS 危险模式(同 hooks D14 防 ReDoS)
_REDOS_PATTERNS: Final[tuple[str, ...]] = (
    r"\(\.\*\)\*",  # (.*)*
    r"\(\.\+\)\+",  # (.+)+
    r"\(\.\*\)\+",  # (.*)+
    r"\(\.\+\)\*",  # (.+)*
)


class PermissionsConfigError(Exception):
    """permissions.json 加载 / 校验失败。"""


def _is_safe_regex(matcher: str) -> bool:
    """防 ReDoS:长度 > 256 / ReDoS 模式 → False。"""
    if not isinstance(matcher, str):
        return False
    if len(matcher) > 256:
        return False
    for pat in _REDOS_PATTERNS:
        if re.search(pat, matcher):
            return False
    try:
        re.compile(matcher)
        return True
    except re.error:
        return False


@dataclass(frozen=True, slots=True)
class RuleEntry:
    """单条软规则 entry。matcher 走 re.search 语义。"""
    tool: str
    matcher: str


@dataclass(frozen=True, slots=True)
class ToolLevelOverride:
    """per-tool 档位覆盖(D4 锁)。"""
    tool: str
    level: str  # observe / propose / confirm / auto / accept_edits


@dataclass(frozen=True, slots=True)
class PermissionsConfig:
    version: int = 1
    default_level: str | None = None   # None = 沿用 ApprovalGate.level
    tools: Mapping[str, str] = field(default_factory=dict)
    allow: tuple[RuleEntry, ...] = ()
    deny: tuple[RuleEntry, ...] = ()
    ask: tuple[RuleEntry, ...] = ()

    def __post_init__(self) -> None:
        if self.default_level is not None and self.default_level not in VALID_LEVELS:
            raise ValueError(
                f"default_level {self.default_level!r} 非法,需 ∈ {sorted(VALID_LEVELS)}"
            )
        for tool, level in self.tools.items():
            if level not in VALID_LEVELS:
                raise ValueError(
                    f"tool level {level!r} for {tool!r} 非法,需 ∈ {sorted(VALID_LEVELS)}"
                )

    @staticmethod
    def empty() -> "PermissionsConfig":
        """D20 锁:无 permissions.json 时用 empty(沿用 ApprovalGate.level)。"""
        return PermissionsConfig(version=1)

    def match_allow(self, tool: str, arg_str: str) -> RuleEntry | None:
        for e in self.allow:
            if e.tool == tool and _matcher_match(e.matcher, arg_str):
                return e
        return None

    def match_deny(self, tool: str, arg_str: str) -> RuleEntry | None:
        for e in self.deny:
            if e.tool == tool and _matcher_match(e.matcher, arg_str):
                return e
        return None

    def match_ask(self, tool: str, arg_str: str) -> RuleEntry | None:
        for e in self.ask:
            if e.tool == tool and _matcher_match(e.matcher, arg_str):
                return e
        return None


def _matcher_match(matcher: str, arg_str: str) -> bool:
    """re.search 语义(空 / "*" = 全匹配)。"""
    if not matcher or matcher == "*":
        return True
    try:
        return bool(re.search(matcher, arg_str))
    except re.error:
        return False


def _safe_rule_entries(arr: Sequence[dict]) -> tuple[RuleEntry, ...]:
    """逐条校验;坏 entry 跳过 + log warning(不整体禁用)。"""
    out: list[RuleEntry] = []
    for ent in arr:
        if not isinstance(ent, dict):
            continue
        tool = ent.get("tool")
        matcher = ent.get("matcher", "")
        if not isinstance(tool, str) or not tool:
            continue
        if not _is_safe_regex(matcher):
            _log.warning(
                "permissions: skip soft rule (unsafe regex) tool=%r matcher=%r", tool, matcher,
            )
            continue
        out.append(RuleEntry(tool=tool, matcher=matcher))
    return tuple(out)


def load(path: Path | None = None) -> PermissionsConfig:
    """加载 permissions.json。
    缺文件 → empty()(D20);JSON 坏 / 校验失败 → PermissionsConfigError(spec D11 不部分加载)。"""
    p = path or CONFIG_PATH
    if not p.exists():
        return PermissionsConfig.empty()
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise PermissionsConfigError(f"permissions.json JSON 解析失败: {e}") from e
    if not isinstance(raw, dict):
        raise PermissionsConfigError("permissions.json 必须是 JSON object")
    version = raw.get("version")
    if version != 1:
        raise PermissionsConfigError(
            f"permissions.json version 必须 = 1,收到 {version!r}(v2 留 v1.1)"
        )
    default_level = raw.get("default_level")
    if default_level is not None and default_level not in VALID_LEVELS:
        raise PermissionsConfigError(
            f"default_level {default_level!r} 非法,需 ∈ {sorted(VALID_LEVELS)}"
        )
    tools = raw.get("tools") or {}
    if not isinstance(tools, dict):
        raise PermissionsConfigError("tools 必须是 object")
    tools_clean: dict[str, str] = {}
    for k, v in tools.items():
        if isinstance(k, str) and isinstance(v, str) and v in VALID_LEVELS:
            tools_clean[k] = v
        else:
            _log.warning(
                "permissions: skip tool override (invalid) tool=%r level=%r", k, v,
            )
    allow = _safe_rule_entries(raw.get("allow") or [])
    deny = _safe_rule_entries(raw.get("deny") or [])
    ask = _safe_rule_entries(raw.get("ask") or [])
    return PermissionsConfig(
        version=1,
        default_level=default_level,
        tools=tools_clean,
        allow=allow,
        deny=deny,
        ask=ask,
    )


# 模块级单例(同 hooks._config,spec §2.5)
_config: PermissionsConfig | None = None


def _reset_config() -> None:
    global _config
    _config = None


def get_config() -> PermissionsConfig:
    """惰性加载 + 返回当前配置。无文件 → empty()(D20)。"""
    global _config
    if _config is None:
        try:
            _config = load()
        except PermissionsConfigError as e:
            _log.warning("permissions: 加载失败,使用 empty():%s", e)
            _config = PermissionsConfig.empty()
    return _config


def reload_config(path: Path | None = None) -> PermissionsConfig:
    """重读 permissions.json。坏配置 → 保旧 + 抛 PermissionsConfigError。"""
    global _config
    try:
        new_cfg = load(path)
    except PermissionsConfigError:
        if _config is None:
            _config = PermissionsConfig.empty()
        raise
    _config = new_cfg
    return _config
