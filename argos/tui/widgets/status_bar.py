"""Internal documentation."""
from __future__ import annotations

from rich.text import Text
from textual.reactive import reactive
from textual.widgets import Static

from argos.core.types import Phase
from argos.i18n import t as _t

_PHASE_GLYPH: dict[str, str] = {
    "plan":   "◔",
    "act":    "◉",
    "verify": "❂",
    "report": "◕",
    "idle":   "◌",
}
_GLYPH_BLOCKED = "◓"

_STYLE_EYE      = "#D9A85C"
_STYLE_BLOCKED  = "#FF9E64"
_STYLE_INK_DIM  = "#7E869C"
_STYLE_INK_FAINT = "#6B7494"

def _hints() -> str:
    return _t("tui.statusbar.hints")


class StatusBar(Static):
    """Internal documentation."""

    DEFAULT_CSS = """
    StatusBar { dock: bottom; height: 1; background: $abyss; color: $ink-faint; padding: 0 2; }
    StatusBar.-plan-mode { color: $plan; }
    StatusBar.-ctx-warn { color: $unverif; text-style: bold; }
    StatusBar.-ctx-crit { color: $fail; text-style: bold; }
    StatusBar.-blocked { color: $unverif; }
    StatusBar.-alert { color: $fail; text-style: bold; }
    StatusBar.-alert-warn { color: $unverif; text-style: bold; }
    """

    # ── reactives ────────────────────────────────────────────────────────────
    phase:      reactive[str]        = reactive("idle")
    actions:    reactive[int]        = reactive(0)
    max_steps:  reactive[int | None] = reactive(None)
    tokens_in:  reactive[int]        = reactive(0)
    tokens_out: reactive[int]        = reactive(0)
    cost_usd:   reactive[float | None] = reactive(0.0)
    elapsed_s:  reactive[float]      = reactive(0.0)
    plan_mode:  reactive[bool]       = reactive(False)
    ctx_pct:    reactive[float]      = reactive(0.0)

    def __init__(self, **kwargs) -> None:
        super().__init__("", markup=False, **kwargs)
        self._blocked: bool = False
        self._alert: bool   = False
        self._alert_kind: str = "fail"
        self._run_summary: list[tuple[str, str]] = []
        self._kernel_mode: str = ""

    def _phase_eye(self) -> str:
        """Internal documentation."""
        return _PHASE_GLYPH.get(self.phase, "◌")

    def _resolve_render_state(self) -> tuple[str, str]:
        """Internal documentation."""
        if self._blocked:
            return _GLYPH_BLOCKED, "-blocked"
        if self._alert:
            return self._phase_eye(), ("-alert-warn" if self._alert_kind == "warn" else "-alert")
        return self._phase_eye(), ""

    def _ctx_class(self) -> str:
        """Internal documentation."""
        if self.ctx_pct >= 0.95:
            return "-ctx-crit"
        if self.ctx_pct >= 0.80:
            return "-ctx-warn"
        return ""

    def set_blocked(self, active: bool) -> None:
        """Internal documentation."""
        self._blocked = bool(active)
        self._refresh()

    def set_alert(self, active: bool, kind: str = "fail") -> None:
        """Internal documentation."""
        self._alert = bool(active)
        self._alert_kind = "warn" if kind == "warn" else "fail"
        self._refresh()

    @property
    def render_text(self) -> str:
        """Internal documentation."""
        eye, _ = self._resolve_render_state()

        _action_str = (
            _t("tui.statusbar.action", n=self.actions) + f"/{self.max_steps}"
            if self.max_steps is not None
            else _t("tui.statusbar.action", n=self.actions)
        )
        parts = [
            f"{eye} {self.phase}",
            _action_str,
        ]
        if self._blocked:
            parts.insert(1, _t("tui.statusbar.blocked_label"))
        if self.plan_mode:
            parts.append(_t("tui.statusbar.plan_mode"))
        if self._kernel_mode:
            parts.append(self._kernel_mode)
        return " · ".join(parts)

    def set_run_summary(self, runs: list[tuple[str, str]]) -> None:
        """Internal documentation."""
        self._run_summary = list(runs)
        self._refresh()

    def render_count_badges(self, runs: list[tuple[str, str]]) -> str:
        """Internal documentation."""
        if not runs:
            return ""
        active  = sum(1 for _, s in runs if s == "running")
        paused  = sum(1 for _, s in runs if s == "paused")
        history = sum(
            1 for _, s in runs
            if s in ("suspended", "completed", "failed", "cancelled")
        )
        return f"⏵{active} / ⏸{paused} / ⏹{history}"

    def set_phase(self, phase: Phase, actions: int, max_steps: int | None = None) -> None:
        """Internal documentation."""
        self.phase   = phase
        self.actions = actions
        if max_steps is not None:
            self.max_steps = max_steps

    def mark_run_end(self) -> None:
        """Internal documentation."""
        self.phase     = "idle"
        self.actions   = 0
        self.max_steps = None

    def set_cost(
        self,
        *,
        tokens_in: int,
        tokens_out: int,
        cost_usd: float | None,
        elapsed_s: float,
    ) -> None:
        """Internal documentation."""
        self.tokens_in  = tokens_in
        self.tokens_out = tokens_out
        self.cost_usd   = cost_usd
        self.elapsed_s  = elapsed_s

    def set_plan_mode(self, active: bool) -> None:
        """Internal documentation."""
        self.plan_mode = bool(active)

    def set_kernel_mode(self, mode: str) -> None:
        """Internal documentation."""
        self._kernel_mode = mode
        self._refresh()

    def update_ctx_pressure(self, pct: float) -> None:
        """Internal documentation."""
        self.ctx_pct = max(0.0, min(1.0, float(pct or 0.0)))

    def render(self) -> Text:
        """Internal documentation."""
        left_str = self.render_text
        left = Text(left_str, no_wrap=True, overflow="ellipsis")

        eye, _ = self._resolve_render_state()
        eye_style = _STYLE_EYE
        if left.plain.startswith(eye):
            left.stylize(eye_style, 0, len(eye))

        width = self.size.width or 0
        hints = Text(_hints(), style=_STYLE_INK_FAINT)
        pad = width - left.cell_len - hints.cell_len - 2
        if pad >= 1:
            return Text.assemble(left, " " * pad, hints)
        return left

    def _refresh(self) -> None:
        """Internal documentation."""
        self.refresh()
        self.set_class(self.plan_mode, "-plan-mode")
        _, css_suffix = self._resolve_render_state()
        for cls in ("-blocked", "-alert", "-alert-warn", "-ctx-warn", "-ctx-crit"):
            self.remove_class(cls)
        if css_suffix:
            self.add_class(css_suffix)
        else:
            ctx_cls = self._ctx_class()
            if ctx_cls:
                self.add_class(ctx_cls)

    # ── reactive watchers──────────────────────────────────────────────────────
    def watch_phase(self, _: str) -> None:
        self._refresh()

    def watch_actions(self, _: int) -> None:
        self._refresh()

    def watch_tokens_in(self, _: int) -> None:
        self._refresh()

    def watch_tokens_out(self, _: int) -> None:
        self._refresh()

    def watch_cost_usd(self, _: float | None) -> None:
        self._refresh()

    def watch_elapsed_s(self, _: float) -> None:
        self._refresh()

    def watch_plan_mode(self, _: bool) -> None:
        self._refresh()

    def watch_ctx_pct(self, _: float) -> None:
        self._refresh()
