"""Routing 配置(契约 §11;spec §6,§14)。

从 ~/.argos/config.json 的 routing 段读/写。tier 名 fail-closed:拼写错 / 不在
config.models 里 → ConfigError 拒绝(spec D17 防假绿)。
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from argos_agent.config import ConfigError
from argos_agent.routing.categorizer import TaskCategory


@dataclass(frozen=True, slots=True)
class RoutingConfig:
    """路由配置(spec §4.4):default + by_category + by_tool + tier_force_confirm。"""
    default: str = "default"
    by_category: dict[str, str] = field(default_factory=dict)
    by_tool: dict[str, str] = field(default_factory=dict)
    tier_force_confirm: list[str] = field(default_factory=list)

    def is_force_confirm(self, tier: str) -> bool:
        return tier in self.tier_force_confirm


def load_routing(config_dir: Path) -> RoutingConfig:
    """从 config_dir/config.json 读 routing 段;缺则 safe default(零破坏 spec D17)。"""
    config_dir = Path(config_dir).expanduser()
    cfile = config_dir / "config.json"
    if not cfile.exists():
        return RoutingConfig()
    try:
        raw = json.loads(cfile.read_text())
    except json.JSONDecodeError as e:
        raise ConfigError(f"config.json 解析失败:{e}") from e
    routing = raw.get("routing")
    if not isinstance(routing, dict):
        return RoutingConfig()
    default = routing.get("default") or "default"
    by_category = dict(routing.get("by_category") or {})
    by_tool = dict(routing.get("by_tool") or {})
    tier_force_confirm = list(routing.get("tier_force_confirm") or [])
    for k, v in {**by_category, **by_tool}.items():
        if not isinstance(v, str):
            raise ConfigError(
                f"routing.{k} 的 tier 值必须是 str,得 {type(v).__name__}")
    for v in tier_force_confirm:
        if not isinstance(v, str):
            raise ConfigError("routing.tier_force_confirm 项必须是 str")
    # 校验 category 键必须在 8 枚举内(spec D11 严格 schema)
    valid_cats = {c.value for c in TaskCategory}
    for k in by_category:
        if k not in valid_cats:
            raise ConfigError(
                f"routing.by_category 的键 {k!r} 不在合法类别 {sorted(valid_cats)} 内")
    return RoutingConfig(
        default=default, by_category=by_category, by_tool=by_tool,
        tier_force_confirm=tier_force_confirm,
    )


def _validate_tier(tier: str, config_dir: Path) -> None:
    """tier 名必须在 config.models 里(fail-closed spec D17 防拼写退化)。"""
    cfile = config_dir / "config.json"
    if not cfile.exists():
        return
    try:
        raw = json.loads(cfile.read_text())
    except json.JSONDecodeError as e:
        raise ConfigError(f"config.json 解析失败:{e}") from e
    models = raw.get("models") or {}
    if tier not in models:
        raise ConfigError(
            f"routing tier '{tier}' 不在 config.models {list(models)} 内(防拼写退化)")


def set_category(config_dir: Path, category: TaskCategory, tier: str) -> RoutingConfig:
    """原子改写 config.json 的 routing.by_category[category] = tier;返回新 config。"""
    _validate_tier(tier, config_dir)
    config_dir = Path(config_dir).expanduser()
    cfile = config_dir / "config.json"
    if not cfile.exists():
        raise ConfigError(f"无 {cfile},无法 set_category")
    raw = json.loads(cfile.read_text())
    routing = dict(raw.get("routing") or {})
    by_category = dict(routing.get("by_category") or {})
    by_category[category.value] = tier
    routing["by_category"] = by_category
    raw["routing"] = routing
    # 原子写:.tmp + os.replace(spec D12)
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
