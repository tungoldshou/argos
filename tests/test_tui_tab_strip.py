"""Internal documentation."""
from __future__ import annotations

import pytest
from textual.app import App, ComposeResult

from argos.tui.theme import ARGOS_NIGHT
from argos.tui.widgets.tab_strip import (
    TabActivated,
    TabStrip,
    _format_cost,
    _truncate,
    _STATE_ICON,
)




def test_format_cost_none():
    assert _format_cost(None) == "$N/A"


def test_format_cost_small():
    assert _format_cost(0.001) == "$<0.01"
    assert _format_cost(0.009) == "$<0.01"


def test_format_cost_medium():
    assert _format_cost(0.05) == "$0.050"
    assert _format_cost(0.123) == "$0.123"


def test_format_cost_large():
    assert _format_cost(1.5) == "$1.50"
    assert _format_cost(10.123) == "$10.12"


def test_truncate_short():
    assert _truncate("hi", 10) == "hi"


def test_truncate_long():
    # n=10 → 9 chars + ellipsis = 10 chars total
    assert _truncate("hello world this is long", 10) == "hello wor…"
    assert len(_truncate("hello world this is long", 10)) == 10


def test_state_icon_known_states():
    assert _STATE_ICON["running"] == "⏵"
    assert _STATE_ICON["paused"] == "⏸"
    assert _STATE_ICON["suspended"] == "⏹"
    assert _STATE_ICON["failed"] == "◉"
    assert _STATE_ICON["cancelled"] == "⏹"
    assert _STATE_ICON["completed"] == "◕"
    assert _STATE_ICON["pending"] == "◌"




class _TabApp(App):
    """Internal documentation."""

    def __init__(self) -> None:
        super().__init__()
        self.register_theme(ARGOS_NIGHT)
        self.theme = "argos-night"

    def compose(self) -> ComposeResult:
        yield TabStrip(id="tabs")


@pytest.mark.asyncio
async def test_tab_strip_empty_render():
    app = _TabApp()
    async with app.run_test() as pilot:
        strip = app.query_one(TabStrip)
        assert "(no runs)" in strip.render()


@pytest.mark.asyncio
async def test_tab_strip_renders_5_tabs():
    app = _TabApp()
    async with app.run_test() as pilot:
        strip = app.query_one(TabStrip)
        tabs = [
            {"run_id": f"a{i:011x}", "goal": f"goal-{i}", "state": "running",
             "cost_usd": 0.01 * i}
            for i in range(5)
        ]
        strip.update_tabs(tabs, active=tabs[0]["run_id"])
        out = strip.render()
        assert "goal-0" in out
        assert "goal-4" in out
        assert "⏵" in out


@pytest.mark.asyncio
async def test_tab_strip_renders_with_active_highlight():
    app = _TabApp()
    async with app.run_test() as pilot:
        strip = app.query_one(TabStrip)
        tabs = [
            {"run_id": "a" * 12, "goal": "alpha", "state": "running", "cost_usd": 0.01},
            {"run_id": "b" * 12, "goal": "beta", "state": "paused", "cost_usd": 0.02},
        ]
        strip.update_tabs(tabs, active="b" * 12)
        out = strip.render()
        assert "[reverse]" not in out
        assert "beta" in out
        assert "bold" in out.lower() or "#23263A" in out or "on #" in out


@pytest.mark.asyncio
async def test_tab_strip_icon_for_each_state():
    app = _TabApp()
    async with app.run_test() as pilot:
        strip = app.query_one(TabStrip)
        tabs = [
            {"run_id": "a" * 12, "goal": "r", "state": "running", "cost_usd": 0.01},
            {"run_id": "b" * 12, "goal": "p", "state": "paused", "cost_usd": 0.01},
            {"run_id": "c" * 12, "goal": "s", "state": "suspended", "cost_usd": 0.01},
            {"run_id": "d" * 12, "goal": "f", "state": "failed", "cost_usd": 0.01},
            {"run_id": "e" * 12, "goal": "x", "state": "cancelled", "cost_usd": 0.01},
            {"run_id": "f" * 12, "goal": "v", "state": "completed", "cost_usd": 0.01},
            {"run_id": "0" * 12, "goal": "n", "state": "pending", "cost_usd": 0.01},
        ]
        strip.update_tabs(tabs)
        out = strip.render()
        for icon in ["⏵", "⏸", "⏹", "◉", "◕", "◌"]:
            assert icon in out


