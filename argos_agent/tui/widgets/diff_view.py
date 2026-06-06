"""文件 diff 块:⏺ header + 红绿 diff 高亮(spec §widget 改造)。"""
from __future__ import annotations

from rich.syntax import Syntax
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Static


class DiffView(Vertical):
    DEFAULT_CSS = """
    DiffView {
        border: round $panel;
        border-title-color: $accent;
        padding: 0 1;
        margin: 0 1 1 1;
        height: auto;
    }
    """
    def __init__(self, *, path: str, added: int, removed: int, unified: str) -> None:
        super().__init__()
        # 保留公开属性(API 兼容:wiring/外部读 d.path/d.added/d.removed/d.unified)
        self.path = path
        self.added = added
        self.removed = removed
        self.unified = unified
        self._unified = unified
        self.border_title = f"⏺ Edit · {path}"
        self.border_subtitle = f"+{added} -{removed}"

    def compose(self) -> ComposeResult:
        yield Static(Syntax(self._unified, "diff", theme="monokai", word_wrap=True), id="diff")
