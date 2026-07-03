"""Internal documentation."""
import pytest
from textual.app import App, ComposeResult

from argos.core.verify_gate import Verdict
from argos.tui.theme import ARGOS_NIGHT
from argos.tui.widgets.verdict_badge import VerdictBadge


class _H(App):
    """Internal documentation."""

    def get_theme_variable_defaults(self) -> dict[str, str]:
        """Internal documentation."""
        defaults = super().get_theme_variable_defaults()
        if ARGOS_NIGHT.variables:
            defaults.update(ARGOS_NIGHT.variables)
        return defaults

    def compose(self) -> ComposeResult:
        yield VerdictBadge(id="vb")




def test_css_class_names_unchanged():
    """Internal documentation."""
    css = VerdictBadge.DEFAULT_CSS
    assert "verdict-passed" in css
    assert "verdict-failed" in css
    assert "verdict-unverifiable" in css
    assert "verdict-self" in css




@pytest.mark.asyncio
async def test_three_states_get_distinct_classes():
    """Internal documentation."""
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        vb = app.query_one("#vb", VerdictBadge)
        vb.show(Verdict.passed(detail="ok", verify_cmd="echo", attempts=1))
        await pilot.pause()
        assert vb.has_class("verdict-passed")
        vb.show(Verdict.failed(detail="bad", verify_cmd="echo", attempts=1))
        await pilot.pause()
        assert vb.has_class("verdict-failed") and not vb.has_class("verdict-passed")
        vb.show(Verdict.unverifiable(detail="??", tampered=[], attempts=1))
        await pilot.pause()
        assert vb.has_class("verdict-unverifiable") and not vb.has_class("verdict-failed")




@pytest.mark.asyncio
async def test_passed_prefix_eye():
    """Internal documentation."""
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        vb = app.query_one("#vb", VerdictBadge)
        vb.show(Verdict.passed(detail="42 passed", verify_cmd="pytest -x", attempts=1))
        await pilot.pause()
        assert "◉" in vb.render_text


@pytest.mark.asyncio
async def test_failed_prefix_eye():
    """Internal documentation."""
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        vb = app.query_one("#vb", VerdictBadge)
        vb.show(Verdict.failed(detail="3 failed", verify_cmd="pytest -x", attempts=2))
        await pilot.pause()
        assert "◉" in vb.render_text


@pytest.mark.asyncio
async def test_unverifiable_prefix_eye():
    """Internal documentation."""
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        vb = app.query_one("#vb", VerdictBadge)
        vb.show(Verdict.unverifiable(detail="trivial command rejected", tampered=[], attempts=1))
        await pilot.pause()
        assert "◔" in vb.render_text


@pytest.mark.asyncio
async def test_self_verified_prefix_eye():
    """Internal documentation."""
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        vb = app.query_one("#vb", VerdictBadge)
        vb.show(Verdict.passed_self(detail="3 checks ok", verify_cmd=None, attempts=1))
        await pilot.pause()
        assert "◍" in vb.render_text




@pytest.mark.asyncio
async def test_passed_shows_verify_cmd_and_attempts():
    """Internal documentation."""
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        vb = app.query_one("#vb", VerdictBadge)
        vb.show(Verdict.passed(detail="12 passed", verify_cmd="pytest -x", attempts=1))
        await pilot.pause()
        assert "pytest -x" in vb.render_text
        assert "次尝试" in vb.render_text or "1 次" in vb.render_text




@pytest.mark.asyncio
async def test_failed_shows_detail_and_retry():
    """Internal documentation."""
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        vb = app.query_one("#vb", VerdictBadge)
        vb.show(Verdict.failed(detail="assert mismatch", verify_cmd="pytest -x", attempts=3))
        await pilot.pause()
        assert "assert mismatch" in vb.render_text
        assert "重试" in vb.render_text




@pytest.mark.asyncio
async def test_unverifiable_text_contains_wufa():
    """Internal documentation."""
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        vb = app.query_one("#vb", VerdictBadge)
        vb.show(Verdict.unverifiable(detail="trivial command rejected", tampered=[], attempts=1))
        await pilot.pause()
        assert "无法验证" in vb.render_text


@pytest.mark.asyncio
async def test_tampered_归入_unverifiable():
    """Internal documentation."""
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        vb = app.query_one("#vb", VerdictBadge)
        vb.show(Verdict.unverifiable(detail="tamper detected", tampered=["auth.py"], attempts=1))
        await pilot.pause()
        assert vb.has_class("verdict-unverifiable")
        assert "无法验证" in vb.render_text
        assert "◔" in vb.render_text




@pytest.mark.asyncio
async def test_self_verified_css_class_not_passed():
    """Internal documentation."""
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        vb = app.query_one("#vb", VerdictBadge)
        vb.show(Verdict.passed_self(detail="3 checks ok", verify_cmd=None, attempts=1))
        await pilot.pause()
        assert vb.has_class("verdict-self")
        assert not vb.has_class("verdict-passed")


@pytest.mark.asyncio
async def test_self_verified_render_text_contains_weaker_and_not_promoted():
    """Internal documentation."""
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        vb = app.query_one("#vb", VerdictBadge)
        vb.show(Verdict.passed_self(detail="3 checks ok", verify_cmd=None, attempts=1))
        await pilot.pause()
        assert "较弱" in vb.render_text
        assert "未晋级" in vb.render_text


@pytest.mark.asyncio
async def test_self_verified_second_line_annotation():
    """Internal documentation."""
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        vb = app.query_one("#vb", VerdictBadge)
        vb.show(Verdict.passed_self(detail="3 checks ok", verify_cmd=None, attempts=1))
        await pilot.pause()
        assert "⤷" in vb.render_text




def test_css_passed_uses_pass_token():
    """Internal documentation."""
    css = VerdictBadge.DEFAULT_CSS
    assert "$pass" in css


def test_css_failed_uses_fail_token():
    """Internal documentation."""
    css = VerdictBadge.DEFAULT_CSS
    assert "$fail" in css


def test_css_unverifiable_uses_unverif_token():
    """Internal documentation."""
    css = VerdictBadge.DEFAULT_CSS
    assert "$unverif" in css


def test_css_self_uses_pass_weak_token():
    """Internal documentation."""
    css = VerdictBadge.DEFAULT_CSS
    assert "$pass-weak" in css