@pytest.mark.asyncio
async def test_tab_strip_truncates_long_goal():
    app = _TabApp()
    async with app.run_test() as pilot:
        strip = app.query_one(TabStrip)
        long_goal = "x" * 100
        tabs = [{"run_id": "a" * 12, "goal": long_goal, "state": "running",
                 "cost_usd": 0.01}]
        strip.update_tabs(tabs)
        out = strip.render()
        # 24 chars max + 1 ellipsis
        assert "…" in out
        assert "x" * 25 not in out


@pytest.mark.asyncio
async def test_tab_strip_includes_cost():
    app = _TabApp()
    async with app.run_test() as pilot:
        strip = app.query_one(TabStrip)
        tabs = [
            {"run_id": "a" * 12, "goal": "g1", "state": "running", "cost_usd": 0.05},
            {"run_id": "b" * 12, "goal": "g2", "state": "running", "cost_usd": None},
        ]
        strip.update_tabs(tabs)
        out = strip.render()
        assert "$0.050" in out
        assert "$N/A" in out


@pytest.mark.asyncio
async def test_tab_strip_post_activated_message_on_click():
    """Internal documentation."""
    app = _TabApp()
    activated: list[TabActivated] = []
    original_post = TabStrip.post_message

    def spy(self, message):
        if isinstance(message, TabActivated):
            activated.append(message)
        return original_post(self, message)

    TabStrip.post_message = spy
    try:
        async with app.run_test() as pilot:
            strip = app.query_one(TabStrip)
            tabs = [
                {"run_id": "a" * 12, "goal": "alpha", "state": "running", "cost_usd": 0.01},
                {"run_id": "b" * 12, "goal": "beta", "state": "running", "cost_usd": 0.02},
            ]
            strip.update_tabs(tabs, active="a" * 12)
            strip.post_message(TabActivated("a" * 12))
            await pilot.pause()
            assert any(m.run_id == "a" * 12 for m in activated)
    finally:
        TabStrip.post_message = original_post


@pytest.mark.asyncio
async def test_tab_strip_action_select_tab_0_to_4():
    """Internal documentation."""
    app = _TabApp()
    activated: list[TabActivated] = []
    original_post = TabStrip.post_message

    def spy(self, message):
        if isinstance(message, TabActivated):
            activated.append(message)
        return original_post(self, message)

    TabStrip.post_message = spy
    try:
        async with app.run_test() as pilot:
            strip = app.query_one(TabStrip)
            tabs = [
                {"run_id": f"{i:012x}", "goal": f"g{i}", "state": "running",
                 "cost_usd": 0.01}
                for i in range(5)
            ]
            strip.update_tabs(tabs)
            strip.action_select_tab(0)
            strip.action_select_tab(2)
            strip.action_select_tab(4)
            await pilot.pause()
            rids = [m.run_id for m in activated if isinstance(m, TabActivated)]
            assert rids == [f"{i:012x}" for i in [0, 2, 4]]
    finally:
        TabStrip.post_message = original_post


@pytest.mark.asyncio
async def test_tab_strip_ctrl_5_noop_when_fewer_tabs():
    """Internal documentation."""
    app = _TabApp()
    activated: list[TabActivated] = []
    original_post = TabStrip.post_message

    def spy(self, message):
        if isinstance(message, TabActivated):
            activated.append(message)
        return original_post(self, message)

    TabStrip.post_message = spy
    try:
        async with app.run_test() as pilot:
            strip = app.query_one(TabStrip)
            tabs = [
                {"run_id": "a" * 12, "goal": "g1", "state": "running", "cost_usd": 0.01},
            ]
            strip.update_tabs(tabs)
            strip.action_select_tab(4)
            await pilot.pause()
            assert activated == []
    finally:
        TabStrip.post_message = original_post
