from argos_agent.tui import glow


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


import pytest
from argos_agent.tui.app import ArgosApp
from argos_agent.tui.fakeloop import FakeLoop


@pytest.mark.asyncio
async def test_border_idle_then_runs_then_resets():
    app = ArgosApp(loop_factory=lambda: FakeLoop())
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        # idle:中性灰
        assert tuple(app.screen.styles.border_top[1].rgb) == glow.IDLE_BORDER.rgb
        await app.start_run("演示")
        await app.workers.wait_for_complete()
        await pilot.pause()
        # 跑完 finally 复位灰
        assert tuple(app.screen.styles.border_top[1].rgb) == glow.IDLE_BORDER.rgb
