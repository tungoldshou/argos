# argos/tui/widgets/routing_table.py
from __future__ import annotations

from typing import Sequence

from rich.text import Text
from textual.widgets import Static

from argos.i18n import t as _t
from argos.routing.categorizer import TaskCategory
from argos.routing.config import RoutingConfig
from argos.routing.resolver import RouteDecision

_COL_CYAN        = "#7DCFFF"   # $cyan       — cheap tier
_COL_INK         = "#C8CCDA"
_COL_INK_BRIGHT  = "#ECEEF5"   # $ink-bright — strong tier
_COL_INK_DIM     = "#7E869C"
_COL_INK_FAINT   = "#6B7494"   # $ink-faint  — hint / footer
_COL_UNVERIF     = "#FF9E64"

_CATEGORIES: tuple[TaskCategory, ...] = (
    TaskCategory.PLAN,
    TaskCategory.FILE_EDIT,
    TaskCategory.REFACTOR,
    TaskCategory.TEST_WRITE,
    TaskCategory.VERIFY,
    TaskCategory.LONG_RUN,
    TaskCategory.AUTO_CAPTURE,
    TaskCategory.SIMPLE_READ,
)

_TIER_COLOR: dict[str, str] = {
    "cheap":   _COL_CYAN,
    "default": _COL_INK,
    "strong":  _COL_INK_BRIGHT,
}

_CAT_COL_WIDTH = 13


def _tier_color(tier: str) -> str:
    return _TIER_COLOR.get(tier, _COL_INK)


class RoutingTable(Static):

    DEFAULT_CSS = """
    RoutingTable {
        height: auto;
        margin: 0 0 1 0;
        padding: 1 2;
        background: $stream;
        border: round $border;
    }
    """

    can_focus = False

    def __init__(
        self,
        routing: RoutingConfig,
        history: Sequence[RouteDecision],
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._routing = routing
        self._history: list[RouteDecision] = list(history)

    @property
    def routing(self) -> RoutingConfig:
        return self._routing

    @property
    def history(self) -> list[RouteDecision]:
        return self._history

    def rendered_text(self) -> Text:
        t = Text()

        t.append("› /routing", style=_COL_INK_DIM)
        t.append("\n")

        # Row 2: caption
        t.append(_t("widget.routing_caption"), style=_COL_INK)
        t.append("\n")

        for cat in _CATEGORIES:
            self._append_category_row(t, cat)

        t.append(_t("widget.routing_set_hint"), style=_COL_INK_FAINT)
        t.append("\n")

        self._append_history_block(t)

        t.append(_t("widget.routing_footer_left"), style=_COL_INK_FAINT)
        t.append("  ", style=_COL_INK_FAINT)
        t.append(_t("widget.routing_footer_module"), style=_COL_INK_FAINT)

        return t

    def _append_category_row(self, t: Text, cat: TaskCategory) -> None:
        tier = self._routing.by_category.get(cat.value, self._routing.default)

        cat_label = f"  {cat.value:<{_CAT_COL_WIDTH}}"
        t.append(cat_label, style=_COL_INK_DIM)

        t.append("→ ", style=_COL_INK_DIM)
        t.append(tier, style=_tier_color(tier))

        if self._routing.is_force_confirm(tier):
            t.append(_t("widget.routing_force_confirm"), style=_COL_UNVERIF)

        t.append("\n")

    def _append_history_block(self, t: Text) -> None:
        if not self._history:
            t.append(_t("widget.routing_no_history"), style=_COL_INK_FAINT)
            t.append("\n")
            return

        t.append(_t("widget.routing_history_header"), style=_COL_INK_DIM)
        t.append("\n")

        # spec: f"  step {d.step:3}  cat={d.category.value:13} tool={d.tool or '-':14} → {d.tier:8} ({d.source})"
        for d in self._history[:10]:
            tool_str = d.tool or "-"
            line_cat = f"  step {d.step:3}  cat={d.category.value:<13} tool={tool_str:<14} → "
            t.append(line_cat, style=_COL_INK_DIM)
            t.append(f"{d.tier:<8}", style=_tier_color(d.tier))
            t.append(f" ({d.source})", style=_COL_INK_FAINT)
            t.append("\n")

    def render(self) -> Text:
        return self.rendered_text()
