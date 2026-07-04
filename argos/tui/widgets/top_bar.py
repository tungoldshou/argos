# argos/tui/widgets/top_bar.py
from __future__ import annotations

from rich.text import Text
from textual.widgets import Static

from argos.i18n import t

_EYE_SOFT = "#A8854A"
_EYE = "#D9A85C"
_INK_BRIGHT = "#ECEEF5" # Internal note.
_INK_DIM = "#7E869C"
_PLAN = "#7AA2F7"
_FAIL = "#F7768E"
_PASS = "#9ECE6A"
_UNVERIF = "#FF9E64"

_PHASE_GLYPH: dict[str, str] = {
    "idle":    "◌",
    "plan":    "◔",
    "act":     "◉",
    "verify":  "❂",
    "report":  "◕",
    "done":    "◕",
    "blocked": "◓",
}


class TopBar(Static):
    DEFAULT_CSS = """
    TopBar { height: 1; background: $surface; padding: 0 1; }  /* $surface resolves to $well in the bare app */
    """

    def __init__(self, *, version: str = "0.x", model_label: str = "—", **kwargs) -> None:
        super().__init__("", **kwargs)
        self._version = version
        self._model = model_label
        self._plan_mode = False
        self._yolo = False
        self._has_key = True
        self._phase = "idle"
        self._trust_level: int | None = None
        self._trust_label: str = ""

    def set_state(
        self, *,
        model_label: str | None = None,
        plan_mode: bool | None = None,
        yolo: bool | None = None,
        has_key: bool | None = None,
        trust_level: int | None = None,
        trust_label: str | None = None,
    ) -> None:
        if model_label is not None:
            self._model = model_label
        if plan_mode is not None:
            self._plan_mode = bool(plan_mode)
        if yolo is not None:
            self._yolo = bool(yolo)
        if has_key is not None:
            self._has_key = bool(has_key)
        if trust_level is not None:
            self._trust_level = int(trust_level)
        if trust_label is not None:
            self._trust_label = trust_label
        self.refresh()

    def set_phase(self, phase: str) -> None:
        self._phase = phase
        self.refresh()

    def badges(self) -> list[str]:
        out: list[str] = []
        if self._plan_mode:
            out.append(t("widget.badge_plan"))
        if self._yolo:
            out.append(t("widget.badge_yolo"))
        if not self._has_key:
            out.append(t("widget.badge_no_key"))
        else:
            out.append(t("widget.badge_live"))
        from argos.config import sandbox_enabled
        if not sandbox_enabled():
            out.append(t("widget.badge_no_sandbox"))
        if self._trust_level is not None:
            prefix = "⏻ " if self._trust_level == 4 else ""
            label_part = f" · {self._trust_label}" if self._trust_label else ""
            out.append(f"{prefix}L{self._trust_level}{label_part}")
        return out

    @property
    def render_text(self) -> str:
        return str(self.render())

    def render(self) -> Text:
        glyph = _PHASE_GLYPH.get(self._phase, "◌")
        if self._phase == "blocked":
            eye_color = _UNVERIF
        elif self._phase == "idle":
            eye_color = _EYE_SOFT
        else:
            eye_color = _EYE
        left = Text()
        left.append(f"{glyph} ", style=f"bold {eye_color}")
        left.append(f"Argos v{self._version}", style=f"bold {_INK_BRIGHT}")
        left.append(f" · {self._model}", style=_INK_DIM)

        right = Text()
        for i, b in enumerate(self.badges()):
            if i:
                right.append("  ")
            style = self._badge_style(b)
            right.append(b, style=style)

        width = self.size.width or 0
        pad = max(1, width - left.cell_len - right.cell_len - 2)
        return Text.assemble(left, " " * pad, right) if right.cell_len else left

    def _badge_style(self, badge: str) -> str:
        _FIXED: dict[str, str] = {
            t("widget.badge_plan"): _PLAN,
            t("widget.badge_yolo"): _FAIL,
            t("widget.badge_no_key"): _UNVERIF,
            t("widget.badge_live"): _PASS,
        }
        if badge in _FIXED:
            return _FIXED[badge]
        if self._trust_level == 4:
            return _FAIL
        return _EYE_SOFT
