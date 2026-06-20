"""Routing 配置(契约 §11;spec §6,§14)。

从 ~/.argos/config.json 的 routing 段读/写。tier 名 fail-closed:拼写错 / 不在
config.models 里 → ConfigError 拒绝(spec D17 防假绿)。

任务:routing 模式跟 lsp/hooks/permissions 不同(无单例缓存 + 无 empty + set_category 后
重读),不强行套单例助手;仅抽 JSON 读取样板(走 config_base.read_json_file,失败返 None
让 caller 决定"routing 段缺则 safe default")。
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from argos import config_base
from argos.config import ConfigError
from argos.routing.categorizer import TaskCategory


@dataclass(frozen=True, slots=True)
class RoutingConfig:
    """路由配置(spec §4.4):default + by_category + by_tool + tier_force_confirm。"""
    default: str = "default"
    by_category: dict[str, str] = field(default_factory=dict)
    by_tool: dict[str, str] = field(default_factory=dict)
    tier_force_confirm: list[str] = field(default_factory=list)

    def is_force_confirm(self, tier: str) -> bool:
        return tier in self.tier_force_confirm

    def is_active(self) -> bool:
        """是否配置了任何实际路由行为。否则 router 纯 no-op(每步 categorize+select 都解析到
        default tier、无 force-confirm),不必构造 —— loop 走原路径,省掉每步路由开销(Phase 4.4)。"""
        return bool(self.by_category or self.by_tool or self.tier_force_confirm
                    or self.default != "default")


def load_routing(config_dir: Path) -> RoutingConfig:
    """从 config_dir/config.json 读 routing 段;缺则 safe default(零破坏 spec D17)。"""
    config_dir = Path(config_dir).expanduser()
    cfile = config_dir / "config.json"
    # 任务:JSON 读取走 config_base.read_json_file(OSError 走 silent —— routing 段
    # 不存在就 safe default,与原行为一致)。抛 ConfigError 时带原 "config.json 解析失败"
    # 前缀(历史消息格式,测试断言 match="config.json 解析失败" 不破)。
    try:
        raw = config_base.read_json_file(cfile, ErrorCls=ConfigError, on_os_error="silent")
    except ConfigError as e:
        # 重抛带原消息前缀(测试/用户文案不变)
        if "不是合法 JSON" in str(e):
            raise ConfigError(f"config.json 解析失败:{str(e).split(':', 1)[-1].strip()}") from None
        raise
    if raw is None:
        return RoutingConfig()
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
    config_dir = Path(config_dir).expanduser()
    cfile = config_dir / "config.json"
    try:
        raw = config_base.read_json_file(cfile, ErrorCls=ConfigError, on_os_error="silent")
    except ConfigError as e:
        if "不是合法 JSON" in str(e):
            raise ConfigError(f"config.json 解析失败:{str(e).split(':', 1)[-1].strip()}") from None
        raise
    if raw is None:
        return
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
    # set_category 必须读到完整 raw(要保留其他段),不走 read_json_file 助手(助手只返顶层 dict,
    # set_category 需要 raw 全段保留 + 原子写),但 parse error 处理复用助手模式。
    try:
        raw = json.loads(cfile.read_text())
    except json.JSONDecodeError as e:
        raise ConfigError(f"config.json 解析失败:{e}") from e
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
