from __future__ import annotations

import pytest
from textual.app import App, ComposeResult

from argos.core.types import Verdict
from argos.tui.theme import ARGOS_NIGHT
from argos.tui.widgets.code_action import CodeActionBlock
from argos.tui.widgets.diff_view import DiffView
from argos.tui.widgets.verdict_badge import VerdictBadge


class _Host(App):

    def __init__(self, widget) -> None:
        super().__init__()
        self._w = widget

    def get_theme_variable_defaults(self) -> dict[str, str]:
        return ARGOS_NIGHT.variables

    def compose(self) -> ComposeResult:
        yield self._w




@pytest.mark.asyncio
async def test_code_action_block_shows_code_and_collapsed_output():
    block = CodeActionBlock(code="x = search_files('foo')", step=0)
    app = _Host(block)
    async with app.run_test() as pilot:
        await pilot.pause()
        header = str(block.query_one("#header").render())
        assert "⏺" in header
        assert "0" in header
        block.set_result(stdout="1 match", value_repr="['foo.py']", exc="", ok=True)
        await pilot.pause()
        assert block.ok is True
        assert not block.has_class("ok-false")


@pytest.mark.asyncio
async def test_code_action_block_marks_error():
    block = CodeActionBlock(code="boom()", step=1)
    app = _Host(block)
    async with app.run_test() as pilot:
        await pilot.pause()
        block.set_result(stdout="", value_repr="", exc="NameError: boom", ok=False)
        await pilot.pause()
        assert block.ok is False
        assert block.has_class("ok-false")


@pytest.mark.asyncio
async def test_diff_view_renders_added_removed_counts():
    dv = DiffView(
        path="auth.py", added=3, removed=1,
        unified="--- a/auth.py\n+++ b/auth.py\n@@\n-old\n+new1\n+new2\n+new3\n",
    )
    app = _Host(dv)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert str(dv.border_title) == "Edit · auth.py"
        assert "+3" in str(dv.border_subtitle) and "−1" in str(dv.border_subtitle)


@pytest.mark.asyncio
async def test_verdict_badge_three_states():
    badge = VerdictBadge()
    app = _Host(badge)
    async with app.run_test() as pilot:
        await pilot.pause()
        badge.show(Verdict.passed(detail="12 passed (0.8s)", verify_cmd="pytest", attempts=1))
        await pilot.pause()
        assert badge.status == "passed"
        assert "verify passed" in badge.render_text and "pytest" in badge.render_text

        badge.show(Verdict.failed(detail="1 failed", verify_cmd="pytest", attempts=2))
        await pilot.pause()
        assert badge.status == "failed" and "verify FAILED" in badge.render_text

        badge.show(Verdict.unverifiable(detail="tampered", tampered=["t.py"], attempts=2))
        await pilot.pause()
        assert badge.status == "unverifiable" and "无法验证" in badge.render_text

from argos.tui.widgets.status_bar import StatusBar


@pytest.mark.asyncio
async def test_status_bar_always_on_fields():
    bar = StatusBar()
    app = _Host(bar)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert "idle" in bar.render_text
        bar.set_phase("verify", actions=3)
        bar.set_cost(tokens_in=12400, tokens_out=3100, cost_usd=0.013, elapsed_s=4.2)
        await pilot.pause()
        t = bar.render_text
        assert "verify" in t
        assert "动作3" in t
        assert "12.4k" not in t and "$" not in t and "4.2s" not in t
