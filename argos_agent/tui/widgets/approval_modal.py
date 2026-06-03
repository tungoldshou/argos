"""ApprovalModal:审批弹窗(spec §4.3,契约 §6.3)。

键盘速选 1=deny 2=once 3=session 4=always(对齐 DecisionKind)。dismiss 回 decision 字符串,
由 app 回调:① gate.respond(call_id, decision) 放行/拒绝 broker;② 投 ApprovalResponse 事件存档。
"""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Label

from argos_agent.tui.events import ApprovalRequest

# 1-4 → DecisionKind(契约 §6.3)
_KEY_TO_DECISION: dict[str, str] = {"1": "deny", "2": "once", "3": "session", "4": "always"}
_RISK_ICON = {"low": "·", "medium": "⚠", "high": "⛔"}


class ApprovalModal(ModalScreen[str]):
    """dismiss 值 = DecisionKind 字符串(deny|once|session|always)。"""

    BINDINGS = [
        ("1", "decide('deny')", "拒绝"),
        ("2", "decide('once')", "本次"),
        ("3", "decide('session')", "本会话"),
        ("4", "decide('always')", "总是"),
        ("escape", "decide('deny')", "拒绝"),
    ]

    def __init__(self, request: ApprovalRequest) -> None:
        super().__init__()
        self.request = request

    def compose(self) -> ComposeResult:
        r = self.request
        icon = _RISK_ICON.get(r.risk, "·")
        yield Vertical(
            Label(f"{icon} 审批请求 [{r.risk}]", id="ap-title"),
            Label(r.description, id="ap-desc"),
            Label(f"动作: {r.action}", id="ap-action"),
            Label(f"参数: {r.args}", id="ap-args"),
            Label("[1] 拒绝   [2] 本次   [3] 本会话   [4] 总是", id="ap-keys"),
            id="approval-dialog",
        )

    def action_decide(self, decision: str) -> None:
        self.dismiss(decision)
