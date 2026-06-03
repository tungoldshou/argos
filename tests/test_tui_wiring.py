"""Phase 5 端到端接线:FakeLoop 投全套 Event → 各 widget 出现/更新(Pilot)。
覆盖契约不变量:UI 看到的 = 事件源(一份事件三用的 UI 出口)。"""
from __future__ import annotations

import pytest

from argos_agent.approval import ApprovalLevel
from argos_agent.tui.app import ArgosApp
from argos_agent.tui.fakeloop import FakeLoop, FailingFakeLoop
from argos_agent.tui.widgets.code_action import CodeActionBlock
from argos_agent.tui.widgets.diff_view import DiffView
from argos_agent.tui.widgets.status_bar import StatusBar
from argos_agent.tui.widgets.verdict_badge import VerdictBadge


@pytest.mark.asyncio
async def test_app_boots_with_status_bar_and_transcript():
    app = ArgosApp(loop_factory=lambda: FakeLoop())
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.query_one("#transcript") is not None
        assert app.query_one("#status-bar", StatusBar) is not None
        assert "Argos" in app.title


@pytest.mark.asyncio
async def test_run_goal_drives_widgets_from_events():
    app = ArgosApp(loop_factory=lambda: FakeLoop())
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.start_run("修个 bug")
        await app.workers.wait_for_complete()
        await pilot.pause()
        blocks = list(app.query(CodeActionBlock))
        assert len(blocks) >= 1
        assert blocks[0].ok is True
        diffs = list(app.query(DiffView))
        assert any(d.path == "a.py" and d.added == 2 for d in diffs)
        badge = app.query_one(VerdictBadge)
        assert badge.status == "passed"
        bar = app.query_one("#status-bar", StatusBar)
        assert bar.phase == "report"
        assert "$0.013" in bar.render_text
        assert "12.4k" in bar.render_text


@pytest.mark.asyncio
async def test_failing_run_shows_escalation_and_failed_verdict():
    app = ArgosApp(loop_factory=lambda: FailingFakeLoop())
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.start_run("会失败的任务")
        await app.workers.wait_for_complete()
        await pilot.pause()
        badge = app.query_one(VerdictBadge)
        assert badge.status == "failed"
        log = app.query_one("#transcript")
        assert "无法自行收敛" in log._flushed or "诚实上报" in log._flushed


@pytest.mark.asyncio
async def test_slash_yolo_switches_level_and_shows_red_badge():
    app = ArgosApp(loop_factory=lambda: FakeLoop())
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.gate.level is ApprovalLevel.CONFIRM
        assert "YOLO" not in app.sub_title
        app.handle_input("/yolo")
        await pilot.pause()
        assert app.gate.level is ApprovalLevel.AUTO
        assert "YOLO" in app.sub_title


@pytest.mark.asyncio
async def test_slash_status_and_cost_write_to_transcript():
    app = ArgosApp(loop_factory=lambda: FakeLoop())
    async with app.run_test() as pilot:
        await pilot.pause()
        app.handle_input("/status")
        app.handle_input("/cost")
        await pilot.pause()
        log = app.query_one("#transcript")
        assert "phase:" in log._flushed
        assert "成本" in log._flushed or "$" in log._flushed


@pytest.mark.asyncio
async def test_unknown_slash_is_reported_not_run_as_goal():
    app = ArgosApp(loop_factory=lambda: FakeLoop())
    async with app.run_test() as pilot:
        await pilot.pause()
        app.handle_input("/frobnicate")
        await pilot.pause()
        log = app.query_one("#transcript")
        assert "未知命令" in log._flushed
