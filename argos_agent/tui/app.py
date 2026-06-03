"""Argos TUI 外壳 —— Phase 1 只立骨架与布局,不接 agent loop。"""
from __future__ import annotations

from textual.app import App, ComposeResult
from textual.widgets import Footer, Header, Static


class ArgosApp(App):
    TITLE = "Argos"
    SUB_TITLE = "诚实可靠的终端编码智能体"

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(
            "Argos TUI — 骨架就绪（占位）。后续阶段接入 agent loop / 状态 / 审批。",
            id="welcome",
        )
        yield Footer()
