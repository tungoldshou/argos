from __future__ import annotations

import pytest

from argos.approval import ApprovalLevel
from argos.core.types import Verdict
from argos.tui.app import ArgosApp
from argos.tui.events import MemoryRecallEvent, PhaseChange, TokenDelta, VerifyVerdict
from argos.tui.fakeloop import FakeLoop, FailingFakeLoop
from argos.tui.widgets.code_action import CodeActionBlock
from argos.tui.widgets.diff_view import DiffView
from argos.tui.widgets.status_bar import StatusBar
from argos.tui.widgets.verdict_badge import VerdictBadge


class _RaisingLoop:

    async def run(self, goal, session_id):
        yield PhaseChange(phase="act", actions=1)
        yield TokenDelta(text="干活中...\n")
        raise RuntimeError("模型 502 / sandbox 崩了")


@pytest.mark.asyncio
async def test_app_boots_with_status_bar_and_transcript():
    app = ArgosApp(loop_factory=lambda **kw: FakeLoop())
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.query_one("#transcript") is not None
        assert app.query_one("#status-bar", StatusBar) is not None
        assert "Argos" in app.title


@pytest.mark.asyncio
async def test_run_goal_drives_widgets_from_events():
    app = ArgosApp(loop_factory=lambda **kw: FakeLoop())
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
        assert bar.phase == "idle"
        assert "$" not in bar.render_text and "12.4k" not in bar.render_text


@pytest.mark.asyncio
async def test_failing_run_shows_escalation_and_failed_verdict():
    app = ArgosApp(loop_factory=lambda **kw: FailingFakeLoop())
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.start_run("会失败的任务")
        await app.workers.wait_for_complete()
        await pilot.pause()
        badge = app.query_one(VerdictBadge)
        assert badge.status == "failed"
        log = app.query_one("#transcript")
        assert "无法自行收敛" in log.rendered_text or "诚实上报" in log.rendered_text


@pytest.mark.asyncio
async def test_slash_yolo_switches_level_and_shows_red_badge():
    app = ArgosApp(loop_factory=lambda **kw: FakeLoop())
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
    app = ArgosApp(loop_factory=lambda **kw: FakeLoop())
    async with app.run_test() as pilot:
        await pilot.pause()
        app.handle_input("/status")
        app.handle_input("/cost")
        await pilot.pause()
        log = app.query_one("#transcript")
        assert "idle" in log.rendered_text and "动作" in log.rendered_text
        assert "成本" in log.rendered_text or "$" in log.rendered_text


@pytest.mark.asyncio
async def test_unknown_slash_is_reported_not_run_as_goal():
    app = ArgosApp(loop_factory=lambda **kw: FakeLoop())
    async with app.run_test() as pilot:
        await pilot.pause()
        app.handle_input("/frobnicate")
        await pilot.pause()
        log = app.query_one("#transcript")
        assert "未知命令" in log.rendered_text




@pytest.mark.asyncio
async def test_loop_exception_degrades_to_error_not_crash():
    app = ArgosApp(loop_factory=lambda **kw: _RaisingLoop())
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.start_run("会抛异常的任务")
        await app.workers.wait_for_complete()
        await pilot.pause()
        log = app.query_one("#transcript")
        assert "◉ 错误" in log.rendered_text
        assert "模型 502" in log.rendered_text
        assert "RuntimeError" in log.rendered_text


@pytest.mark.asyncio
async def test_input_focused_on_mount_and_receives_typing():
    from argos.tui.widgets.prompt import PromptArea

    app = ArgosApp(loop_factory=lambda **kw: FakeLoop())
    async with app.run_test() as pilot:
        await pilot.pause()
        prompt = app.query_one("#prompt", PromptArea)
        assert app.focused is prompt, "启动后焦点必须在输入框(#prompt)"
        await pilot.press("h", "i")
        await pilot.pause()
        assert prompt.text == "hi", "聚焦的输入框应接收按键"


@pytest.mark.asyncio
async def test_input_accepts_cjk_characters():
    from argos.tui.widgets.prompt import PromptArea

    app = ArgosApp(loop_factory=lambda **kw: FakeLoop())
    async with app.run_test() as pilot:
        await pilot.pause()
        prompt = app.query_one("#prompt", PromptArea)
        for ch in "修个bug":
            await pilot.press(ch)
        await pilot.pause()
        assert prompt.text == "修个bug", "输入框应接收汉字 + ASCII 混排"




