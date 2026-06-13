"""Tier 解析(契约 §11;spec §6):by_tool > by_category > default;命中层标 source。

RouteDecision 不可变记录,供 ModelRouter.history() 与 /routing 视图读。
"""
from __future__ import annotations

from dataclasses import dataclass

from argos.routing.categorizer import TaskCategory
from argos.routing.config import RoutingConfig


@dataclass(frozen=True, slots=True)
class RouteDecision:
    """单次路由决策(契约 §11;spec §4.2)。"""
    category: TaskCategory
    tool: str | None
    tier: str
    source: str  # "by_tool" | "by_category" | "default"
    step: int = 0


def resolve(config: RoutingConfig, *, category: TaskCategory,
            tool: str | None) -> RouteDecision:
    """3 层优先级(spec D2):by_tool > by_category > default。"""
    if tool is not None and tool in config.by_tool:
        return RouteDecision(category, tool, config.by_tool[tool], "by_tool")
    if category.value in config.by_category:
        return RouteDecision(
            category, tool, config.by_category[category.value], "by_category",
        )
    return RouteDecision(category, tool, config.default, "default")
