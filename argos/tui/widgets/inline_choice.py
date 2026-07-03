# argos/tui/widgets/inline_choice.py
"""Internal documentation."""
from __future__ import annotations

from collections.abc import Callable

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Input, Static

from argos.i18n import t

_WARNING_SIGN = "⚠︎"


def format_approval_title(*, risk: str, trigger: str) -> str:
    """Internal documentation."""
    base = t("widget.approval_title_base", risk=risk)
    if not trigger:
        return base
    if trigger.startswith("hard_rule:"):
        tag = f"[hard rule: {trigger.split(':', 1)[1]}]"
        return f"{base} — {tag}"
    elif trigger.startswith("soft_allow:"):
        tag = f"[soft rule: allow {trigger.split(':', 1)[1]}]"
        return f"{base} — {tag}"
    elif trigger.startswith("soft_ask:"):
        tag = f"[soft rule: ask {trigger.split(':', 1)[1]}]"
        return f"{base} — {tag}"
    elif trigger.startswith("soft_deny:"):
        tag = f"[soft rule: deny {trigger.split(':', 1)[1]}]"
        return f"{base} — {tag}"
    elif trigger.startswith("secret:"):
        key_name = trigger.split(":", 1)[1]
        secret_label = t("widget.approval_secret_hit", _WARNING_SIGN=_WARNING_SIGN, key_name=key_name)
        return f"{base} · {secret_label}"
    elif trigger.startswith("tool_level:"):
        inner = trigger.split("=", 1)[1] if "=" in trigger else trigger
        tag = f"[level: {inner}]"
        return f"{base} — {tag}"
    elif trigger.startswith("level:"):
        tag = f"[level: {trigger.split(':', 1)[1]}]"
        return f"{base} — {tag}"
    else:
        return base


class InlineChoice(Vertical):
    """Internal documentation."""

    DEFAULT_CSS = """
    InlineChoice { height: auto; margin: 0 0 1 0; padding: 1 2; background: $raise; border-left: thick $unverif; }
    InlineChoice.risk-low  { border-left: thick $hairline-lit; }
    InlineChoice.risk-high { border-left: thick $fail; }
    InlineChoice.risk-plan { border-left: thick $plan; }
    InlineChoice #ic-title { text-style: bold; color: $unverif; }
    InlineChoice.risk-high #ic-title { color: $fail; }
    InlineChoice.risk-plan #ic-title { color: $plan; }
    InlineChoice #ic-body { color: $ink-bright; }
    InlineChoice #ic-hint { color: $ink-faint; }
    InlineChoice #ic-input { display: none; }
    InlineChoice.-input-mode #ic-input { display: block; }
    .ic-summary { color: $ink-faint; }
    """

    can_focus = True

    def __init__(
        self,
        *,
        title: str,
        body: str = "",
        options: list[tuple[str, str]],
        on_decide: Callable[[str, str], None],
        escape_value: str | None = None,
        needs_input: frozenset[str] | set[str] = frozenset(),
        input_placeholder: str | None = None,
        risk: str = "medium",
        action_label: str = "",
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        if not options:
            raise ValueError(t("widget.choice_empty"))
        self._title = title
        self._body = body
        self._options = list(options)
        self._on_decide = on_decide
        self._escape_value = escape_value
        self._needs_input = frozenset(needs_input)
        self._input_placeholder = input_placeholder if input_placeholder is not None else t("widget.choice_input_placeholder")
        self._action_label = action_label or (options[0][0] if options else "")
        self._cursor = 0
        self._decided = False
        self._pending_value: str | None = None
        self.add_class(f"risk-{risk}" if risk in ("low", "high", "plan") else "risk-medium")

    def compose(self) -> ComposeResult:
        yield Static(self._title, id="ic-title", markup=False)
        if self._body:
            yield Static(self._body, id="ic-body", markup=False)
        yield Static(self._options_text(), id="ic-options")
        yield Static(self._hint_text(), id="ic-hint", markup=False)
        yield Input(placeholder=self._input_placeholder, id="ic-input")

    _COL_EYE       = "#D9A85C"
    _COL_INK_BRIGHT = "#ECEEF5"
    _COL_INK_DIM   = "#7E869C"

    def _options_text(self) -> Text:
        """Internal documentation."""
        txt = Text()
        for i, (_, label) in enumerate(self._options):
            cur = i == self._cursor
            txt.append("▸ " if cur else "  ", style=f"bold {self._COL_EYE}")
            txt.append(
                f"{i + 1}  {label}",
                style=f"bold {self._COL_INK_BRIGHT}" if cur else self._COL_INK_DIM,
            )
            if i < len(self._options) - 1:
                txt.append("\n")
        return txt

    def _hint_text(self) -> str:
        esc = t("widget.choice_hint_esc") if self._escape_value else ""
        return t("widget.choice_hint_base") + esc

    def _refresh_options(self) -> None:
        self.query_one("#ic-options", Static).update(self._options_text())

    def on_mount(self) -> None:
        self.focus()
        try:
            self.app.bell()
        except Exception:  # noqa: BLE001
            pass

    async def _on_key(self, event: events.Key) -> None:
        if self._decided:
            return
        key = event.key
        if self.has_class("-input-mode"):
            if key == "escape":
                event.stop()
                self._pending_value = None
                self.remove_class("-input-mode")
                self.focus()
            else:
                await super()._on_key(event)
            return
        if key == "up":
            event.stop()
            self._cursor = (self._cursor - 1) % len(self._options)
            self._refresh_options()
        elif key == "down":
            event.stop()
            self._cursor = (self._cursor + 1) % len(self._options)
            self._refresh_options()
        elif key == "enter":
            event.stop()
            self._confirm(self._options[self._cursor][0])
        elif key == "escape" and self._escape_value:
            event.stop()
            self._finish(self._escape_value, "")
        elif key.isdigit() and 1 <= int(key) <= len(self._options):
            event.stop()
            self._cursor = int(key) - 1
            self._refresh_options()
            self._confirm(self._options[self._cursor][0])
        else:
            await super()._on_key(event)

    def _confirm(self, value: str) -> None:
        if value in self._needs_input:
            self._pending_value = value
            self.add_class("-input-mode")
            self.query_one("#ic-input", Input).focus()
            return
        self._finish(value, "")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if self._pending_value is not None:
            event.stop()
            self._finish(self._pending_value, event.value.strip())

    def _finish(self, value: str, feedback: str) -> None:
        """Internal documentation."""
        if self._decided:
            return
        self._decided = True
        try:
            self._on_decide(value, feedback)
        finally:
            summary_text = t("widget.choice_summary", action=self._action_label, value=value)
            parent = self.parent
            try:
                if parent is not None:
                    summary = Static(summary_text, markup=False, classes="ic-summary")
                    parent.mount(summary, after=self)
            except Exception:  # noqa: BLE001
                pass
            self.remove()
            try:
                self.app.query_one("#prompt").focus()
            except Exception:  # noqa: BLE001
                pass
