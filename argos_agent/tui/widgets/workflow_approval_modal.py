"""WorkflowApprovalModal:工作流编排审批弹窗(Task 12)。

显示多行 preview(render_preview(spec) —— 人类可读的工作流编排预览),让用户批准/拒绝
起多个子 agent 跑工作流。dismiss 回 DecisionKind 字符串(deny|once|always),由 app 回调
gate.respond(call_id, decision) 放行/拒绝 loop 侧 await。

键盘:↵ / 4=always 批准(整段工作流一次起多 agent,无逐工具复批必要,故只给一次/总是/拒绝);
Esc=拒绝(fail-closed:不明确批准即不放行)。markup=False:preview 可能含 `[...]`,防崩。
"""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Static


class WorkflowApprovalModal(ModalScreen[str]):
    """dismiss 值 = DecisionKind 字符串(once|always|deny)。"""

    DEFAULT_CSS = """
    WorkflowApprovalModal {
        align: center middle;
    }
    WorkflowApprovalModal > #workflow-approval-dialog {
        border: round $warning;
        background: $surface;
        padding: 1 2;
        width: auto;
        max-width: 80%;
        height: auto;
    }
    WorkflowApprovalModal #wf-title { color: $warning; text-style: bold; }
    WorkflowApprovalModal #wf-keys { color: $text-muted; }
    """

    BINDINGS = [
        ("enter", "decide('once')", "批准"),
        ("4", "decide('always')", "总是"),
        ("2", "decide('once')", "本次"),
        ("1", "decide('deny')", "拒绝"),
        ("escape", "decide('deny')", "拒绝"),
    ]

    def __init__(self, preview: str) -> None:
        super().__init__()
        self._preview = preview

    def compose(self) -> ComposeResult:
        # markup=False:preview 是工作流编排预览(可能含 `[...]`),按纯文本渲染防崩。
        yield Vertical(
            Static("⚙ 工作流审批 — 将起多个子 agent 编排执行", id="wf-title", markup=False),
            Static(self._preview, id="wf-preview", markup=False),
            Static("[↵/2] 本次批准   [4] 总是   [Esc/1] 拒绝", id="wf-keys", markup=False),
            id="workflow-approval-dialog",
        )

    def action_decide(self, decision: str) -> None:
        self.dismiss(decision)
