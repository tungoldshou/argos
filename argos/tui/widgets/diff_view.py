"""Internal documentation."""
from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Static

_PASS  = "#9ECE6A"
_FAIL  = "#F7768E"
_DIM   = "#7E869C"
_INK   = "#C8CCDA"


def _render_diff(unified: str) -> Text:
    """Internal documentation."""
    out = Text(no_wrap=False, overflow="fold")
    for i, raw_line in enumerate(unified.splitlines(keepends=False)):
        if i > 0:
            out.append("\n")
        first = raw_line[:1]
        if first == "+":
            out.append(raw_line, style=_PASS)
        elif first == "-":
            out.append(raw_line, style=_FAIL)
        elif first == "@":
            out.append(raw_line, style=_DIM)
        else:
            out.append(raw_line, style=_INK)
    return out


class DiffView(Vertical):
    """Internal documentation."""

    DEFAULT_CSS = """
    DiffView {
        border-left: tall $hairline-lit;
        border-title-color: $ink-bright;
        background: $raise;
        padding: 0 1;
        margin: 0 0 1 0;
        height: auto;
    }
    """

    def __init__(self, *, path: str, added: int, removed: int, unified: str) -> None:
        super().__init__()
        self.path = path
        self.added = added
        self.removed = removed
        self.unified = unified
        self._unified = unified
        self.border_title = f"Edit · {path}"
        self.border_subtitle = f"+{added} −{removed}"

    def compose(self) -> ComposeResult:
        yield Static(_render_diff(self._unified), id="diff")
