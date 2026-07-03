"""Internal documentation."""
from __future__ import annotations

from rich.text import Text
from textual.widgets import Static

from argos.i18n import t as t_
from argos.ledger.entry import LedgerEntry

_COL_EYE        = "#D9A85C"
_COL_INK_BRIGHT = "#ECEEF5"
_COL_INK        = "#C8CCDA"
_COL_INK_DIM    = "#7E869C"
_COL_INK_FAINT  = "#6B7494"
_COL_PASS       = "#9ECE6A"   # $pass:       verdict passed（undo_state=available）
_COL_PASS_WEAK  = "#73A857"
_COL_FAIL       = "#F7768E"   # $fail:       failed（risk=high / reversible=no）
_COL_UNVERIF    = "#FF9E64"
_COL_HAIRLINE   = "#23252E"

_SENTINEL_ACTION = "undo_done"

_W_SEQ   = 4
_W_RISK  = 7
_W_REV   = 8
_W_UNDO  = 11
_W_SIG   = 8
_COL_GAP = "  " # Internal note.

_SIG_DISPLAY_LEN = 8

_RISK_DISPLAY = {
    "low":    "low",
    "medium": "med",   # spec §14: backend stores 'medium', display shows 'med'
    "high":   "high",
}

# risk → (display_text, hex_color)
_RISK_COLOR = {
    "low":    (_RISK_DISPLAY["low"],    _COL_INK_DIM),
    "medium": (_RISK_DISPLAY["medium"], _COL_UNVERIF),
    "high":   (_RISK_DISPLAY["high"],   _COL_FAIL),
}

# reversible → (display_text, hex_color)
_REV_COLOR = {
    "yes":     ("yes",     _COL_PASS_WEAK),
    "no":      ("no",      _COL_FAIL),
    "unknown": ("unknown", _COL_UNVERIF),
}

# undo_state → (display_text, hex_color)
_UNDO_COLOR = {
    "available":  ("available",  _COL_PASS),
    "done":       ("done",       _COL_INK_DIM),
    "impossible": ("impossible", _COL_INK_FAINT),
}


class LedgerTable(Static):
    """Internal documentation."""

    DEFAULT_CSS = """
    LedgerTable {
        height: auto;
        margin: 0 0 1 0;
        padding: 0 2;
        background: $stream;
    }
    """

    can_focus = False

    def __init__(
        self,
        *,
        entries: list[LedgerEntry],
        run_id: str,
        **kwargs,
    ) -> None:
        self._entries: list[LedgerEntry] = [
            e for e in entries if e.action != _SENTINEL_ACTION
        ]
        self._run_id = run_id
        rich_content = self._build_rich_text()
        super().__init__(rich_content, markup=False, **kwargs)


    @property
    def rendered_text(self) -> str:
        """Internal documentation."""
        return self._build_rich_text().plain

    def _build_rich_text(self) -> Text:
        """Internal documentation."""
        t = Text(no_wrap=False)
        entries = self._entries
        n = len(entries)

        # ── 1. Header line ──────────────────────────────────────────────
        t.append(t_("ledger.header", run_id=self._run_id, n=n), style=_COL_INK)
        t.append("\n")

        # ── 2. Column header row in $ink-faint ─────────────────────────
        seq_h    = t_("ledger.col_seq")
        action_h = t_("ledger.col_action")
        risk_h   = t_("ledger.col_risk")
        rev_h    = t_("ledger.col_rev")
        undo_h   = t_("ledger.col_undo")
        sig_h    = t_("ledger.col_sig")
        t.append(seq_h, style=_COL_INK_FAINT)
        t.append(action_h, style=_COL_INK_FAINT)
        t.append(risk_h, style=_COL_INK_FAINT)
        t.append(rev_h, style=_COL_INK_FAINT)
        t.append(undo_h, style=_COL_INK_FAINT)
        t.append(sig_h, style=_COL_INK_FAINT)
        t.append("\n")

        # ── 3. Hairline separator ───────────────────────────────────────
        t.append("─" * 60, style=_COL_HAIRLINE)
        t.append("\n")

        # ── 4. Data rows ────────────────────────────────────────────────
        for entry in entries:
            self._append_data_row(t, entry)

        return t

    def _append_data_row(self, t: Text, entry: LedgerEntry) -> None:
        """Internal documentation."""
        # ── col 1: seq ──
        seq_str = str(entry.seq)
        t.append(f"{seq_str:<{_W_SEQ}}", style=_COL_INK_FAINT)
        t.append(_COL_GAP)

        t.append(entry.summary_human, style=_COL_INK)
        t.append(_COL_GAP)

        risk_val = entry.risk
        disp, color = _RISK_COLOR.get(risk_val, (risk_val, _COL_INK_DIM))
        t.append(f"{disp:<{_W_RISK}}", style=color)
        t.append(_COL_GAP)

        rev_val = entry.reversible
        disp_r, color_r = _REV_COLOR.get(rev_val, (rev_val, _COL_INK_FAINT))
        t.append(f"{disp_r:<{_W_REV}}", style=color_r)
        t.append(_COL_GAP)

        undo_val = entry.undo_state
        disp_u, color_u = _UNDO_COLOR.get(undo_val, ("—", _COL_INK_FAINT))
        t.append(f"{disp_u:<{_W_UNDO}}", style=color_u)
        t.append(_COL_GAP)

        sig_disp = (entry.receipt_sig or "")[:_SIG_DISPLAY_LEN]
        t.append(f"{sig_disp:<{_W_SIG}}", style=_COL_INK_FAINT)

        t.append("\n")
