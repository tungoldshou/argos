"""Internal documentation."""
from __future__ import annotations

from dataclasses import dataclass

from argos.routing.categorizer import TaskCategory
from argos.routing.config import RoutingConfig


@dataclass(frozen=True, slots=True)
class RouteDecision:
    """Internal documentation."""
    category: TaskCategory
    tool: str | None
    tier: str
    source: str  # "by_tool" | "by_category" | "default"
    step: int = 0


def resolve(config: RoutingConfig, *, category: TaskCategory,
            tool: str | None) -> RouteDecision:
    """Internal documentation."""
    if tool is not None and tool in config.by_tool:
        return RouteDecision(category, tool, config.by_tool[tool], "by_tool")
    if category.value in config.by_category:
        return RouteDecision(
            category, tool, config.by_category[category.value], "by_category",
        )
    return RouteDecision(category, tool, config.default, "default")
