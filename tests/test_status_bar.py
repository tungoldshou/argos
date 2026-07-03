# tests/test_status_bar.py
import pytest
from textual.app import App, ComposeResult

from argos.tui.theme import ARGOS_NIGHT
from argos.tui.widgets.status_bar import StatusBar


class _H(App):

    def get_theme_variable_defaults(self) -> dict[str, str]:
        defaults = super().get_theme_variable_defaults()
        if ARGOS_NIGHT.variables:
            defaults.update(ARGOS_NIGHT.variables)
        return defaults

    def compose(self) -> ComposeResult:
        yield StatusBar(id="sb")


@pytest.mark.asyncio
async def test_status_bar_shows_phase_and_actions():
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        sb = app.query_one("#sb", StatusBar)
        sb.set_phase("verify", 3)
        sb.set_cost(tokens_in=1, tokens_out=2, cost_usd=0.0, elapsed_s=4.2)
        await pilot.pause()
        t = sb.render_text
        assert "verify" in t and "3" in t
        assert "4.2" not in t and "$" not in t


@pytest.mark.asyncio
async def test_phase_eye_plan():
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        sb = app.query_one("#sb", StatusBar)
        sb.set_phase("plan", 0)
        await pilot.pause()
        assert sb.render_text.startswith("◔"), f"期望 ◔ 开头，实际：{sb.render_text!r}"


@pytest.mark.asyncio
async def test_phase_eye_act():
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        sb = app.query_one("#sb", StatusBar)
        sb.set_phase("act", 2)
        await pilot.pause()
        assert sb.render_text.startswith("◉"), f"期望 ◉ 开头，实际：{sb.render_text!r}"


@pytest.mark.asyncio
async def test_phase_eye_verify():
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        sb = app.query_one("#sb", StatusBar)
        sb.set_phase("verify", 5)
        await pilot.pause()
        assert sb.render_text.startswith("❂"), f"期望 ❂ 开头，实际：{sb.render_text!r}"


@pytest.mark.asyncio
async def test_phase_eye_report():
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        sb = app.query_one("#sb", StatusBar)
        sb.set_phase("report", 1)
        await pilot.pause()
        assert sb.render_text.startswith("◕"), f"期望 ◕ 开头，实际：{sb.render_text!r}"


@pytest.mark.asyncio
async def test_phase_eye_idle():
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        sb = app.query_one("#sb", StatusBar)
        await pilot.pause()
        assert sb.render_text.startswith("◌"), f"期望 ◌ 开头，实际：{sb.render_text!r}"


@pytest.mark.asyncio
async def test_set_blocked_overrides_verify_phase():
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        sb = app.query_one("#sb", StatusBar)
        sb.set_phase("verify", 5)
        sb.set_blocked(True)
        await pilot.pause()
        t = sb.render_text
        assert t.startswith("◓"), f"blocked 时期望 ◓ 开头，实际：{t!r}"
        assert "审批挂起" in t, f"blocked 时期望含'审批挂起'，实际：{t!r}"


@pytest.mark.asyncio
async def test_set_blocked_false_restores_phase():
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        sb = app.query_one("#sb", StatusBar)
        sb.set_phase("act", 2)
        sb.set_blocked(True)
        sb.set_blocked(False)
        await pilot.pause()
        t = sb.render_text
        assert t.startswith("◉"), f"blocked=False 后期望 ◉ 开头，实际：{t!r}"


@pytest.mark.asyncio
async def test_set_alert_adds_css_class():
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        sb = app.query_one("#sb", StatusBar)
        sb.set_phase("verify", 5)
        sb.set_alert(True)
        await pilot.pause()
        assert sb.has_class("-alert"), "set_alert(True) 后期望 CSS 类 -alert"


@pytest.mark.asyncio
async def test_set_alert_false_removes_css_class():
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        sb = app.query_one("#sb", StatusBar)
        sb.set_alert(True)
        sb.set_alert(False)
        await pilot.pause()
        assert not sb.has_class("-alert"), "set_alert(False) 后期望无 -alert 类"


@pytest.mark.asyncio
async def test_alert_does_not_override_phase_eye_glyph():
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        sb = app.query_one("#sb", StatusBar)
        sb.set_phase("act", 3)
        sb.set_alert(True)
        await pilot.pause()
        t = sb.render_text
        assert t.startswith("◉"), f"alert 时阶段眼应保持 ◉，实际：{t!r}"


@pytest.mark.asyncio
async def test_blocked_beats_alert():
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        sb = app.query_one("#sb", StatusBar)
        sb.set_phase("verify", 5)
        sb.set_alert(True)
        sb.set_blocked(True)
        await pilot.pause()
        t = sb.render_text
        assert t.startswith("◓"), f"blocked+alert 时期望 ◓ 优先，实际：{t!r}"


