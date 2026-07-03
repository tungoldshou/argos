"""Internal documentation."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

from argos import config
from argos import config_base
from argos.hooks.schema import KNOWN_EVENTS, VALID_HANDLER_TYPES
from argos.i18n import t


class HooksConfigError(Exception):
    """Internal documentation."""


@dataclass(frozen=True, slots=True)
class HookHandler:
    """Internal documentation."""
    type: str
    command: str
    timeout: int = 60000

    def __post_init__(self) -> None:
        if self.type not in VALID_HANDLER_TYPES:
            raise ValueError(
                t("hooks.config.handler_type_invalid", valid=sorted(VALID_HANDLER_TYPES), type_val=self.type)
            )
        if not self.command or not self.command.strip():
            raise ValueError(t("hooks.config.handler_command_empty"))
        if self.timeout <= 0:
            raise ValueError(t("hooks.config.handler_timeout_nonpositive", timeout=self.timeout))


@dataclass(frozen=True, slots=True)
class HookMatcherEntry:
    """Internal documentation."""
    matcher: str | None
    hooks: tuple[HookHandler, ...]


@dataclass(frozen=True, slots=True)
class HooksConfig:
    """Internal documentation."""
    version: int = 1
    entries: Mapping[str, tuple[HookMatcherEntry, ...]] = field(default_factory=dict)

    @staticmethod
    def empty() -> "HooksConfig":
        """Internal documentation."""
        return HooksConfig(version=1, entries={})



HOOKS_CONFIG_PATH: Path | None = None


def _default_config_path() -> Path:
    return Path(config.get("ARGOS_CONFIG_DIR") or (Path.home() / ".argos")).expanduser() / "hooks.json"


def _validate_event_name(event_name: str) -> None:
    if event_name not in KNOWN_EVENTS:
        raise HooksConfigError(
            t("hooks.config.unknown_event", event_name=event_name, allowed=sorted(KNOWN_EVENTS))
        )


def _parse_handler(raw: dict) -> HookHandler:
    if not isinstance(raw, dict):
        raise HooksConfigError(t("hooks.config.handler_not_dict", type_name=type(raw).__name__))
    if "type" not in raw:
        raise HooksConfigError(t("hooks.config.handler_missing_type"))
    if "command" not in raw:
        raise HooksConfigError(t("hooks.config.handler_missing_command"))
    timeout = raw.get("timeout", 60000)
    try:
        return HookHandler(type=raw["type"], command=raw["command"], timeout=timeout)
    except ValueError as e:
        raise HooksConfigError(t("hooks.config.handler_invalid", exc=e)) from e


def _parse_entry(raw: dict) -> HookMatcherEntry:
    if not isinstance(raw, dict):
        raise HooksConfigError(t("hooks.config.entry_not_dict", type_name=type(raw).__name__))
    if "hooks" not in raw:
        raise HooksConfigError(t("hooks.config.entry_missing_hooks"))
    raw_hooks = raw["hooks"]
    if not isinstance(raw_hooks, list) or not raw_hooks:
        raise HooksConfigError(t("hooks.config.entry_hooks_not_array"))
    matcher = raw.get("matcher")
    if matcher is not None and not isinstance(matcher, str):
        raise HooksConfigError(t("hooks.config.entry_matcher_not_string", type_name=type(matcher).__name__))
    if matcher is not None and matcher != "" and matcher != "*":
        from argos.hooks.matcher import validate_matcher
        validate_matcher(matcher)
    handlers = tuple(_parse_handler(h) for h in raw_hooks)
    return HookMatcherEntry(matcher=matcher, hooks=handlers)


def load(path: Path | None = None) -> HooksConfig:
    """Internal documentation."""
    p = path or HOOKS_CONFIG_PATH or _default_config_path()
    data = config_base.read_json_file(p, ErrorCls=HooksConfigError)
    if data is None:
        return HooksConfig.empty()
    if "version" not in data:
        raise HooksConfigError(t("hooks.config.missing_version"))
    if data["version"] != 1:
        raise HooksConfigError(
            t("hooks.config.version_mismatch", version=data["version"])
        )
    raw_hooks = data.get("hooks", {})
    if not isinstance(raw_hooks, dict):
        raise HooksConfigError(t("hooks.config.hooks_not_object"))
    entries: dict[str, tuple[HookMatcherEntry, ...]] = {}
    for event_name, raw_entries in raw_hooks.items():
        _validate_event_name(event_name)
        if not isinstance(raw_entries, list):
            raise HooksConfigError(t("hooks.config.event_entries_not_array", event_name=event_name))
        entries[event_name] = tuple(_parse_entry(e) for e in raw_entries)
    return HooksConfig(version=1, entries=entries)
