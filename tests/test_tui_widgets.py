"""Phase 5 widget 单元:渲染 + reactive 更新(借 Pilot 挂进临时 App)。"""
from __future__ import annotations

import pytest
from textual.app import App, ComposeResult

from argos.core.types import Verdict
from argos.tui.theme import ARGOS_NIGHT
from argos.tui.widgets.code_action import CodeActionBlock
from argos.tui.widgets.diff_view import DiffView
from argos.tui.widgets.verdict_badge import VerdictBadge


class _Host(App):
    """挂任意 widget 做单元测试的临时宿主。"""

    def __init__(self, widget) -> None:
        super().__init__()
        self._w = widget

    def get_theme_variable_defaults(self) -> dict[str, str]:
        # v3 黑曜石 token($raise/$ink-ghost/$pass-weak/$hairline-lit 等)须在 DEFAULT_CSS
        # 解析阶段即可解析,否则 widget DEFAULT_CSS 抛 UnresolvedVariableError。register_theme
        # 在 on_mount 太晚(compose 时 CSS 已解析),故在变量默认值层注入(与 test_status_bar.py
        # 等成熟测试同模式)。
        return ARGOS_NIGHT.variables

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
        # TUI v2 扁平块:⏺ header Static + step(无边框盒,无 border_title)
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
        # TUI v3(spec §4.5):border_title 纯文字 "Edit · {path}"(⏺ 前缀去掉,仅左缘一线),
        # border_subtitle 减号用 U+2212(−,真数学减号),非 ASCII '-'。
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
        # TUI v2 扁平行:▌ + 文字标签(三态文案分明,色相由 verdict-* class 钉死)
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
        # TUI v3 状态眼:阶段眼字形 + 阶段名(◌idle),动作计数走 "动作N" 文字(⚙ 处决,spec §4.9)
        assert "idle" in bar.render_text
        bar.set_phase("verify", actions=3)
        bar.set_cost(tokens_in=12400, tokens_out=3100, cost_usd=0.013, elapsed_s=4.2)
        await pilot.pause()
        t = bar.render_text
        assert "verify" in t
        assert "动作3" in t
        # 去重(2026-07-01)+ 去花费:token/花费/耗时归右侧 ActivityPanel,不再在底栏重复
        assert "12.4k" not in t and "$" not in t and "4.2s" not in t
