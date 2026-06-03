"""Phase 5 端到端接线:FakeLoop 投全套 Event → 各 widget 出现/更新(Pilot)。
覆盖契约不变量:UI 看到的 = 事件源(一份事件三用的 UI 出口)。"""
from __future__ import annotations

import pytest

from argos_agent.approval import ApprovalLevel
from argos_agent.tui.app import ArgosApp
from argos_agent.tui.events import PhaseChange, TokenDelta
from argos_agent.tui.fakeloop import FakeLoop, FailingFakeLoop
from argos_agent.tui.widgets.code_action import CodeActionBlock
from argos_agent.tui.widgets.diff_view import DiffView
from argos_agent.tui.widgets.status_bar import StatusBar
from argos_agent.tui.widgets.verdict_badge import VerdictBadge


class _RaisingLoop:
    """yield 一个事件后抛异常 —— 验证 _produce 把异常降级成 Error 事件而非击穿 TUI(final review HIGH)。"""

    async def run(self, goal, session_id):
        yield PhaseChange(phase="act", actions=1)
        yield TokenDelta(text="干活中...\n")
        raise RuntimeError("模型 502 / sandbox 崩了")


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


# ── final review 回归:两个 HIGH ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_loop_exception_degrades_to_error_not_crash():
    """HIGH:loop.run 抛异常时,_produce 捕获并降级为 Error 事件,TUI 不崩溃(诚实上报而非 PANIC)。"""
    app = ArgosApp(loop_factory=lambda: _RaisingLoop())
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.start_run("会抛异常的任务")
        await app.workers.wait_for_complete()
        await pilot.pause()
        log = app.query_one("#transcript")
        # 异常被容纳成 ❌ 错误 行(含异常链),而非 WorkerFailed 击穿 app。
        assert "❌ 错误" in log._flushed
        assert "模型 502" in log._flushed
        assert "RuntimeError" in log._flushed


@pytest.mark.asyncio
async def test_demo_mode_marks_subtitle_and_warns_before_run():
    """HIGH:默认 demo 模式头部常驻 DEMO 标识,且每轮起手 banner 声明假数据(诚实)。"""
    app = ArgosApp(loop_factory=lambda: FakeLoop())  # demo 默认 True
    async with app.run_test() as pilot:
        await pilot.pause()
        assert "DEMO" in app.sub_title
        await app.start_run("演示任务")
        await app.workers.wait_for_complete()
        await pilot.pause()
        log = app.query_one("#transcript")
        assert "演示模式" in log._flushed


@pytest.mark.asyncio
async def test_real_loop_has_no_demo_marker():
    """注入真 loop(demo=False)时,DEMO 标识消失 —— 标识与真实状态一致,不撒谎。"""
    app = ArgosApp(loop_factory=lambda: FakeLoop(), demo=False)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert "DEMO" not in app.sub_title
