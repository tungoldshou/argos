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
        title = _format_title(icon=icon, risk=r.risk, trigger=getattr(r, "trigger", "") or "")
        children = [
            Label(title, id="ap-title"),
            Label(r.description, id="ap-desc"),
            Label(f"动作: {r.action}", id="ap-action"),
            Label(f"参数: {r.args}", id="ap-args"),
        ]
        # Smart approval 副标题(D6 锁):secret 命中显 "did you mean to commit this?" 提示
        if getattr(r, "secret_pattern", None):
            children.append(Label(
                "⚠ Possible secret pattern matched: did you mean to commit this?",
                id="ap-secret",
            ))
        children.append(Label("[1] 拒绝   [2] 本次   [3] 本会话   [4] 总是", id="ap-keys"))
        yield Vertical(*children, id="approval-dialog")

    def action_decide(self, decision: str) -> None:
        self.dismiss(decision)


def _format_title(*, icon: str, risk: str, trigger: str) -> str:
    """Smart approval 标题(spec 2026-06-06 §2.6, D6 锁):trigger 标签按类别格式化。

    标签格式约定:
      hard_rule:X       → [hard rule: X]
      soft_allow:X      → [soft rule: allow X]
      soft_ask:X        → [soft rule: ask X]
      soft_deny:X       → [soft rule: deny X]
      secret:X          → [secret: X]
      tool_level:T=L    → [level: L]
      level:L           → [level: L]
    空 trigger / 未知前缀 → 不附加标签(向后兼容)。"""
    base = f"{icon} 审批请求 [{risk}]"
    if not trigger:
        return base
    if trigger.startswith("hard_rule:"):
        tag = f"[hard rule: {trigger.split(':', 1)[1]}]"
    elif trigger.startswith("soft_allow:"):
        tag = f"[soft rule: allow {trigger.split(':', 1)[1]}]"
    elif trigger.startswith("soft_ask:"):
        tag = f"[soft rule: ask {trigger.split(':', 1)[1]}]"
    elif trigger.startswith("soft_deny:"):
        tag = f"[soft rule: deny {trigger.split(':', 1)[1]}]"
    elif trigger.startswith("secret:"):
        tag = f"[secret: {trigger.split(':', 1)[1]}]"
    elif trigger.startswith("tool_level:"):
        inner = trigger.split("=", 1)[1] if "=" in trigger else trigger
        tag = f"[level: {inner}]"
    elif trigger.startswith("level:"):
        tag = f"[level: {trigger.split(':', 1)[1]}]"
    else:
        return base
    return f"{base} — {tag}"
