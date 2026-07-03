"""Internal documentation."""
from __future__ import annotations

import pytest
from textual.app import App, ComposeResult

from argos.tui.widgets.activity_panel import ActivityPanel
from argos.tui.theme import ARGOS_NIGHT


class _H(App):
    """Internal documentation."""

    def get_theme_variable_defaults(self) -> dict[str, str]:
        """Internal documentation."""
        defaults = super().get_theme_variable_defaults()
        if ARGOS_NIGHT.variables:
            defaults.update(ARGOS_NIGHT.variables)
        return defaults

    def compose(self) -> ComposeResult:
        yield ActivityPanel(id="ap", model_label="M3", tier="t")


def _visible_titles(ap: ActivityPanel) -> set[str]:
    return {str(s.border_title) for s in ap._sections() if s.display}


@pytest.mark.asyncio
async def test_idle_view_default_and_footer_always_on():
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        ap = app.query_one("#ap", ActivityPanel)
        vis = _visible_titles(ap)
        assert "模型" in vis and "MCP" in vis
        assert "工具" not in vis
        assert "用量 + 缓存" in vis and "上下文" in vis


@pytest.mark.asyncio
async def test_phase_drives_view_auto_switch():
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        ap = app.query_one("#ap", ActivityPanel)
        ap.on_phase("plan", 0)
        assert ap._view == "plan"
        assert "任务进度" in _visible_titles(ap)
        ap.on_phase("act", 1)
        assert ap._view == "act"
        vis = _visible_titles(ap)
        assert "工具" in vis and "Approval" in vis
        assert "模型" not in vis
        ap.on_phase("verify", 1)
        assert ap._view == "verify"
        assert "Verdict" in _visible_titles(ap)
        ap.on_run_end()
        assert ap._view == "idle"
        assert "用量 + 缓存" in _visible_titles(ap)


@pytest.mark.asyncio
async def test_pinned_view_ignores_phase():
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        ap = app.query_one("#ap", ActivityPanel)
        ap.set_view("act", pinned=True)
        ap.on_phase("plan", 0)
        assert ap._view == "act"
        ap.on_run_end()
        assert ap._view == "act"


@pytest.mark.asyncio
async def test_cycle_view_walks_and_returns_to_auto():
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        ap = app.query_one("#ap", ActivityPanel)
        seen = [ap.cycle_view() for _ in range(5)]
        assert seen == ["idle", "plan", "act", "verify", "auto"]
        assert ap._pinned is False
        ap.on_phase("act", 1)
        assert ap._view == "act"


@pytest.mark.asyncio
async def test_snapshot_text_aggregates_hidden_sections():
    """Internal documentation."""
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        ap = app.query_one("#ap", ActivityPanel)
        ap.on_receipt("write_file")
        ap.set_view("idle", pinned=True)
        assert "write_file" in ap.snapshot_text()


@pytest.mark.asyncio
async def test_verdict_section_shows_three_state_honestly():
    from argos.core.verify_gate import Verdict
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        ap = app.query_one("#ap", ActivityPanel)
        ap.on_verdict(Verdict.unverifiable(detail="no cmd", tampered=[], attempts=1))
        assert "unverifiable" in ap.snapshot_text()
        ap.on_verdict(Verdict.passed_self(detail="ok", verify_cmd="pytest", attempts=1))
        t = ap.snapshot_text()
        assert "passed" in t and "pytest" in t and "self-verified" in t
