"""Task 12:TUI 渲染工作流 —— 审批预览模态 + 实时进度树 + 汇总落行。

经真 App/Pilot 喂事件(仿 tests/test_tui_markup_safety.py 直接调 app._apply_event):
  · AUTO 档:不弹模态,直接渲染进度树 + 汇总落行;含方括号的 preview/synthesis 不崩(markup=False)。
  · CONFIRM 档:WorkflowProposed 弹出审批模态(screen 栈多一层),回调 gate.respond 落对 gate。
"""
import pytest

from argos_agent.approval import ApprovalGate, ApprovalLevel
from argos_agent.tui.app import ArgosApp
from argos_agent.tui.events import WorkflowDone, WorkflowProgress, WorkflowProposed
from argos_agent.tui.fakeloop import FakeLoop
from argos_agent.tui.widgets.workflow_panel import WorkflowPanel


@pytest.mark.asyncio
async def test_workflow_events_render_progress_and_summary():
    # AUTO 档:不弹模态,直接渲染进度+汇总
    app = ArgosApp(loop_factory=lambda: FakeLoop(), gate=ApprovalGate(ApprovalLevel.AUTO))
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await app._apply_event(WorkflowProposed(name="audit", description="审计",
            preview="将起 2 个 agent [review]", call_id="c1"))
        await app._apply_event(WorkflowProgress(stage_id="r", agent_id="r#0", phase="act", note=""))
        await app._apply_event(WorkflowProgress(stage_id="r", agent_id="r#1", phase="done", note="[ok]"))
        await app._apply_event(WorkflowDone(name="audit", synthesis="结论:list[str] 无问题", notes=()))
        await pilot.pause()
        assert app.is_running                       # 含方括号的 preview/synthesis 不崩
        panels = list(app.query(WorkflowPanel))
        assert panels, "应 mount 工作流进度面板"
        log = app.query_one("#transcript")
        assert "audit" in log.rendered_text         # 汇总落行


@pytest.mark.asyncio
async def test_workflow_proposed_pushes_modal_under_confirm():
    app = ArgosApp(loop_factory=lambda: FakeLoop(), gate=ApprovalGate(ApprovalLevel.CONFIRM))
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await app._apply_event(WorkflowProposed(name="x", description="d",
            preview="预览内容 [VOTE]", call_id="c2"))
        await pilot.pause()
        # CONFIRM 档应弹出审批模态(screen 栈多了一层)
        assert any("Modal" in type(s).__name__ or "Approval" in type(s).__name__
                   for s in app.screen_stack)


@pytest.mark.asyncio
async def test_workflow_panel_marks_error_phase_honestly():
    """诚实:error phase 显失败、不冒充完成;含方括号的 note 不崩(markup=False)。"""
    app = ArgosApp(loop_factory=lambda: FakeLoop(), gate=ApprovalGate(ApprovalLevel.AUTO))
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await app._apply_event(WorkflowProposed(name="w", description="d",
            preview="p", call_id="c3"))
        await app._apply_event(WorkflowProgress(stage_id="s", agent_id="s#0",
            phase="error", note="boom [trace]"))
        await pilot.pause()
        assert app.is_running
        panel = app.query_one(WorkflowPanel)
        assert panel._render_markup is False        # markup 安全(铁律)
        text = panel.rendered_text
        assert "s#0" in text
        assert "失败" in text                        # error → 失败,不显完成


@pytest.mark.asyncio
async def test_workflow_confirm_callback_responds_on_shared_gate():
    """CONFIRM 档批准回调把 decision 打在 app.gate(= broker gate)上,放行 loop 的 await。"""
    gate = ApprovalGate(ApprovalLevel.CONFIRM)
    app = ArgosApp(loop_factory=lambda: FakeLoop(), gate=gate)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        # 先在 gate 上挂一个与 call_id 对应的待批项(模拟 loop 侧 gate.request)。
        import asyncio
        loop = asyncio.get_running_loop()
        from argos_agent.approval import _Pending
        fut: asyncio.Future = loop.create_future()
        gate._pending["c4"] = _Pending(call_id="c4",
            payload={"action": "run_workflow", "args": {}},
            created_at=0.0, future=fut, loop=loop)
        await app._apply_event(WorkflowProposed(name="x", description="d",
            preview="预览", call_id="c4"))
        await pilot.pause()
        # 模态批准(数字 4=always),回调应 gate.respond("c4", ...) → 唤醒 future。
        await pilot.press("4")
        await pilot.pause()
        assert fut.done(), "审批回调应在共享 gate 上 respond,放行 loop 的 await"
        assert fut.result().approved is True
