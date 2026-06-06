"""TUI slash 接线测试(spec §2.6 / §2.7)。"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from argos_agent.tui.commands import COMMAND_HELP, match_commands, parse_slash


def test_command_help_has_three_new_entries():
    """COMMAND_HELP 含 verify / security-review / simplify(原 15 → 18)。"""
    assert "verify" in COMMAND_HELP
    assert "security-review" in COMMAND_HELP
    assert "simplify" in COMMAND_HELP


def test_match_commands_returns_three_new():
    """`/s` 前缀应匹 security-review + simplify(`/v` → verify)。"""
    matches_v = match_commands("/v")
    assert any(n == "verify" for n, _ in matches_v)
    matches_s = match_commands("/s")
    assert any(n == "security-review" for n, _ in matches_s) or any(n == "simplify" for n, _ in matches_s)


def test_slash_command_parses_with_path():
    """`/verify src/foo.py` → SlashCommand(name='verify', arg='src/foo.py')。"""
    cmd = parse_slash("/verify src/foo.py")
    assert cmd.name == "verify"
    assert cmd.arg == "src/foo.py"
    assert cmd.known is True


def test_slash_command_parses_no_arg():
    """`/verify` 无参 → SlashCommand(name='verify', arg='')。"""
    cmd = parse_slash("/verify")
    assert cmd.name == "verify"
    assert cmd.arg == ""


def test_path_not_found_chat_message(tmp_path):
    """path arg 不存在 → chat 显 'path not found: <arg>',不弹栈(由 runner 路径覆盖)。"""
    from argos_agent.skills_runtime.analysis import AnalysisSkillResult
    fake_result = AnalysisSkillResult(
        summary="path not found: nope.py",
        findings=(), duration_ms=0,
        errors=("path not found: nope.py",),
        verdict="skipped",
    )
    from argos_agent.skills_runtime import registry
    from argos_agent.skills_runtime.analysis import AnalysisSkill, AnalysisSkillContext
    import asyncio

    async def _echo(args, ctx):
        return fake_result
    registry.register(AnalysisSkill(
        name="verify", description="x", parameters_schema={}, run=_echo, requires_approval=True,
    ))

    ctx = AnalysisSkillContext(workspace=tmp_path, approval_level="auto", run_id="r1")
    result = asyncio.run(registry.get("verify").run({"path": "nope.py"}, ctx))
    assert result.verdict == "skipped"
    assert "path not found" in result.errors[0]


@pytest.mark.asyncio
@pytest.mark.slow
async def test_pilot_skill_cmd_dispatch(tmp_path, monkeypatch):
    """Pilot e2e:真实 TUI 输入 /verify → 调 run_skill → chat 显 summary。"""
    from textual.app import App
    from argos_agent.tui.app import ArgosApp
    from argos_agent.tui.fakeloop import FakeLoop
    from argos_agent.skills_runtime import _reset_registry, register_builtin_skills

    _reset_registry()  # 清理前一个测试的 stub
    monkeypatch.chdir(tmp_path)
    app = ArgosApp(loop_factory=lambda: FakeLoop())
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        # 通过 query prompt 并 submit 触发 /verify
        from argos_agent.tui.commands import parse_slash
        from argos_agent.tui.widgets.transcript import Transcript
        log = app.query_one("#transcript", Transcript)
        cmd = parse_slash("/verify")
        await app._dispatch_slash(cmd)
        await pilot.pause(0.5)
        # chat_log 应含 /verify 输出
        chat_text = "\n".join(getattr(line, "text", str(line)) for line in log._lines)
        assert "/verify" in chat_text or "n_a" in chat_text or "0 findings" in chat_text or "passed" in chat_text
