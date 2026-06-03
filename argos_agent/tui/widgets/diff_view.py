"""DiffView:文件编辑红绿 diff(spec §4.1/§4.2,借鉴 ACP edit diff)。"""
from __future__ import annotations

from rich.syntax import Syntax
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Static


class DiffView(Vertical):
    """一次文件编辑的统一 diff,带 path 与 +N/-M 计数 header。"""

    def __init__(self, *, path: str, added: int, removed: int, unified: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self.path = path
        self.added = added
        self.removed = removed
        self.unified = unified

    @property
    def header_text(self) -> str:
        return f"┌ diff ▸ {self.path} {self.added}+ {self.removed}-"

    def compose(self) -> ComposeResult:
        yield Static(self.header_text, id="diff-header")
        yield Static(Syntax(self.unified, "diff", theme="ansi_dark", word_wrap=True), id="diff-body")
