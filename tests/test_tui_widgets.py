"""Phase 5 widget 单元:渲染 + reactive 更新(借 Pilot 挂进临时 App)。"""
from __future__ import annotations

import pytest
from textual.app import App, ComposeResult

from argos_agent.core.types import Verdict
from argos_agent.tui.widgets.code_action import CodeActionBlock
from argos_agent.tui.widgets.diff_view import DiffView
from argos_agent.tui.widgets.verdict_badge import VerdictBadge


class _Host(App):
    """挂任意 widget 做单元测试的临时宿主。"""

    def __init__(self, widget) -> None:
        super().__init__()
        self._w = widget

    def compose(self) -> ComposeResult:
        yield self._w


# test_transcript_appends_token_deltas 已随 Task 3 删除 TranscriptLog(改用
# Transcript+流式 Markdown);等价覆盖见 tests/test_transcript_widget.py。


@pytest.mark.asyncio
async def test_code_action_block_shows_code_and_collapsed_output():
    block = CodeActionBlock(code="x = search_files('foo')", step=0)
    app = _Host(block)
    async with app.run_test() as pilot:
        await pilot.pause()
        # ⏺ header + step(spec §widget 改造:不再手画 ASCII box)
        assert "⏺" in str(block.border_title)
        assert "0" in str(block.border_title)
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
        # ⏺ header + path + +N/−M 计数(spec §widget 改造:不再手画 ┌ ASCII box)
        assert "⏺" in str(dv.border_title)
        assert "auth.py" in str(dv.border_title)
        assert "+3" in str(dv.border_subtitle) and "1" in str(dv.border_subtitle)


@pytest.mark.asyncio
async def test_verdict_badge_three_states():
    badge = VerdictBadge()
    app = _Host(badge)
    async with app.run_test() as pilot:
        await pilot.pause()
        badge.show(Verdict.passed(detail="12 passed (0.8s)", verify_cmd="pytest", attempts=1))
        await pilot.pause()
        assert badge.status == "passed"
        assert "✅" in badge.render_text and "pytest" in badge.render_text

        badge.show(Verdict.failed(detail="1 failed", verify_cmd="pytest", attempts=2))
        await pilot.pause()
        assert badge.status == "failed" and "❌" in badge.render_text

        badge.show(Verdict.unverifiable(detail="tampered", tampered=["t.py"], attempts=2))
        await pilot.pause()
        assert badge.status == "unverifiable" and "⚠️" in badge.render_text

from argos_agent.tui.widgets.status_bar import StatusBar
from argos_agent.tui.widgets.cost_meter import CostMeter


@pytest.mark.asyncio
async def test_status_bar_always_on_fields():
    bar = StatusBar()
    app = _Host(bar)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert "phase:" in bar.render_text
        assert "$0" in bar.render_text
        bar.set_phase("verify", actions=3)
        bar.set_cost(tokens_in=12400, tokens_out=3100, cost_usd=0.013, elapsed_s=4.2)
        await pilot.pause()
        t = bar.render_text
        assert "verify" in t
        assert "⚙3" in t
        assert "12.4k" in t and "3.1k" in t
        assert "$0.013" in t
        assert "4.2s" in t


@pytest.mark.asyncio
async def test_cost_meter_accumulates_from_events():
    meter = CostMeter()
    app = _Host(meter)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert meter.cost_usd == 0.0
        meter.update_cost(tokens_in=100, tokens_out=50, cost_usd=0.002, elapsed_s=1.0)
        await pilot.pause()
        assert meter.cost_usd == 0.002
        assert meter.tokens_in == 100 and meter.tokens_out == 50
        assert "$0.002" in meter.render_text
