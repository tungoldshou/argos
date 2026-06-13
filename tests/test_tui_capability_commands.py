"""能力可见命令(/help /tools /skills /mcp)的分发铁证 —— 经真 ArgosApp + Pilot 走通,
断言 transcript 里出现真实能力信息(诚实:数量/内容来自真实注册表/技能库)。"""
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
    app = ArgosApp(loop_factory=lambda: FakeLoop())
    async with app.run_test() as pilot:
        await pilot.pause()
        txt = await _dispatch(app, "/help")
        assert "/tools" in txt and "/skills" in txt and "/mcp" in txt


@pytest.mark.asyncio
async def test_tools_lists_real_29_tools_grouped():
    app = ArgosApp(loop_factory=lambda: FakeLoop())
    async with app.run_test() as pilot:
        await pilot.pause()
        txt = await _dispatch(app, "/tools")
        assert "30 个工具" in txt                 # 诚实数量(= ALL_TOOL_NAMES 实长；stt_transcribe 是宿主进程能力非沙箱工具)
        assert "browser_navigate" in txt          # 计算机控制分组真出现(浏览器)
        assert "mcp_call" in txt                   # 外部工具分组真出现
        assert "lsp_definition" in txt             # LSP 工具分组真出现
        assert "computer.screenshot" in txt        # OS 级控制分组真出现


@pytest.mark.asyncio
async def test_skills_lists_builtin_library(tmp_path, monkeypatch):
    """#10 T6:/skills 重写为 curator 视图,列 installed + available + Recommended."""
    import argos.skills_curator.index as _idx
    monkeypatch.setattr(_idx, "_skills_root", lambda: tmp_path)
    app = ArgosApp(loop_factory=lambda: FakeLoop())
    async with app.run_test() as pilot:
        await pilot.pause()
        txt = await _dispatch(app, "/skills")
        # 新实现:列 installed + available + Recommended
        assert "Installed skills" in txt
        assert "(no skills installed" in txt or "Recommended" in txt


@pytest.mark.asyncio
async def test_mcp_honest_when_unconfigured(monkeypatch):
    # conftest 已把 MCP 单例指向不存在的 config(零预配)→ /mcp 应诚实报未配置/无工具。
    app = ArgosApp(loop_factory=lambda: FakeLoop())
    async with app.run_test() as pilot:
        await pilot.pause()
        txt = await _dispatch(app, "/mcp")
        assert "未配置 MCP" in txt or "未连上" in txt
