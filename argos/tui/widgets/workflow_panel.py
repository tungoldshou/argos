"""Internal documentation."""
from __future__ import annotations

from rich.text import Text
from textual.widgets import Static

from argos.i18n import t

_COL_INK_BRIGHT = "#ECEEF5"
_COL_EYE = "#D9A85C"
_COL_PASS = "#9ECE6A"
_COL_FAIL = "#F7768E"
_COL_INK_DIM = "#7E869C"
_COL_INK_FAINT = "#6B7494"

# _PHASE_KEY:  i18n key map (single source of truth for render and tests).
# _PHASE_TEXT: derived at import time via t() — imported by tests for contract assertions.
#              Values reflect the active ARGOS_LANG (ZH in test suite, EN by default).
_PHASE_KEY = {
    "plan":   "widget.phase_plan",
    "act":    "widget.phase_act",
    "verify": "widget.phase_verify",
    "report": "widget.phase_report",
    "done":   "widget.phase_done",
    "error":  "widget.phase_error",
}
_PHASE_TEXT = {phase: t(key) for phase, key in _PHASE_KEY.items()}
_PHASE_GLYPH = {
    "plan": "◔",
    "act": "◉",
    "verify": "❂",
    "report": "◕",
    "done": "◕",
    "error": "◉",
}
_PHASE_GLYPH_COLOR = {
    "plan":   _COL_EYE,
    "act":    _COL_EYE,
    "verify": _COL_EYE,
    "report": _COL_PASS,
    "done":   _COL_PASS,
    "error":  _COL_FAIL,
}


class WorkflowPanel(Static):
    """Internal documentation."""

    DEFAULT_CSS = """
    WorkflowPanel {
        border: round $accent;
        padding: 0 1;
        margin: 0 1 1 1;
        height: auto;
    }
    """

    def __init__(self, *, name: str, **kwargs) -> None:
        super().__init__("", markup=False, **kwargs)
        self._name = name
        self._order: list[str] = []
        self._agents: dict[str, tuple[str, str]] = {}
        self._done = False
        self._synthesis = ""
        self._notes: tuple[str, ...] = ()
        self.update(self._compose_text())

    def update_progress(self, agent_id: str, phase: str, note: str = "") -> None:
        """Internal documentation."""
        if agent_id not in self._agents:
            self._order.append(agent_id)
        self._agents[agent_id] = (phase, note)
        self.update(self._compose_text())

    def finish(self, synthesis: str, notes: tuple[str, ...] = ()) -> None:
        """Internal documentation."""
        self._done = True
        self._synthesis = synthesis
        self._notes = tuple(notes or ())
        self.update(self._compose_text())

    @property
    def rendered_text(self) -> str:
        """Internal documentation."""
        return self._compose_text().plain

    def _compose_text(self) -> Text:
        """Internal documentation."""
        result = Text(no_wrap=False, end="")

        if self._done:
            head = t("widget.workflow_title_done", name=self._name)
        else:
            head = t("widget.workflow_title", name=self._name)
        result.append(head, style=f"bold {_COL_INK_BRIGHT}")

        for agent_id in self._order:
            phase, note = self._agents[agent_id]
            glyph = _PHASE_GLYPH.get(phase, "·")
            phase_text = t(_PHASE_KEY.get(phase, "widget.phase_plan")) if phase in _PHASE_KEY else phase
            glyph_color = _PHASE_GLYPH_COLOR.get(phase, _COL_EYE)

            result.append("\n  ")
            result.append(glyph, style=glyph_color)
            result.append(f" {agent_id} {phase_text}")
            if note:
                result.append(f" — {note}")

        if self._done:
            result.append(t("widget.workflow_synthesis_label"), style=_COL_INK_DIM)
            result.append(self._synthesis, style=_COL_INK_DIM)
            for n in self._notes:
                result.append("\n    · ", style=_COL_INK_FAINT)
                result.append(n, style=_COL_INK_FAINT)

        return result
