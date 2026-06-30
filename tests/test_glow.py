from argos.tui import glow


def test_phase_colors_distinct():
    cs = {glow.phase_color(p) for p in ("plan", "act", "verify", "report")}
    assert len(cs) == 4, "四阶段颜色应各不相同"


def test_verdict_colors_map_to_semantic():
    assert glow.verdict_color("failed") == glow.ERROR
    assert glow.verdict_color("unverifiable") == glow.WARNING
    assert glow.verdict_color("passed") == glow.SUCCESS


def test_idle_is_neutral_not_rainbow():
    assert glow.IDLE_BORDER == glow.IDLE_BORDER  # 中性灰常量存在
    # 诚实:idle 不是任何阶段色
    assert glow.IDLE_BORDER not in {glow.phase_color(p) for p in ("plan", "act", "verify", "report")}


def test_breathe_color_dims_and_restores():
    base = glow.phase_color("act")
    dim = glow.breathe(base, 0.0)   # 谷(cos(0)=1 → k=0.55,最暗)
    bright = glow.breathe(base, 0.5)  # 峰(cos(π)=-1 → k=1.0,基色满亮)
    assert tuple(dim.rgb) != tuple(bright.rgb), "呼吸应在亮↔暗间变化"


import pytest
from argos.tui.app import ArgosApp
from argos.tui.fakeloop import FakeLoop


@pytest.mark.asyncio
async def test_border_idle_then_runs_then_resets():
    app = ArgosApp(loop_factory=lambda **kw: FakeLoop())
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        # idle:中性灰
        assert tuple(app.screen.styles.border_top[1].rgb) == glow.IDLE_BORDER.rgb
        await app.start_run("演示")
        await app.workers.wait_for_complete()
        await pilot.pause()
        # 跑完 finally 复位灰
        assert tuple(app.screen.styles.border_top[1].rgb) == glow.IDLE_BORDER.rgb


@pytest.mark.asyncio
async def test_terminal_verdict_glow_survives_report_phase():
    """诚实(终态优先):failed/unverifiable 告警色锁定后,后续 report 阶段色不得覆盖。
    否则 verify(failed)→report 会把告警红抹成中性灰,视觉上'降级'了真实失败。"""
    from argos.core.verify_gate import Verdict
    from argos.tui.events import PhaseChange, VerifyVerdict

    app = ArgosApp(loop_factory=lambda **kw: FakeLoop())
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        app._glow_start()  # 模拟一轮开始(解锁 + plan 色)
        await app._apply_event(VerifyVerdict(
            verdict=Verdict.failed(detail="断言不符", verify_cmd="pytest", attempts=1)))
        await app._apply_event(PhaseChange(phase="report", actions=2))
        await pilot.pause()
        assert tuple(app.screen.styles.border_top[1].rgb) == glow.ERROR.rgb, \
            "失败告警红必须挺过 report 阶段(终态色优先于阶段色)"


@pytest.mark.asyncio
async def test_passed_verdict_glow_does_not_lock():
    """passed 不锁:passed→report 允许 report 阶段色接管(passed 是好事,不需持续告警)。"""
    from argos.core.verify_gate import Verdict
    from argos.tui.events import PhaseChange, VerifyVerdict

    app = ArgosApp(loop_factory=lambda **kw: FakeLoop())
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        app._glow_start()
        await app._apply_event(VerifyVerdict(
            verdict=Verdict.passed(detail="ok", verify_cmd="pytest", attempts=1)))
        await app._apply_event(PhaseChange(phase="report", actions=2))
        # 停呼吸计时器:_glow_start 启动一个每 0.1s 改边框色的 set_interval 定时器。
        # 若 pilot.pause() 耗时超 0.1s(并行高负载下可能),定时器会把 report 阶段色
        # "呼吸"成略暗的变体,导致颜色比较失败(虚假失败,非逻辑 bug)。
        # 停计时器后再断言:被测行为是"passed 不锁定 → report 接管",与计时器无关。
        if app._glow_timer is not None:
            app._glow_timer.stop()
            app._glow_timer = None
        await pilot.pause()
        assert tuple(app.screen.styles.border_top[1].rgb) == glow.phase_color("report").rgb, \
            "passed 不锁定,report 阶段色应接管"
