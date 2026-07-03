import pytest

from argos.approval import ApprovalGate, ApprovalLevel
from argos.tui.app import ArgosApp
from argos.tui.events import WorkflowDone, WorkflowProgress, WorkflowProposed
from argos.tui.fakeloop import FakeLoop
from argos.tui.widgets.workflow_panel import WorkflowPanel


@pytest.mark.asyncio
async def test_workflow_events_render_progress_and_summary():
    app = ArgosApp(loop_factory=lambda **kw: FakeLoop(), gate=ApprovalGate(ApprovalLevel.AUTO))
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await app._apply_event(WorkflowProposed(name="audit", description="审计",
            preview="将起 2 个 agent [review]", call_id="c1"))
        await app._apply_event(WorkflowProgress(stage_id="r", agent_id="r#0", phase="act", note=""))
        await app._apply_event(WorkflowProgress(stage_id="r", agent_id="r#1", phase="done", note="[ok]"))
        await app._apply_event(WorkflowDone(name="audit", synthesis="结论:list[str] 无问题", notes=()))
        await pilot.pause()
        assert app.is_running
        panels = list(app.query(WorkflowPanel))
        assert panels, "应 mount 工作流进度面板"
        log = app.query_one("#transcript")
        assert "audit" in log.rendered_text


@pytest.mark.asyncio
async def test_workflow_proposed_pushes_modal_under_confirm():
    app = ArgosApp(loop_factory=lambda **kw: FakeLoop(), gate=ApprovalGate(ApprovalLevel.CONFIRM))
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await app._apply_event(WorkflowProposed(name="x", description="d",
            preview="预览内容 [VOTE]", call_id="c2"))
        await pilot.pause()
        from argos.tui.widgets.inline_choice import InlineChoice
        choices = list(app.query(InlineChoice))
        assert choices, "CONFIRM 档应在流内渲染工作流审批 InlineChoice"
        body = str(choices[0].query_one("#ic-body").render())
        assert "预览内容 [VOTE]" in body


@pytest.mark.asyncio
async def test_workflow_panel_marks_error_phase_honestly():
    app = ArgosApp(loop_factory=lambda **kw: FakeLoop(), gate=ApprovalGate(ApprovalLevel.AUTO))
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await app._apply_event(WorkflowProposed(name="w", description="d",
            preview="p", call_id="c3"))
        await app._apply_event(WorkflowProgress(stage_id="s", agent_id="s#0",
            phase="error", note="boom [trace]"))
        await pilot.pause()
        assert app.is_running
        panel = app.query_one(WorkflowPanel)
        assert panel._render_markup is False
        text = panel.rendered_text
        assert "s#0" in text
        assert "失败" in text


@pytest.mark.asyncio
async def test_workflow_confirm_callback_responds_on_shared_gate():
    gate = ApprovalGate(ApprovalLevel.CONFIRM)
    app = ArgosApp(loop_factory=lambda **kw: FakeLoop(), gate=gate)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        import asyncio
        loop = asyncio.get_running_loop()
        from argos.approval import _Pending
        fut: asyncio.Future = loop.create_future()
        gate._pending["c4"] = _Pending(call_id="c4",
            payload={"action": "run_workflow", "args": {}},
            created_at=0.0, future=fut, loop=loop)
        await app._apply_event(WorkflowProposed(name="x", description="d",
            preview="预览", call_id="c4"))
        await pilot.pause()
        await pilot.press("2")
        await pilot.pause()
        assert fut.done(), "审批回调应在共享 gate 上 respond,放行 loop 的 await"
        assert fut.result().approved is True
