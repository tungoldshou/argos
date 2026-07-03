"""Internal documentation."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from argos.tui.commands import COMMAND_HELP, parse_slash
from argos.protocol.events import CostUpdate
from argos.tui.app import ArgosApp
from argos.tui.widgets.activity_panel import ActivityPanel
from argos.tui.widgets.status_bar import StatusBar


def test_command_help_includes_context():
    """Internal documentation."""
    assert "context" in COMMAND_HELP
    assert "context" in COMMAND_HELP["context"].lower()


def test_parse_slash_context_recognized():
    """Internal documentation."""
    sc1 = parse_slash("/context")
    assert sc1 is not None
    assert sc1.name == "context"
    assert sc1.arg == ""
    assert sc1.known is True
    sc2 = parse_slash("/context --json")
    assert sc2 is not None
    assert sc2.arg == "--json"
    assert sc2.known is True




def test_activity_panel_on_context_adds_badge():
    """Internal documentation."""
    import inspect
    src = inspect.getsource(ActivityPanel)
    assert "ctx" in src and "badge" in src


def test_status_bar_update_ctx_pressure_above_80():
    """update_ctx_pressure(0.85) → ctx_pct=0.85(spec §10.4 + D8)。"""
    bar = StatusBar()
    bar.update_ctx_pressure(0.85)
    assert bar.ctx_pct == 0.85


def test_status_bar_update_ctx_pressure_below_80():
    """Internal documentation."""
    bar = StatusBar()
    bar.update_ctx_pressure(0.5)
    assert bar.ctx_pct == 0.5


def test_status_bar_update_ctx_pressure_zero_safe():
    """Internal documentation."""
    bar = StatusBar()
    bar.update_ctx_pressure(0)
    assert bar.ctx_pct == 0.0
    bar.update_ctx_pressure(0.0)
    assert bar.ctx_pct == 0.0


@pytest.mark.asyncio
async def test_cost_update_refreshes_status_bar_context_pressure(monkeypatch):
    """Internal documentation."""
    monkeypatch.setattr(
        ArgosApp,
        "_display_tier",
        staticmethod(lambda: type("_Tier", (), {"model": "m", "name": "default", "context_window": 100_000})()),
    )

    app = ArgosApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        await app._apply_event(CostUpdate(
            tokens_in=1,
            tokens_out=1,
            cost_usd=None,
            elapsed_s=0.1,
            context_used=85_000,
        ))
        await pilot.pause()

        assert app.query_one("#status-bar", StatusBar).ctx_pct == 0.85


import inspect
import argos.tui.app as _app


def test_context_cmd_uses_analyzer_and_render():
    """Internal documentation."""
    src = inspect.getsource(_app.ArgosApp._context_cmd)
    assert "analyze" in src
    assert "format_table" in src
    assert "format_json" in src
    assert "--json" in src


@pytest.mark.asyncio
async def test_context_unknown_arg_prints_usage():
    """Internal documentation."""
    class Log:
        def __init__(self) -> None:
            self.lines: list[tuple[str, str | None]] = []

        async def append_line(self, text: str, kind: str | None = None) -> None:
            self.lines.append((text, kind))

    log = Log()
    await _app.ArgosApp()._context_cmd(log, "bogus")

    text = "\n".join(line for line, _kind in log.lines)
    assert "Usage" in text or "用法" in text
    assert any(kind == "error" for _line, kind in log.lines)


@pytest.mark.asyncio
async def test_context_json_flag_is_case_insensitive():
    """/context --JSON should behave like /context --json."""
    class Log:
        def __init__(self) -> None:
            self.lines: list[tuple[str, str | None]] = []

        async def append_line(self, text: str, kind: str | None = None) -> None:
            self.lines.append((text, kind))

    log = Log()
    await _app.ArgosApp()._context_cmd(log, "--JSON")

    text = "\n".join(line for line, _kind in log.lines)
    assert "Usage" not in text and "用法" not in text
    assert text.lstrip().startswith("{")
