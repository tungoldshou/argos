# argos/tui/widgets/orders_panel.py
"""Internal documentation."""
from __future__ import annotations

from collections.abc import Callable

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Static

from argos.conductor.orders import StandingOrder
from argos.i18n import t
from argos.protocol.events import ProactiveSuggestionEvent
from argos.tui.widgets.inline_choice import InlineChoice

# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
_COL_EYE_SOFT   = "#A8854A"
_COL_EYE        = "#D9A85C"
_COL_INK        = "#C8CCDA"
_COL_INK_DIM    = "#7E869C"
_COL_INK_FAINT  = "#6B7494"
_COL_INK_GHOST  = "#3A4055"
_COL_PLAN       = "#7AA2F7"
_COL_PASS       = "#9ECE6A"
_COL_FAIL       = "#F7768E"


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------

def _normalize_order(obj: StandingOrder | dict) -> StandingOrder:
    """Internal documentation."""
    if isinstance(obj, StandingOrder):
        return obj
    return StandingOrder.from_dict(obj)


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------

class OrdersPanel(Vertical):
    """Internal documentation."""

    DEFAULT_CSS = """
    OrdersPanel {
        height: auto;
        margin: 0 0 1 0;
        padding: 1 2;
        background: $abyss;
        border: round $hairline-lit;
    }
    OrdersPanel .op-count   { color: $ink; }
    OrdersPanel .op-empty   { color: $ink-faint; }
    OrdersPanel .op-footer  { color: $ink-faint; }
    OrdersPanel .op-echo    { color: $ink-dim; }
    """

    def __init__(
        self,
        *,
        orders: list[StandingOrder | dict],
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._orders: list[StandingOrder] = [_normalize_order(o) for o in orders]


    def _count_line(self) -> str:
        """Internal documentation."""
        return f"standing orders ({len(self._orders)})"

    def _empty_state_text(self) -> str:
        """Internal documentation."""
        return t("widget.orders_empty")

    def _footer_left(self) -> str:
        """Internal documentation."""
        return t("widget.orders_footer_left")

    def _footer_right(self) -> str:
        """Internal documentation."""
        return "argos/conductor"

    def _order_row_text(self, order: StandingOrder) -> Text:
        """Internal documentation."""
        t = Text()

        if order.enabled:
            glyph_color = _COL_EYE_SOFT
            trigger_color = _COL_INK
            utterance_color = _COL_INK_DIM
            action_color = _COL_INK_FAINT
        else:
            glyph_color = _COL_INK_GHOST
            trigger_color = _COL_INK_GHOST
            utterance_color = _COL_INK_GHOST
            action_color = _COL_INK_GHOST

        if order.kind == "schedule":
            t.append("⏱ ", style=glyph_color)
        else:
            t.append("⊙ ", style=glyph_color)

        if order.kind == "schedule":
            trigger_label = order.schedule or ""
        else:
            trigger_label = order.trigger_glob or ""

        t.append(f"{trigger_label:<20}", style=trigger_color)

        # col2: utterance（flex 1fr）
        t.append(f"  {order.utterance}", style=utterance_color)

        # col3: action（→ run / → dream）
        t.append(f"  → {order.action}", style=action_color)

        return t


    def compose(self) -> ComposeResult:
        """Internal documentation."""
        # count line
        yield Static(self._count_line(), markup=False, classes="op-count")

        if not self._orders:
            yield Static(self._empty_state_text(), markup=False, classes="op-empty")
        else:
            for order in self._orders:
                row = self._order_row_text(order)
                yield Static(row, markup=False)

        footer_text = Text()
        footer_text.append(self._footer_left(), style=_COL_INK_FAINT)
        footer_text.append("  ", style=_COL_INK_FAINT)
        footer_text.append(self._footer_right(), style=_COL_INK_FAINT)
        yield Static(footer_text, markup=False, classes="op-footer")


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------

class ConductorSuggestionChoice(InlineChoice):
    """Internal documentation."""

    DEFAULT_CSS = """
    ConductorSuggestionChoice {
        height: auto;
        margin: 0 0 1 0;
        padding: 1 2;
        background: $raise;
        border-left: thick $plan;
    }
    ConductorSuggestionChoice #ic-title {
        text-style: bold;
        color: $plan;
    }
    ConductorSuggestionChoice #ic-body  { color: $ink; }
    ConductorSuggestionChoice #ic-hint  { color: $ink-faint; }
    ConductorSuggestionChoice #ic-input { display: none; }
    ConductorSuggestionChoice.-input-mode #ic-input { display: block; }
    """

    # Title is resolved at __init__ time via t() to respect ARGOS_LANG.
    _TITLE_KEY = "widget.conductor_title"

    def __init__(
        self,
        *,
        ev: ProactiveSuggestionEvent,
        on_decide: Callable[[str, str], None],
        **kwargs,
    ) -> None:
        sid8 = ev.suggestion_id[:8]

        #   Line 1: reason_human
        body = (
            f"{ev.reason_human}\n"
            f"{t('widget.conductor_body_suggest', goal=ev.goal)}\n"
            f"{t('widget.conductor_body_confirm_invariant')}"
        )

        options: list[tuple[str, str]] = [
            ("confirm", t("widget.conductor_option_confirm", sid8=sid8)),
            ("dismiss", t("widget.conductor_option_dismiss", sid8=sid8)),
        ]

        super().__init__(
            title=t(self._TITLE_KEY),
            body=body,
            options=options,
            on_decide=on_decide,
            escape_value="dismiss",
            risk="medium",
            action_label=t("widget.conductor_action_label"),
            **kwargs,
        )

        self.add_class("conductor")

    def _hint_text(self) -> str:
        """Internal documentation."""
        return t("widget.conductor_hint")
