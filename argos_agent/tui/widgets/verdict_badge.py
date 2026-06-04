"""VerdictBadge:三态 verify 徽章(spec §4.2,契约 §6.1 fail-closed)。

✅passed / ❌failed / ⚠️无法验证 —— "无法验证"绝不显成 passed(不变量 §12.5)。
"""
from __future__ import annotations

from textual.reactive import reactive
from textual.widgets import Static

from argos_agent.core.types import Verdict, VerdictStatus

_ICON = {"passed": "✅", "failed": "❌", "unverifiable": "⚠️"}
_LABEL = {"passed": "verify", "failed": "verify FAILED", "unverifiable": "无法验证"}


class VerdictBadge(Static):
    """show(verdict) 后渲染对应三态行。三态着色色相分明(诚实硬约束)。"""

    DEFAULT_CSS = """
    VerdictBadge { border: round $panel; padding: 0 1; margin: 0 1 1 1; height: auto; }
    VerdictBadge.verdict-passed       { border: round $success; color: $success; }
    VerdictBadge.verdict-failed       { border: round $error;   color: $error; }
    VerdictBadge.verdict-unverifiable { border: round $warning; color: $warning; }
    """

    status: reactive[VerdictStatus | None] = reactive(None)

    def __init__(self, **kwargs) -> None:
        super().__init__("", **kwargs)
        self.render_text: str = ""

    def watch_status(self, value: str) -> None:
        # 三态各自独占一个 class，切换时清掉另两态——色相绝不混淆(passed绝不显成 failed/unverifiable)。
        for s in ("passed", "failed", "unverifiable"):
            self.set_class(value == s, f"verdict-{s}")

    def show(self, verdict: Verdict) -> None:
        icon = _ICON[verdict.status]
        label = _LABEL[verdict.status]
        cmd = verdict.verify_cmd or "—"
        if verdict.status == "unverifiable" and verdict.tampered:
            self.render_text = f"{icon} {label}: 受保护文件被改 {verdict.tampered} — {verdict.detail}"
        else:
            self.render_text = f"{icon} {label}: {cmd} → {verdict.detail}"
        self.status = verdict.status  # 触发 watch
        self.update(self.render_text)
