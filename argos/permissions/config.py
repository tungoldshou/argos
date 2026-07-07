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
from argos.permissions.mode import PermissionMode, parse_permission_mode

_log = logging.getLogger("argos.permissions")

CONFIG_PATH: Path | None = None


def _config_path(path: Path | None = None) -> Path:
    return Path(path or CONFIG_PATH or (config.config_dir() / "permissions.json"))


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
class PermissionsConfig:
    version: int = 2
    mode: PermissionMode = PermissionMode.SMART_APPROVAL
    network: Mapping[str, object] = field(default_factory=dict)
    rules: Mapping[str, object] = field(default_factory=dict)
    reviewer: Mapping[str, object] = field(default_factory=dict)
    allow: tuple[RuleEntry, ...] = ()
    deny: tuple[RuleEntry, ...] = ()
    ask: tuple[RuleEntry, ...] = ()

    @staticmethod
    def empty() -> "PermissionsConfig":
        return PermissionsConfig(version=2)

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
    if version != 2:
        raise PermissionsConfigError(
            t("perm2.config.bad_version", version=version)
        )
    old_keys = {"default" + "_level", "tool" + "s", "pre" + "auth"} & set(raw)
    if old_keys:
        raise PermissionsConfigError(
            "permissions.json v2 only supports mode, network, rules, and reviewer; "
            f"remove old keys: {', '.join(sorted(old_keys))}"
        )
    mode = parse_permission_mode(raw.get("mode"))
    network = raw.get("network") or {}
    if not isinstance(network, dict):
        raise PermissionsConfigError("network must be an object")
    rules = raw.get("rules") or {}
    if not isinstance(rules, dict):
        raise PermissionsConfigError("rules must be an object")
    reviewer = raw.get("reviewer") or {}
    if not isinstance(reviewer, dict):
        raise PermissionsConfigError("reviewer must be an object")
    allow = _safe_rule_entries(rules.get("allow") or [])
    deny = _safe_rule_entries(rules.get("deny") or [])
    ask = _safe_rule_entries(rules.get("ask") or [])
    return PermissionsConfig(
        version=2,
        mode=mode,
        network=network,
        rules=rules,
        reviewer=reviewer,
        allow=allow,
        deny=deny,
        ask=ask,
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
            _log.debug("permissions: 加载失败,使用 smart fail-closed:%s", e)
            _config = PermissionsConfig(version=2, mode=PermissionMode.SMART_APPROVAL)
    return _config


def reload_config(path: Path | None = None) -> PermissionsConfig:
    global _config
    try:
        new_cfg = load(path)
    except PermissionsConfigError:
        if _config is None:
            _config = PermissionsConfig(version=2, mode=PermissionMode.SMART_APPROVAL)
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
    raw.setdefault("version", 2)
    raw.setdefault("mode", PermissionMode.SMART_APPROVAL.value)
    rules = raw.get("rules")
    if not isinstance(rules, dict):
        rules = {}
    allow_list = rules.get("allow")
    if not isinstance(allow_list, list):
        allow_list = []
    exists = any(isinstance(e, dict) and e.get("tool") == tool and e.get("matcher") == matcher
                 for e in allow_list)
    if not exists:
        allow_list.append({"tool": tool, "matcher": matcher})
        rules["allow"] = allow_list
        raw["rules"] = rules
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
