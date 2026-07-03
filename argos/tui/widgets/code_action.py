# argos/tui/widgets/code_action.py
"""Code execution block for inline TUI actions."""
from __future__ import annotations

from rich.syntax import Syntax
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.reactive import reactive
from textual.widgets import Static

from argos.i18n import t

_EYE = "#D9A85C"
_INK_DIM = "#7E869C"
_CODE_MAX = 8
_CODE_HEAD = 6


class CodeActionBlock(Vertical):
    """Render code results with branch eye glyphs.

    The first result line uses `└ ◕` for the ok eye state and `└ ◉` for the fail eye state.
    The colors stay tied to $pass and $fail tokens instead of hardcoded pass/fail badges.
    """
    DEFAULT_CSS = """
    CodeActionBlock { height: auto; margin: 0 0 1 0; background: $raise; padding: 0 2; }
    CodeActionBlock #code { padding: 0 0 0 2; }
    CodeActionBlock #code-fold { color: $ink-ghost; padding: 0 0 0 2; }
    CodeActionBlock #result { color: $ink-faint; padding: 0 0 0 2; }
    CodeActionBlock.ok-false #result { color: $fail; }
    """
    ok: reactive[bool | None] = reactive(None)

    def __init__(self, *, code: str, step: int) -> None:
        super().__init__()
        self._code = code
        self._step = step

    def compose(self) -> ComposeResult:
        header = Text.assemble(("⏺ ", f"bold {_EYE}"), (f"python · step {self._step}", _INK_DIM))
        yield Static(header, id="header")
        lines = self._code.splitlines()
        shown = self._code
        folded = 0
        if len(lines) > _CODE_MAX:
            shown = "\n".join(lines[:_CODE_HEAD])
            folded = len(lines) - _CODE_HEAD
        yield Static(Syntax(shown, "python", theme="monokai", background_color="#1B1D29",
                            line_numbers=False, word_wrap=True), id="code")
        if folded:
            yield Static(t("widget.code_fold", n=folded), id="code-fold", markup=False)
        yield Static(t("widget.code_running"), id="result", markup=False)

    def set_result(self, *, stdout: str, value_repr: str, exc: str, ok: bool) -> None:
        """Internal documentation."""
        self.ok = ok
        body = exc if (not ok and exc) else (stdout or "")
        if value_repr:
            body += t("widget.code_return_value", repr=value_repr)
        text = body.strip() or (t("widget.code_done") if ok else t("widget.code_error"))
        lines = text.splitlines()
        if not ok and text.startswith("Traceback (most recent call last):"):
            nonempty = [ln for ln in lines if ln.strip()]
            headline = nonempty[-1] if nonempty else text
            hidden = max(0, len(lines) - 1)
            text = headline if hidden == 0 else f"{headline}\n{t('widget.code_stack_folded', n=hidden)}"
        elif len(lines) > 12:
            text = "\n".join(lines[:8]) + "\n" + t("widget.code_fold", n=len(lines) - 8)
        glyph = "◕" if ok else "◉"
        self.query_one("#result", Static).update(f"└ {glyph} {text}")

    def watch_ok(self, value: bool | None) -> None:
        self.set_class(value is False, "ok-false")