@pytest.mark.asyncio
async def test_transcript_fills_main_area_not_collapsed():
    app = ArgosApp(loop_factory=lambda **kw: FakeLoop())
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        t = app.query_one("#transcript")
        c = app.query_one("#activity")
        assert t.size.width >= 40, f"transcript 宽度被压塌={t.size.width},对话会隐形"
        assert t.size.height >= 10, f"transcript 高度不足={t.size.height}"
        assert t.size.width > c.size.width, "transcript 是主区,应比活动侧栏宽"


@pytest.mark.asyncio
async def test_pageup_scrolls_transcript_while_prompt_focused():
    from argos.tui.widgets.prompt import PromptArea
    from argos.tui.widgets.transcript import Transcript

    app = ArgosApp(loop_factory=lambda **kw: FakeLoop())
    async with app.run_test(size=(100, 20)) as pilot:
        await pilot.pause()
        prompt = app.query_one("#prompt", PromptArea)
        log = app.query_one("#transcript", Transcript)
        assert prompt.has_focus

        for i in range(80):
            await log.append_line(f"line {i}")
        await pilot.pause()

        bottom = log.scroll_y
        assert bottom > 0
        await pilot.press("pageup")
        await pilot.pause()

        assert log.scroll_y < bottom


@pytest.mark.asyncio
async def test_mouse_wheel_scrolls_transcript_when_event_reaches_app():
    from textual import events

    from argos.tui.widgets.transcript import Transcript

    app = ArgosApp(loop_factory=lambda **kw: FakeLoop())
    async with app.run_test(size=(100, 20)) as pilot:
        await pilot.pause()
        log = app.query_one("#transcript", Transcript)
        for i in range(80):
            await log.append_line(f"line {i}")
        await pilot.pause()

        bottom = log.scroll_y
        assert bottom > 0
        event = events.MouseScrollUp(
            app, 1, 1, 0, -1, 0,
            shift=False, meta=False, ctrl=False,
        )
        app._on_mouse_scroll_up(event)
        await pilot.pause()

        assert event._stop_propagation
        assert log.scroll_y < bottom


@pytest.mark.asyncio
async def test_transcript_can_take_focus_for_history_review():
    from argos.tui.widgets.prompt import PromptArea
    from argos.tui.widgets.transcript import Transcript

    app = ArgosApp(loop_factory=lambda **kw: FakeLoop())
    async with app.run_test(size=(100, 20)) as pilot:
        await pilot.pause()
        prompt = app.query_one("#prompt", PromptArea)
        log = app.query_one("#transcript", Transcript)
        assert app.focused is prompt

        await pilot.mouse_down(log)
        await pilot.mouse_up(log)
        await pilot.pause()

        assert app.focused is log


def test_kitty_keyboard_protocol_disabled_by_default():
    import importlib
    import os

    import argos.tui

    saved = os.environ.pop("TEXTUAL_DISABLE_KITTY_KEY", None)
    try:
        importlib.reload(argos.tui)
        assert os.environ.get("TEXTUAL_DISABLE_KITTY_KEY") == "1"
    finally:
        if saved is not None:
            os.environ["TEXTUAL_DISABLE_KITTY_KEY"] = saved
        else:
            os.environ.setdefault("TEXTUAL_DISABLE_KITTY_KEY", "1")


def test_kitty_disable_respects_explicit_user_optin():
    import importlib
    import os

    import argos.tui

    os.environ["TEXTUAL_DISABLE_KITTY_KEY"] = "0"
    try:
        importlib.reload(argos.tui)
        assert os.environ.get("TEXTUAL_DISABLE_KITTY_KEY") == "0", "显式用户值必须被尊重"
    finally:
        os.environ["TEXTUAL_DISABLE_KITTY_KEY"] = "1"


