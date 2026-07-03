from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, Mapping, Sequence

from argos import config
from argos import config_base
from argos.i18n import t
from argos.permissions.schema import VALID_LEVELS

_log = logging.getLogger("argos.permissions")

CONFIG_PATH: Path | None = None


def _config_path(path: Path | None = None) -> Path:
    return Path(
        path or CONFIG_PATH or (
            Path(config.get("ARGOS_CONFIG_DIR") or (Path.home() / ".argos")).expanduser()
            / "permissions.json"
        )
    )


_REDOS_PATTERNS: Final[tuple[str, ...]] = (
    r"\(\.\*\)\*",  # (.*)*
    r"\(\.\+\)\+",  # (.+)+
    r"\(\.\*\)\+",  # (.*)+
    r"\(\.\+\)\*",  # (.+)*
)


class PermissionsConfigError(Exception):
    pass


def _is_safe_regex(matcher: str) -> bool:
    if not isinstance(matcher, str):
        return False
    if matcher in ("", "*"):
        return True
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
    tool: str
    matcher: str


@dataclass(frozen=True, slots=True)
class ToolLevelOverride:
    tool: str
    level: str  # observe / propose / confirm / auto / accept_edits


@dataclass(frozen=True, slots=True)
class PermissionsConfig:
    version: int = 1
    default_level: str | None = None
    tools: Mapping[str, str] = field(default_factory=dict)
    allow: tuple[RuleEntry, ...] = ()
    deny: tuple[RuleEntry, ...] = ()
    ask: tuple[RuleEntry, ...] = ()
    preauth: Mapping[str, bool] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.default_level is not None and self.default_level not in VALID_LEVELS:
            raise ValueError(
                t("perm2.config.invalid_default_level", level=self.default_level, valid=sorted(VALID_LEVELS))
            )
        for tool, level in self.tools.items():
            if level not in VALID_LEVELS:
                raise ValueError(
                    t("perm2.config.invalid_tool_level", level=level, tool=tool, valid=sorted(VALID_LEVELS))
                )

    @staticmethod
    def empty() -> "PermissionsConfig":
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
    if not matcher or matcher == "*":
        return True
    try:
        return bool(re.search(matcher, arg_str))
    except re.error:
        return False


def _safe_rule_entries(arr: Sequence[dict]) -> tuple[RuleEntry, ...]:
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
    p = _config_path(path)
    data = config_base.read_json_file(p, ErrorCls=PermissionsConfigError)
    if data is None:
        return PermissionsConfig.empty()
    raw = data
    version = raw.get("version")
    if version != 1:
        raise PermissionsConfigError(
            t("perm2.config.bad_version", version=version)
        )
    default_level = raw.get("default_level")
    if default_level is not None and default_level not in VALID_LEVELS:
        raise PermissionsConfigError(
            t("perm2.config.invalid_default_level_load", level=default_level, valid=sorted(VALID_LEVELS))
        )
    tools = raw.get("tools") or {}
    if not isinstance(tools, dict):
        raise PermissionsConfigError(t("perm2.config.tools_not_object"))
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
    preauth_raw = raw.get("preauth") or {}
    preauth_clean: dict[str, bool] = {}
    if isinstance(preauth_raw, dict):
        for k, v in preauth_raw.items():
            if isinstance(k, str) and isinstance(v, bool):
                preauth_clean[k] = v
            else:
                _log.warning(
                    "permissions: skip preauth entry (invalid) key=%r value=%r", k, v,
                )
    return PermissionsConfig(
        version=1,
        default_level=default_level,
        tools=tools_clean,
        allow=allow,
        deny=deny,
        ask=ask,
        preauth=preauth_clean,
    )


_config: PermissionsConfig | None = None


def _reset_config() -> None:
    global _config
    _config = None


def get_config() -> PermissionsConfig:
    global _config
    if _config is None:
        try:
            _config = load()
        except PermissionsConfigError as e:
            _log.warning("permissions: 加载失败,使用 observe fail-closed:%s", e)
            _config = PermissionsConfig(version=1, default_level="observe")
    return _config


def reload_config(path: Path | None = None) -> PermissionsConfig:
    global _config
    try:
        new_cfg = load(path)
    except PermissionsConfigError:
        if _config is None:
            _config = PermissionsConfig(version=1, default_level="observe")
        raise
    _config = new_cfg
    return _config


def save_allow_rule(tool: str, matcher: str, path: Path | None = None) -> bool:
    p = _config_path(path)
    raw: dict = {}
    if p.exists():
        try:
            loaded = json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return False
        if not isinstance(loaded, dict):
            return False
        raw = loaded
    raw.setdefault("version", 1)
    allow_list = raw.get("allow")
    if not isinstance(allow_list, list):
        allow_list = []
    exists = any(isinstance(e, dict) and e.get("tool") == tool and e.get("matcher") == matcher
                 for e in allow_list)
    if not exists:
        allow_list.append({"tool": tool, "matcher": matcher})
        raw["allow"] = allow_list
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_name(p.name + ".tmp")
            tmp.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(p)
        except OSError:
            return False
    try:
        reload_config(p)
    except PermissionsConfigError:
        pass
    return True
