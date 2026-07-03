# argos/tui/widgets/hard_confirm_card.py
"""Internal documentation."""
from __future__ import annotations

from collections.abc import Callable

from rich.text import Text
from textual.app import ComposeResult
from textual.widgets import Static

from argos.i18n import t
from argos.tui.widgets.inline_choice import InlineChoice

_COL_FAIL       = "#F7768E"
_COL_EYE        = "#D9A85C"
_COL_INK_BRIGHT = "#ECEEF5"
_COL_INK_DIM    = "#7E869C"
_COL_INK_FAINT  = "#6B7494"

_OPTION_DIGIT: dict[str, str] = {
    "once": "1",
    "deny": "4",
}


def _body_line(
    action: str,
    *,
    x: int | None,
    y: int | None,
    description: str,
    text: str | None,
    app: str | None,
) -> str:
    """Internal documentation."""
    if x is not None and y is not None:
        return f"{action} ({x}, {y}) — {description}"
    return f"{action} — {description}"


class HardConfirmCard(InlineChoice):
    """Internal documentation."""

    @property
    def _GOVERNANCE_TEXT(self) -> str:  # type: ignore[override]
        return t("hardconfirm.governance")

    @property
    def _FOOTER_TEXT(self) -> str:  # type: ignore[override]
        return t("hardconfirm.footer")

    DEFAULT_CSS = """
    HardConfirmCard #hc-gov { color: $ink-faint; }
    HardConfirmCard #hc-foot { color: $ink-faint; margin-top: 1; }
    """

    def __init__(
        self,
        *,
        action: str,
        x: int | None,
        y: int | None,
        description: str,
        on_decide: Callable[[str, str], None],
        text: str | None = None,
        app: str | None = None,
        **kwargs,
    ) -> None:
        """Internal documentation."""
        body = _body_line(action, x=x, y=y, description=description, text=text, app=app)
        super().__init__(
            title=t("hardconfirm.title"),
            body=body,
            options=[
                ("once", t("hardconfirm.option_once")),
                ("deny", t("hardconfirm.option_deny")),
            ],
            on_decide=on_decide,
            escape_value="deny",
            risk="high",
            action_label=action,
            **kwargs,
        )

    def _options_text(self) -> Text:
        """Internal documentation."""
        t = Text()
        for i, (value, label) in enumerate(self._options):
            cur = i == self._cursor
            digit = _OPTION_DIGIT.get(value, str(i + 1))
            t.append("▸ " if cur else "  ", style=f"bold {_COL_EYE}")
            t.append(
                f"{digit}  {label}",
                style=f"bold {_COL_INK_BRIGHT}" if cur else _COL_INK_DIM,
            )
            if i < len(self._options) - 1:
                t.append("\n")
        return t

    def _digit_to_option_index(self, digit: str) -> int | None:
        """Internal documentation."""
        mapping = {"1": 0, "4": 1}
        return mapping.get(digit)

    async def _on_key(self, event) -> None:  # type: ignore[override]
        """Internal documentation."""
        if self._decided:
            return
        key = event.key
        if key.isdigit():
            event.stop()
            idx = self._digit_to_option_index(key)
            if idx is not None:
                self._cursor = idx
                self._refresh_options()
                self._confirm(self._options[self._cursor][0])
            return
        await super()._on_key(event)

    def _finish(self, value: str, feedback: str) -> None:
        """Internal documentation."""
        if self._decided:
            return
        self._decided = True
        try:
            self._on_decide(value, feedback)
        finally:
            summary_text = t("hardconfirm.finish_summary", action_label=self._action_label, value=value)
            parent = self.parent
            try:
                if parent is not None:
                    summary = Static(summary_text, markup=False, classes="ic-summary")
                    parent.mount(summary, after=self)
            except Exception:  # noqa: BLE001
                pass
            try:
                self.remove()
            except Exception:  # noqa: BLE001
                pass
            try:
                self.app.query_one("#prompt").focus()
            except Exception:  # noqa: BLE001
                pass

    def compose(self) -> ComposeResult:
        """Internal documentation."""
        from textual.widgets import Input
        from textual.widgets import Static as _Static

        yield _Static(self._title, id="ic-title", markup=False)
        if self._body:
            yield _Static(self._body, id="ic-body", markup=False)
        yield _Static(self._GOVERNANCE_TEXT, id="hc-gov", markup=False)
        yield _Static(self._options_text(), id="ic-options")
        yield _Static(self._FOOTER_TEXT, id="hc-foot", markup=False)
        yield _Static(self._hint_text(), id="ic-hint", markup=False)
        yield Input(placeholder=self._input_placeholder, id="ic-input")