@pytest.mark.asyncio
async def test_user_goal_echoed_to_transcript():
    app = ArgosApp(loop_factory=lambda **kw: FakeLoop())
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.start_run("修个 off-by-one")
        await app.workers.wait_for_complete()
        await pilot.pause()
        log = app.query_one("#transcript")
        assert "› 修个 off-by-one" in log.rendered_text, "用户目标必须回显进对话流(› 行)"


class _LoopWithStore:
    def __init__(self, store):
        self.store = store
    async def run(self, goal, session_id):
        if False:
            yield None


@pytest.mark.asyncio
async def test_resume_switches_to_most_recent_session(tmp_path):
    from argos.memory.store import ArgosStore
    from argos.tui.widgets.transcript import Transcript

    store = ArgosStore(db_path=str(tmp_path / "r.db"))
    store.ensure_session("old-sess", title="贪吃蛇")
    store.append_message("old-sess", role="user", content="做个贪吃蛇")
    store.append_message("old-sess", role="assistant", content="好的,做完了")

    app = ArgosApp(loop_factory=lambda **kw: _LoopWithStore(store))
    async with app.run_test() as pilot:
        await pilot.pause()
        before = app._session_id
        log = app.query_one("#transcript", Transcript)
        await app._resume_recent(log)
        await pilot.pause()
        assert app._session_id == "old-sess", "/resume 应把会话切到最近一次历史会话"
        assert app._session_id != before
        assert "已恢复" in log.rendered_text and "2 条历史" in log.rendered_text
    store.close()


@pytest.mark.asyncio
async def test_resume_honest_when_no_history(tmp_path):
    from argos.memory.store import ArgosStore
    from argos.tui.widgets.transcript import Transcript

    store = ArgosStore(db_path=str(tmp_path / "empty.db"))
    app = ArgosApp(loop_factory=lambda **kw: _LoopWithStore(store))
    async with app.run_test() as pilot:
        await pilot.pause()
        log = app.query_one("#transcript", Transcript)
        await app._resume_recent(log)
        await pilot.pause()
        assert "没有可恢复" in log.rendered_text
    store.close()




@pytest.mark.asyncio
async def test_compacted_event_writes_transcript_line_and_panel():
    from argos.tui.events import CompactedEvent
    script = [
        PhaseChange(phase="act", actions=1),
        CompactedEvent(before=12, after=4, reduction_pct=0.22, triggered_by="proactive"),
    ]
    app = ArgosApp(loop_factory=lambda **kw: FakeLoop(script=script))
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.start_run("压缩任务")
        await app.workers.wait_for_complete()
        await pilot.pause()
        text = app.query_one("#transcript").rendered_text
        assert "压缩" in text and "-22%" in text and "12→4" in text


@pytest.mark.asyncio
async def test_pruned_event_writes_transcript_line():
    from argos.tui.events import PrunedEvent
    script = [
        PhaseChange(phase="act", actions=1),
        PrunedEvent(before=80, after=60, removed=5, reduction_pct=0.25, aggressiveness=0.5),
    ]
    app = ArgosApp(loop_factory=lambda **kw: FakeLoop(script=script))
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.start_run("修剪任务")
        await app.workers.wait_for_complete()
        await pilot.pause()
        text = app.query_one("#transcript").rendered_text
        assert "修剪" in text and "5 条" in text


@pytest.mark.asyncio
async def test_status_bar_blocked_on_approval_card_then_cleared():
    from argos.tui.events import ApprovalRequest
    from argos.tui.widgets.inline_choice import InlineChoice
    script = [
        PhaseChange(phase="verify", actions=2),
        ApprovalRequest(
            call_id="c1", action="run_command", args={"cmd": "git push"},
            description="soft rule: ask git push", risk="medium", trigger="soft rule",
        ),
    ]
    app = ArgosApp(loop_factory=lambda **kw: FakeLoop(script=script))
    async with app.run_test() as pilot:
        await pilot.pause()
        app.run_worker(app.start_run("要审批的任务"), exclusive=False)
        for _ in range(40):
            await pilot.pause()
            if list(app.query(InlineChoice)):
                break
        bar = app.query_one("#status-bar", StatusBar)
        assert bar._blocked is True, "审批卡活动时 StatusBar 应进 blocked 态"
        assert bar.render_text.startswith("◓"), "用户阻塞态左眼应为 ◓(优先级最高)"
        assert "审批挂起" in bar.render_text
        choice = list(app.query(InlineChoice))[0]
        choice._finish("deny", "")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert bar._blocked is False, "决策落定后 StatusBar 应解除 blocked 态"