@pytest.mark.asyncio
async def test_ctx_warn_at_80_percent():
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        sb = app.query_one("#sb", StatusBar)
        sb.update_ctx_pressure(0.80)
        await pilot.pause()
        assert sb.has_class("-ctx-warn"), "ctx=80% 期望 -ctx-warn"
        assert not sb.has_class("-ctx-crit"), "ctx=80% 不应有 -ctx-crit"


@pytest.mark.asyncio
async def test_ctx_crit_at_95_percent():
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        sb = app.query_one("#sb", StatusBar)
        sb.update_ctx_pressure(0.95)
        await pilot.pause()
        assert sb.has_class("-ctx-crit"), "ctx=95% 期望 -ctx-crit"


@pytest.mark.asyncio
async def test_ctx_below_80_no_warn():
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        sb = app.query_one("#sb", StatusBar)
        sb.update_ctx_pressure(0.5)
        await pilot.pause()
        assert not sb.has_class("-ctx-warn"), "ctx=50% 不应有 -ctx-warn"
        assert not sb.has_class("-ctx-crit"), "ctx=50% 不应有 -ctx-crit"




@pytest.mark.asyncio
async def test_action_count_label():
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        sb = app.query_one("#sb", StatusBar)
        sb.set_phase("act", 7)
        await pilot.pause()
        t = sb.render_text
        assert "动作7" in t, f"期望'动作7'，实际：{t!r}"
        assert "⚙" not in t, f"⚙ 是处决字形，不应出现：{t!r}"


def test_action_label_en_has_space():
    from argos.locales.tui_app import EN
    assert EN["tui.statusbar.action"].format(n=0) == "action 0"
    assert EN["tui.statusbar.action"].format(n=7) == "action 7"


def test_public_api_set_blocked_exists():
    import inspect
    sig = inspect.signature(StatusBar.set_blocked)
    params = list(sig.parameters)
    assert "active" in params, f"set_blocked 缺 active 参数，实际：{params}"


def test_public_api_set_alert_exists():
    import inspect
    assert hasattr(StatusBar, "set_alert"), "StatusBar 缺 set_alert 公开方法"
    sig = inspect.signature(StatusBar.set_alert)
    params = list(sig.parameters)
    assert len(params) >= 2, f"set_alert 签名参数不足，实际：{params}"


@pytest.mark.asyncio
async def test_blocked_eye_glyph_color_is_gold_not_orange():
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        sb = app.query_one("#sb", StatusBar)
        sb.set_phase("verify", 5)
        sb.set_blocked(True)
        await pilot.pause()

        rt = sb.render()
        plain = rt.plain
        assert plain.startswith("◓"), f"blocked 时期望 ◓ 开头，实际：{plain!r}"

        from argos.tui.widgets.status_bar import _STYLE_EYE, _STYLE_BLOCKED

        import inspect
        render_src = inspect.getsource(sb.render)
        assert "_STYLE_EYE" in render_src, "render() 应使用 _STYLE_EYE 给眼着色"
        assert "eye_style = _STYLE_EYE" in render_src, "eye_style 应恒为 _STYLE_EYE"
        assert "if self._blocked" not in render_src.split("eye_style = _STYLE_EYE")[0].split('\n')[-1],\
            "eye_style = _STYLE_EYE 之前不应有 if self._blocked 分支"


def test_mark_run_end_resets_phase_to_idle():
    from argos.tui.widgets.status_bar import StatusBar
    bar = StatusBar()
    bar.set_phase("report", 5)
    assert bar.phase == "report"
    bar.mark_run_end()
    assert bar.phase == "idle", "run 收尾 phase 应复位 idle"
    assert bar.actions == 0


# ── Task 2.4: step budget N/M ─────────────────────────────────────────────────

def test_status_bar_action_with_max_steps():
    """set_phase with max_steps → render_text shows 'action N/M' format."""
    from argos.tui.widgets.status_bar import StatusBar
    bar = StatusBar()
    bar.set_phase("act", 7, max_steps=40)
    text = bar.render_text
    assert "7/40" in text, f"期望 '7/40' 在 render_text 中，实际：{text!r}"


def test_status_bar_action_without_max_steps():
    """set_phase without max_steps → render_text shows 'action N' (no '/None')."""
    from argos.tui.widgets.status_bar import StatusBar
    bar = StatusBar()
    bar.set_phase("act", 7)
    text = bar.render_text
    assert "7" in text, f"期望 '7' 在 render_text 中，实际：{text!r}"
    assert "/None" not in text, f"不应出现 '/None'，实际：{text!r}"
    assert "7/40" not in text


def test_phase_change_max_steps_field_defaults_none():
    """PhaseChange.max_steps defaults to None — existing call sites stay unbroken."""
    from argos.protocol.events import PhaseChange
    ev = PhaseChange(phase="act", actions=3)
    assert ev.max_steps is None

    ev_with = PhaseChange(phase="act", actions=3, max_steps=40)
    assert ev_with.max_steps == 40
