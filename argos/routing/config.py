from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from argos import config_base
from argos.config import ConfigError
from argos.i18n import t
from argos.routing.categorizer import TaskCategory


@dataclass(frozen=True, slots=True)
class RoutingConfig:
    default: str = "default"
    by_category: dict[str, str] = field(default_factory=dict)
    by_tool: dict[str, str] = field(default_factory=dict)
    tier_force_confirm: list[str] = field(default_factory=list)

    def is_force_confirm(self, tier: str) -> bool:
        return tier in self.tier_force_confirm

    def is_active(self) -> bool:
        return bool(self.by_category or self.by_tool or self.tier_force_confirm
                    or self.default != "default")


_DEFAULT_BY_CATEGORY: dict[str, str] = {
    "simple_read":   "cheap",
    "plan":          "cheap",
    "verify":        "cheap",
    "auto_capture":  "cheap",
    "file_edit":     "strong",
    "refactor":      "strong",
    "test_write":    "strong",
    "long_run":      "strong",
}

_BUILTIN_DEFAULT = RoutingConfig(by_category=_DEFAULT_BY_CATEGORY)


def _validate_routing_tiers(tiers: list[str], models: dict) -> None:
    for tier in tiers:
        if tier not in models:
            raise ConfigError(t("route.tier_not_in_models", tier=tier, models=list(models)))


def _validate_category_keys(by_category: dict[str, str]) -> None:
    valid_cats = {c.value for c in TaskCategory}
    for k in by_category:
        if k not in valid_cats:
            raise ConfigError(t("route.category_key_invalid", key=k, valid=sorted(valid_cats)))


def load_routing(config_dir: Path) -> RoutingConfig:
    config_dir = Path(config_dir).expanduser()
    cfile = config_dir / "config.json"
    try:
        raw = config_base.read_json_file(cfile, ErrorCls=ConfigError, on_os_error="silent")
    except ConfigError as e:
        if isinstance(e.__cause__, json.JSONDecodeError):
            raise ConfigError(t("route.config_parse_fail", detail=str(e).split(':', 1)[-1].strip())) from None
        raise
    if raw is None:
        return _BUILTIN_DEFAULT
    routing = raw.get("routing")
    if routing is None:
        return _BUILTIN_DEFAULT
    if not isinstance(routing, dict):
        raise ConfigError(t("route.routing_must_be_object", type_name=type(routing).__name__))
    raw_default = routing.get("default")
    if raw_default is not None and not isinstance(raw_default, str):
        raise ConfigError(t("route.field_must_be_str", field="default", type_name=type(raw_default).__name__))
    default = raw_default or raw.get("active") or "default"
    raw_by_category = routing.get("by_category") or {}
    raw_by_tool = routing.get("by_tool") or {}
    raw_tier_force_confirm = routing.get("tier_force_confirm") or []
    if not isinstance(raw_by_category, dict):
        raise ConfigError(t("route.field_must_be_object", field="by_category", type_name=type(raw_by_category).__name__))
    if not isinstance(raw_by_tool, dict):
        raise ConfigError(t("route.field_must_be_object", field="by_tool", type_name=type(raw_by_tool).__name__))
    if not isinstance(raw_tier_force_confirm, list):
        raise ConfigError(t("route.field_must_be_list", field="tier_force_confirm", type_name=type(raw_tier_force_confirm).__name__))
    by_category = dict(raw_by_category)
    by_tool = dict(raw_by_tool)
    tier_force_confirm = list(raw_tier_force_confirm)
    for k, v in {**by_category, **by_tool}.items():
        if not isinstance(v, str):
            raise ConfigError(t("route.tier_must_be_str", key=k, type_name=type(v).__name__))
    for v in tier_force_confirm:
        if not isinstance(v, str):
            raise ConfigError(t("route.tier_force_confirm_must_be_str"))
    _validate_category_keys(by_category)
    _validate_routing_tiers(
        [default, *by_category.values(), *by_tool.values(), *tier_force_confirm],
        raw.get("models") or {},
    )
    return RoutingConfig(
        default=default, by_category=by_category, by_tool=by_tool,
        tier_force_confirm=tier_force_confirm,
    )


def _validate_tier(tier: str, config_dir: Path) -> None:
    config_dir = Path(config_dir).expanduser()
    cfile = config_dir / "config.json"
    try:
        raw = config_base.read_json_file(cfile, ErrorCls=ConfigError, on_os_error="silent")
    except ConfigError as e:
        if isinstance(e.__cause__, json.JSONDecodeError):
            raise ConfigError(t("route.config_parse_fail", detail=str(e).split(':', 1)[-1].strip())) from None
        raise
    if raw is None:
        return
    _validate_routing_tiers([tier], raw.get("models") or {})


def set_category(config_dir: Path, category: TaskCategory, tier: str) -> RoutingConfig:
    _validate_tier(tier, config_dir)
    config_dir = Path(config_dir).expanduser()
    cfile = config_dir / "config.json"
    if not cfile.exists():
        raise ConfigError(t("route.no_config_set_category", path=cfile))
    try:
        raw = json.loads(cfile.read_text())
    except json.JSONDecodeError as e:
        raise ConfigError(t("route.config_parse_fail", detail=str(e))) from e
    raw_routing = raw.get("routing")
    if raw_routing is not None and not isinstance(raw_routing, dict):
        raise ConfigError(t("route.routing_must_be_object", type_name=type(raw_routing).__name__))
    routing = dict(raw_routing or {})
    raw_default = routing.get("default")
    if raw_default is not None and not isinstance(raw_default, str):
        raise ConfigError(t("route.field_must_be_str", field="default", type_name=type(raw_default).__name__))
    raw_by_category = routing.get("by_category") or {}
    raw_by_tool = routing.get("by_tool") or {}
    raw_tier_force_confirm = routing.get("tier_force_confirm") or []
    if not isinstance(raw_by_category, dict):
        raise ConfigError(t("route.field_must_be_object", field="by_category", type_name=type(raw_by_category).__name__))
    if not isinstance(raw_by_tool, dict):
        raise ConfigError(t("route.field_must_be_object", field="by_tool", type_name=type(raw_by_tool).__name__))
    if not isinstance(raw_tier_force_confirm, list):
        raise ConfigError(t("route.field_must_be_list", field="tier_force_confirm", type_name=type(raw_tier_force_confirm).__name__))
    by_category = dict(raw_by_category)
    by_category[category.value] = tier
    routing["by_category"] = by_category
    _validate_category_keys(by_category)
    _validate_routing_tiers(
        [
            routing.get("default") or raw.get("active") or "default",
            *by_category.values(),
            *raw_by_tool.values(),
            *raw_tier_force_confirm,
        ],
        raw.get("models") or {},
    )
    raw["routing"] = routing
    tmp_fd, tmp_path = tempfile.mkstemp(dir=str(config_dir), suffix=".tmp")
    try:
        with os.fdopen(tmp_fd, "w") as f:
            json.dump(raw, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, cfile)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
    return load_routing(config_dir)
