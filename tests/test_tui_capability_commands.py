"""Internal documentation."""
from __future__ import annotations

import pytest

from argos.tui.app import ArgosApp
from argos.tui.commands import parse_slash
from argos.tui.fakeloop import FakeLoop
from argos.tui.widgets.transcript import Transcript


async def _dispatch(app, text: str) -> str:
    await app._dispatch_slash(parse_slash(text))
    return app.query_one("#transcript", Transcript).rendered_text


@pytest.mark.asyncio
async def test_help_lists_commands():
    app = ArgosApp(loop_factory=lambda **kw: FakeLoop())
    async with app.run_test() as pilot:
        await pilot.pause()
        txt = await _dispatch(app, "/help")
        assert "/tools" in txt and "/skills" in txt and "/mcp" in txt


@pytest.mark.asyncio
async def test_tools_lists_real_29_tools_grouped():
    app = ArgosApp(loop_factory=lambda **kw: FakeLoop())
    async with app.run_test() as pilot:
        await pilot.pause()
        txt = await _dispatch(app, "/tools")
        assert "31 个工具" in txt
        assert "browser_navigate" in txt
        assert "mcp_call" in txt
        assert "lsp_definition" in txt
        assert "computer_screenshot" in txt


@pytest.mark.asyncio
async def test_skills_lists_builtin_library(tmp_path, monkeypatch):
    """Internal documentation."""
    import argos.skills_curator.index as _idx
    monkeypatch.setattr(_idx, "_skills_root", lambda: tmp_path)
    app = ArgosApp(loop_factory=lambda **kw: FakeLoop())
    async with app.run_test() as pilot:
        await pilot.pause()
        txt = await _dispatch(app, "/skills")
        assert "Installed skills" in txt
        assert "(no skills installed" in txt or "Recommended" in txt


@pytest.mark.asyncio
async def test_mcp_honest_when_unconfigured(monkeypatch):
    app = ArgosApp(loop_factory=lambda **kw: FakeLoop())
    async with app.run_test() as pilot:
        await pilot.pause()
        txt = await _dispatch(app, "/mcp")
        assert "未配置 MCP" in txt or "未连上" in txt
