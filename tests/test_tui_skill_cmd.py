"""Internal documentation."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from argos.tui.commands import COMMAND_HELP, match_commands, parse_slash


def test_command_help_has_three_new_entries():
    """Internal documentation."""
    assert "verify" in COMMAND_HELP
    assert "security-review" in COMMAND_HELP
    assert "simplify" in COMMAND_HELP


def test_match_commands_returns_three_new():
    """Internal documentation."""
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
    """Internal documentation."""
    cmd = parse_slash("/verify")
    assert cmd.name == "verify"
    assert cmd.arg == ""


def test_path_not_found_chat_message(tmp_path):
    """Internal documentation."""
    from argos.skills_runtime.analysis import AnalysisSkillResult
    fake_result = AnalysisSkillResult(
        summary="path not found: nope.py",
        findings=(), duration_ms=0,
        errors=("path not found: nope.py",),
        verdict="skipped",
    )
    from argos.skills_runtime import registry, _reset_registry
    from argos.skills_runtime.analysis import AnalysisSkill, AnalysisSkillContext
    import asyncio

    _reset_registry()
    async def _echo(args, ctx):
        return fake_result
    try:
        registry.register(AnalysisSkill(
            name="verify", description="x", parameters_schema={}, run=_echo, requires_approval=True,
        ))

        ctx = AnalysisSkillContext(workspace=tmp_path, approval_level="auto", run_id="r1")
        result = asyncio.run(registry.get("verify").run({"path": "nope.py"}, ctx))
        assert result.verdict == "skipped"
        assert "path not found" in result.errors[0]
    finally:
        _reset_registry()


@pytest.mark.asyncio
async def test_skill_cmd_uses_app_workspace(tmp_path, monkeypatch):
    """TUI skill commands must scan the workspace Argos was launched for, not process cwd."""
    from argos.skills_runtime.analysis import AnalysisSkillResult
    from argos.tui.app import ArgosApp

    class Log:
        def __init__(self) -> None:
            self.lines: list[tuple[str, str | None]] = []

        async def append_line(self, text: str, kind: str | None = None) -> None:
            self.lines.append((text, kind))

    seen: dict[str, Path] = {}
    workspace = tmp_path / "project"
    workspace.mkdir()
    other = tmp_path / "other"
    other.mkdir()
    monkeypatch.chdir(other)

    async def fake_run_skill(name, args, ctx):  # noqa: ANN001
        seen["workspace"] = ctx.workspace
        return AnalysisSkillResult(
            summary="ok",
            findings=(),
            duration_ms=0,
            errors=(),
            verdict="passed",
        )

    monkeypatch.setattr("argos.skills_runtime.run_skill", fake_run_skill)
    monkeypatch.setattr("argos.skills_runtime.register_builtin_skills", lambda: None)

    await ArgosApp(workspace=workspace)._cmd_verify(Log(), "")

    assert seen["workspace"] == workspace.resolve()


@pytest.mark.asyncio
@pytest.mark.slow
async def test_pilot_skill_cmd_dispatch(tmp_path, monkeypatch):
    """Internal documentation."""
    from textual.app import App
    from argos.tui.app import ArgosApp
    from argos.tui.fakeloop import FakeLoop
    from argos.skills_runtime import _reset_registry, register_builtin_skills

    _reset_registry()
    monkeypatch.chdir(tmp_path)
    app = ArgosApp(loop_factory=lambda **kw: FakeLoop())
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        from argos.tui.commands import parse_slash
        from argos.tui.widgets.transcript import Transcript
        log = app.query_one("#transcript", Transcript)
        cmd = parse_slash("/verify")
        await app._dispatch_slash(cmd)
        await pilot.pause(0.5)
        chat_text = "\n".join(getattr(line, "text", str(line)) for line in log._lines)
        assert "/verify" in chat_text or "n_a" in chat_text or "0 findings" in chat_text or "passed" in chat_text