@pytest.mark.asyncio
async def test_status_bar_alert_locked_on_failed_verdict_not_overwritten_by_report():
    script = [
        PhaseChange(phase="verify", actions=2),
        VerifyVerdict(verdict=Verdict.failed(detail="1 failed", verify_cmd="pytest", attempts=3)),
        PhaseChange(phase="report", actions=2),
        TokenDelta(text="诚实上报失败。\n"),
    ]
    app = ArgosApp(loop_factory=lambda **kw: FakeLoop(script=script))
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.start_run("会失败的验证")
        await app.workers.wait_for_complete()
        await pilot.pause()
        bar = app.query_one("#status-bar", StatusBar)
        assert app._terminal_glow is True, "failed verdict 应锁定 _terminal_glow"
        assert bar._alert is True, "陷阱2:report 阶段后告警锁色不得被清(StatusBar -alert 仍在)"
        assert bar.has_class("-alert"), "告警态 CSS 类 -alert 应在"


@pytest.mark.asyncio
async def test_status_bar_alert_cleared_on_new_run():
    fail_script = [
        VerifyVerdict(verdict=Verdict.failed(detail="x", verify_cmd="pytest", attempts=1)),
    ]
    ok_script = [
        PhaseChange(phase="plan", actions=0),
        VerifyVerdict(verdict=Verdict.passed(detail="ok", verify_cmd="pytest", attempts=1)),
    ]
    scripts = iter([fail_script, ok_script])
    app = ArgosApp(loop_factory=lambda **kw: FakeLoop(script=next(scripts)))
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.start_run("第一轮失败")
        await app.workers.wait_for_complete()
        await pilot.pause()
        bar = app.query_one("#status-bar", StatusBar)
        assert bar._alert is True
        await app.start_run("第二轮成功")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app._terminal_glow is False, "新 run 应解锁告警"
        assert bar._alert is False, "新 run 后 StatusBar -alert 应清"


@pytest.mark.asyncio
async def test_memory_recall_line_shown_with_real_store_hits(tmp_path):
    class _LoopWithRecallEvent:
        async def run(self, goal, session_id):
            yield MemoryRecallEvent(hits=["上次也改过 auth → passed（similar goal）"])
            yield PhaseChange(phase="plan", actions=0)

    app = ArgosApp(loop_factory=lambda **kw: _LoopWithRecallEvent())
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.start_run("改 auth.py")
        await app.workers.wait_for_complete()
        await pilot.pause()
        text = app.query_one("#transcript").rendered_text
        assert "记忆召回 1 条" in text, "真召回到 1 条应如实显示"


@pytest.mark.asyncio
async def test_memory_recall_silent_when_no_store():
    app = ArgosApp(loop_factory=lambda **kw: FakeLoop())
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.start_run("普通任务")
        await app.workers.wait_for_complete()
        await pilot.pause()
        text = app.query_one("#transcript").rendered_text
        assert "记忆召回" not in text, "无 store 不得谎报召回"




@pytest.mark.asyncio
async def test_apply_event_phase_change_drives_activity_panel_view():
    from argos.tui.widgets.activity_panel import ActivityPanel

    app = ArgosApp(loop_factory=lambda **kw: FakeLoop())
    async with app.run_test() as pilot:
        await pilot.pause()
        ap = app.query_one("#activity", ActivityPanel)
        assert ap._view == "idle", "初始视图应为 idle"

        await app._apply_event(PhaseChange(phase="act", actions=1))
        await pilot.pause()
        assert ap._view == "act", (
            "_apply_event(PhaseChange(act)) 应把 ap._view 切到 'act';"
            " 若仍为 idle 说明 app._apply_event → ap.on_phase 接线断了"
        )

        await app._apply_event(PhaseChange(phase="verify", actions=2))
        await pilot.pause()
        assert ap._view == "verify", "_apply_event(PhaseChange(verify)) 应把视图切到 'verify'"

        assert ap._view != "idle", "未调 on_run_end,视图不应回退到 idle"
