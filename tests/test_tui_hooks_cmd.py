"""Internal documentation."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def isolated_hooks_home(monkeypatch):
    """Internal documentation."""
    tmp = tempfile.mkdtemp()
    monkeypatch.setenv("HOME", tmp)
    yield Path(tmp) / ".argos"
    # cleanup
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)


@pytest.mark.asyncio
async def test_hooks_command_lists_3_events_4_hooks(isolated_hooks_home, monkeypatch):
    """Internal documentation."""
    from argos.hooks import _reset_config
    from argos.hooks import reload_config
    isolated_hooks_home.mkdir(parents=True, exist_ok=True)
    p = isolated_hooks_home / "hooks.json"
    p.write_text(json.dumps({
        "version": 1,
        "hooks": {
            "PreToolUse": [
                {"matcher": "write_file", "hooks": [{"type": "command", "command": "a.sh"}]},
            ],
            "PostToolUse": [
                {"matcher": "edit_file", "hooks": [{"type": "command", "command": "b.sh"}]},
            ],
            "Stop": [
                {"hooks": [{"type": "command", "command": "c.sh"}]},
            ],
        },
    }))
    monkeypatch.setattr("argos.hooks.config.HOOKS_CONFIG_PATH", p)
    _reset_config()
    cfg = reload_config()
    assert len(cfg.entries) == 3
    assert "PreToolUse" in cfg.entries
    assert "PostToolUse" in cfg.entries
    assert "Stop" in cfg.entries


@pytest.mark.asyncio
async def test_hooks_reload_replaces_singleton(isolated_hooks_home, monkeypatch):
    """Internal documentation."""
    from argos.hooks import _reset_config, get_config, reload_config
    isolated_hooks_home.mkdir(parents=True, exist_ok=True)
    p = isolated_hooks_home / "hooks.json"
    p.write_text(json.dumps({"version": 1, "hooks": {}}))
    monkeypatch.setattr("argos.hooks.config.HOOKS_CONFIG_PATH", p)
    _reset_config()
    assert get_config().entries == {}
    p.write_text(json.dumps({
        "version": 1,
        "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "x"}]}]},
    }))
    reload_config()
    assert "Stop" in get_config().entries


@pytest.mark.asyncio
async def test_hooks_reload_invalid_keeps_old(isolated_hooks_home, monkeypatch):
    """Internal documentation."""
    from argos.hooks import _reset_config, get_config, reload_config, HooksConfigError
    isolated_hooks_home.mkdir(parents=True, exist_ok=True)
    p = isolated_hooks_home / "hooks.json"
    p.write_text(json.dumps({
        "version": 1,
        "hooks": {"PreToolUse": [{"hooks": [{"type": "command", "command": "old"}]}]},
    }))
    monkeypatch.setattr("argos.hooks.config.HOOKS_CONFIG_PATH", p)
    _reset_config()
    cfg_old = reload_config()
    p.write_text("{not json")
    with pytest.raises(HooksConfigError):
        reload_config()
    assert get_config() is cfg_old


def test_bad_config_splash_banner():
    """Internal documentation."""
    from argos.tui.widgets.splash import StartupSplash
    sp = StartupSplash(model_label="x", tier="default", live=True)
    sp.set_bad_config("parse error: bad json at line 3")
    text = sp.renderable_text
    assert "hooks 已禁用" in text
    assert "parse error" in text


def test_command_help_includes_hooks():
    """Internal documentation."""
    from argos.tui.commands import COMMAND_HELP
    assert "hooks" in COMMAND_HELP
    assert "reload" in COMMAND_HELP["hooks"]


@pytest.mark.asyncio
async def test_hooks_empty_mentions_configured_path(tmp_path, monkeypatch):
    from argos import config as C
    from argos.hooks import _reset_config
    from argos.tui.app import ArgosApp

    class Log:
        def __init__(self) -> None:
            self.lines: list[tuple[str, str | None]] = []

        async def append_line(self, text: str, kind: str | None = None) -> None:
            self.lines.append((text, kind))

    cfg_dir = tmp_path / "cfg"
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(cfg_dir))
    monkeypatch.setattr(C, "_ENV", {})
    monkeypatch.setattr("argos.hooks.config.HOOKS_CONFIG_PATH", None)
    _reset_config()

    log = Log()
    await ArgosApp()._hooks_cmd(log, "")

    text = "\n".join(line for line, _kind in log.lines)
    assert str(cfg_dir / "hooks.json") in text
    assert "~/.argos" not in text


@pytest.mark.asyncio
async def test_hooks_unknown_arg_prints_usage(isolated_hooks_home, monkeypatch):
    """Internal documentation."""
    from argos.hooks import _reset_config
    from argos.tui.app import ArgosApp

    isolated_hooks_home.mkdir(parents=True, exist_ok=True)
    p = isolated_hooks_home / "hooks.json"
    p.write_text(json.dumps({"version": 1, "hooks": {}}))
    monkeypatch.setattr("argos.hooks.config.HOOKS_CONFIG_PATH", p)
    _reset_config()

    class Log:
        def __init__(self) -> None:
            self.lines: list[tuple[str, str | None]] = []

        async def append_line(self, text: str, kind: str | None = None) -> None:
            self.lines.append((text, kind))

    log = Log()
    await ArgosApp()._hooks_cmd(log, "bogus")

    text = "\n".join(line for line, _kind in log.lines)
    assert "Usage" in text or "用法" in text
    assert any(kind == "error" for _line, kind in log.lines)


@pytest.mark.asyncio
async def test_hooks_reload_arg_is_case_insensitive(isolated_hooks_home, monkeypatch):
    """/hooks RELOAD should behave like /hooks reload."""
    from argos.hooks import _reset_config
    from argos.tui.app import ArgosApp

    isolated_hooks_home.mkdir(parents=True, exist_ok=True)
    p = isolated_hooks_home / "hooks.json"
    p.write_text(json.dumps({"version": 1, "hooks": {}}))
    monkeypatch.setattr("argos.hooks.config.HOOKS_CONFIG_PATH", p)
    _reset_config()

    class Log:
        def __init__(self) -> None:
            self.lines: list[tuple[str, str | None]] = []

        async def append_line(self, text: str, kind: str | None = None) -> None:
            self.lines.append((text, kind))

    log = Log()
    await ArgosApp()._hooks_cmd(log, "RELOAD")

    text = "\n".join(line for line, _kind in log.lines)
    assert "Usage" not in text and "用法" not in text
    assert any(kind == "system" for _line, kind in log.lines)


@pytest.mark.asyncio
async def test_user_prompt_submit_hook_failure_is_visible_and_run_continues(tmp_path, monkeypatch):
    from argos.hooks.events import HookFired
    from argos.hooks.runner import HookFireResult
    from argos.tui.app import ArgosApp
    from argos.tui.widgets.activity_panel import ActivityPanel

    ran: list[str] = []
    seen_hooks: list[HookFired] = []

    class EmptyLoop:
        async def run(self, goal: str, *, session_id: str, **kwargs):
            ran.append(goal)
            if False:
                yield None

    async def fake_fire(event_name, payload, *, cwd, session_id):
        ev = HookFired(
            event_name=event_name,
            command="false",
            success=False,
            returncode=1,
            elapsed_ms=7,
        )
        return HookFireResult(success=False, per_hook=(ev,), returncode=1)

    def capture_hook(self, ev: HookFired) -> None:
        seen_hooks.append(ev)

    monkeypatch.setattr("argos.hooks.fire", fake_fire)
    monkeypatch.setattr(ActivityPanel, "on_hook_fired", capture_hook)

    app = ArgosApp(loop_factory=lambda **kw: EmptyLoop(), workspace=tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.start_run("ship it")
        await app.workers.wait_for_complete()
        await pilot.pause()

    assert ran == ["ship it"]
    assert len(seen_hooks) == 1
    assert seen_hooks[0].event_name == "UserPromptSubmit"
    assert seen_hooks[0].success is False
    assert seen_hooks[0].returncode == 1
