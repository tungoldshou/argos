"""PlanModal:4 选项 plan 审批 modal(spec §2.4,对齐 CC)。"""
from __future__ import annotations

from dataclasses import dataclass

from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static


@dataclass(frozen=True)
class PlanDecision:
    """PlanModal 选项结果。"""
    action: str  # "approve_start" | "approve_accept_edits" | "keep_planning" | "refine"
    feedback: str | None = None


class PlanModal(ModalScreen[PlanDecision]):
    """4 选项 plan 审批 modal。返回 PlanDecision。

    数字键 1/2/3/4 绑定(对齐 CC)。
    """

    BINDINGS = [
        Binding("1", "decide('approve_start')", "Approve and start"),
        Binding("2", "decide('approve_accept_edits')", "Approve and accept edits"),
        Binding("3", "decide('keep_planning')", "Keep planning"),
        Binding("4", "decide('refine')", "Refine with feedback"),
    ]

    CSS = """
    PlanModal {
        align: center middle;
    }
    PlanModal > Vertical {
        width: 80;
        height: auto;
        padding: 1;
        border: round $primary;
    }
    PlanModal #plan-md {
        height: auto;
        max-height: 20;
        overflow-y: auto;
    }
    PlanModal #plan-buttons {
        height: auto;
    }
    """

    def __init__(self, plan_md: str) -> None:
        super().__init__()
        self.plan_md = plan_md
        self.options = [
            "approve_start",
            "approve_accept_edits",
            "keep_planning",
            "refine",
        ]

    def compose(self):
        with Vertical():
            yield Static("📋 Plan 审批", id="plan-title")
            yield Static(self.plan_md, id="plan-md", markup=False)
            with Horizontal(id="plan-buttons"):
                yield Button("1. Approve and start", id="btn-1")
                yield Button("2. Approve and accept edits", id="btn-2")
                yield Button("3. Keep planning", id="btn-3")
                yield Button("4. Refine", id="btn-4")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        # 4 按钮映射 4 action
        mapping = {
            "btn-1": "approve_start",
            "btn-2": "approve_accept_edits",
            "btn-3": "keep_planning",
            "btn-4": "refine",
        }
        action = mapping.get(event.button.id or "")
        if action:
            self.dismiss(PlanDecision(action=action))

    def action_decide(self, action: str) -> None:
        """数字键 binding 入口。"""
        if action == "refine":
            # 选项 4 弹输入框(本期简化:直接返空 feedback,UI 后续补 input box)
            # spec §2.4:选项 4 弹输入框 — v1.1 完善
            self.dismiss(PlanDecision(action="refine", feedback=""))
        else:
            self.dismiss(PlanDecision(action=action))
