# argos/tui/widgets/trust_dial.py
"""Internal documentation."""
from __future__ import annotations

from rich.text import Text
from textual.widgets import Static

from argos.i18n import t as t_
from argos.permissions.trust_dial import TrustLevel

# ─────────────────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

_COL_EYE        = "#D9A85C"
_COL_INK_BRIGHT = "#ECEEF5"
_COL_INK        = "#C8CCDA"
_COL_INK_DIM    = "#7E869C"
_COL_INK_FAINT  = "#6B7494"
_COL_FAIL       = "#F7768E"
_COL_UNVERIF    = "#FF9E64"

# ─────────────────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

_DIAL_ROWS: list[tuple[TrustLevel, str, str]] = [
    (TrustLevel.L0_EVERY_STEP,        "trust.l0_label", "trust.l0_hint"),
    (TrustLevel.L1_DANGEROUS_ONLY,    "trust.l1_label", "trust.l1_hint"),
    (TrustLevel.L2_IRREVERSIBLE_ONLY, "trust.l2_label", "trust.l2_hint"),
    (TrustLevel.L3_SESSION_TRUSTED,   "trust.l3_label", "trust.l3_hint"),
    (TrustLevel.L4_AUTONOMOUS,        "trust.l4_label", "trust.l4_hint_red"),
]

_L4_HINT_RED_KEY  = "trust.l4_hint_red"
_L4_HINT_REST_KEY = "trust.l4_hint_rest"


class TrustDial(Static):
    """Internal documentation."""

    DEFAULT_CSS = """
    TrustDial {
        height: auto;
        margin: 0 0 1 0;
        padding: 0 2;
        background: $stream;
    }
    """

    can_focus = False

    def __init__(self, *, current: TrustLevel, **kwargs) -> None:
        super().__init__("", markup=False, **kwargs)
        self._current = current

    # ─────────────────────────────────────────────────────────────────────────
    # ─────────────────────────────────────────────────────────────────────────

    def _compose_text(self) -> Text:
        """Internal documentation."""
        t = Text()

        short = self._current.name.split("_")[0]  # "L0" / "L1" / ...
        t.append(t_("trust.title_prefix"), style=_COL_INK)
        t.append(self._current.mode_name, style=f"bold {_COL_INK_BRIGHT}")
        t.append(t_("trust.title_level_suffix", short=short), style=_COL_INK)
        t.append("\n")

        for lvl, label_key, hint_key in _DIAL_ROWS:
            is_current = (lvl == self._current)
            label = t_(label_key)

            if is_current:
                t.append("▸ ", style=f"bold {_COL_EYE}")
                level_short = lvl.name.split("_")[0]
                t.append(level_short + " ", style=f"bold {_COL_INK_BRIGHT}")
                t.append(label, style=f"bold {_COL_INK_BRIGHT}")
                t.append("  ")
                if lvl is TrustLevel.L4_AUTONOMOUS:
                    t.append(t_(_L4_HINT_RED_KEY), style=_COL_FAIL)
                    t.append(t_(_L4_HINT_REST_KEY), style=_COL_INK)
                else:
                    t.append(t_(hint_key), style=_COL_INK)
            else:
                t.append("  ", style=_COL_INK_FAINT)
                level_short = lvl.name.split("_")[0]
                t.append(level_short + " ", style=_COL_INK_FAINT)
                t.append(label, style=_COL_INK_FAINT)
                t.append("  ", style=_COL_INK_FAINT)
                if lvl is TrustLevel.L4_AUTONOMOUS:
                    t.append(t_(_L4_HINT_RED_KEY), style=_COL_FAIL)
                    t.append(t_(_L4_HINT_REST_KEY), style=_COL_INK_FAINT)
                else:
                    t.append(t_(hint_key), style=_COL_INK_FAINT)

            t.append("\n")

        t.append(t_("trust.hard_rules_prefix"), style=_COL_INK_DIM)
        t.append(t_("trust.hard_rules_shell"), style=_COL_FAIL)
        t.append(t_("trust.hard_rules_sep"), style=_COL_INK_DIM)
        t.append(t_("trust.hard_rules_path"), style=_COL_FAIL)
        t.append(t_("trust.hard_rules_sep"), style=_COL_INK_DIM)
        t.append(t_("trust.hard_rules_secret"), style=_COL_FAIL)
        t.append("\n")

        t.append(t_("trust.footer_provenance"), style=_COL_INK_FAINT)
        t.append("  ", style=_COL_INK_FAINT)
        t.append(t_("trust.footer_module"), style=_COL_INK_FAINT)

        return t

    def render(self) -> Text:  # type: ignore[override]
        """Internal documentation."""
        return self._compose_text()
