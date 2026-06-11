"""文件 diff 块:仅左缘竖线 + 红绿 diff 高亮(spec §4.5,TUI v3 黑曜石之眼)。

v3 变更:
- border: round $panel → border-left: tall $hairline-lit(仅左缘一线)
- background: $raise(浮起面,比流面亮一档)
- border_title: 去掉 ⏺ 前缀,改纯文字 "Edit · {path}"
- border_subtitle: 减号改 U+2212(−,真数学减号,非 ASCII 连字符)
"""
from __future__ import annotations

from rich.syntax import Syntax
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Static


class DiffView(Vertical):
    """文件变更 diff 块,左缘点亮发丝竖线,背景浮起。"""

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
        # 保留公开属性(API 兼容:wiring/外部读 d.path/d.added/d.removed/d.unified)
        self.path = path
        self.added = added
        self.removed = removed
        self.unified = unified
        self._unified = unified
        # v3: 纯文字标题,去掉 ⏺ 前缀;减号用 U+2212 而非 ASCII '-'
        self.border_title = f"Edit · {path}"
        self.border_subtitle = f"+{added} −{removed}"

    def compose(self) -> ComposeResult:
        yield Static(Syntax(self._unified, "diff", theme="monokai", word_wrap=True), id="diff")
