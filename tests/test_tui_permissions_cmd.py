"""/permissions + /permissions reload slash 命令测试。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest


def test_command_help_has_permissions():
    from argos.tui.commands import COMMAND_HELP
    assert "permissions" in COMMAND_HELP


def test_parse_slash_permissions():
    from argos.tui.commands import parse_slash
    cmd = parse_slash("/permissions reload")
    assert cmd is not None
    assert cmd.name == "permissions"
    assert cmd.arg == "reload"
    assert cmd.known is True


def test_parse_slash_permissions_no_arg():
    from argos.tui.commands import parse_slash
    cmd = parse_slash("/permissions")
    assert cmd is not None
    assert cmd.name == "permissions"
    assert cmd.arg == ""
    assert cmd.known is True


def test_match_commands_permissions():
    from argos.tui.commands import match_commands
    matches = match_commands("/per")
    assert any(n == "permissions" for n, _ in matches)


def test_permissions_reload_returns_new_count(tmp_path, monkeypatch):
    """reload 改 json 后切新(同 hooks 模式)。"""
    from argos.permissions import config as _cfg
    monkeypatch.setattr(_cfg, "CONFIG_PATH", tmp_path / "permissions.json")
    _cfg._reset_config()
    (tmp_path / "permissions.json").write_text(json.dumps({
        "version": 1,
        "allow": [{"tool": "run_command", "matcher": r"^pytest"}],
    }))
    cfg = _cfg.reload_config()
    assert len(cfg.allow) == 1
    (tmp_path / "permissions.json").write_text(json.dumps({
        "version": 1,
        "allow": [
            {"tool": "run_command", "matcher": r"^pytest"},
            {"tool": "run_command", "matcher": r"^ls "},
        ],
    }))
    cfg = _cfg.reload_config()
    assert len(cfg.allow) == 2


@pytest.mark.asyncio
async def test_permissions_unknown_arg_prints_usage(tmp_path, monkeypatch):
    """/permissions 只接受空参数或 reload,未知参数应报用法。"""
    from argos.permissions import config as _cfg
    from argos.tui.app import ArgosApp

    monkeypatch.setattr(_cfg, "CONFIG_PATH", tmp_path / "permissions.json")
    _cfg._reset_config()
    (tmp_path / "permissions.json").write_text(json.dumps({"version": 1}))

    class Log:
        def __init__(self) -> None:
            self.lines: list[tuple[str, str | None]] = []

        async def append_line(self, text: str, kind: str | None = None) -> None:
            self.lines.append((text, kind))

    log = Log()
    await ArgosApp()._permissions_cmd(log, "bogus")

    text = "\n".join(line for line, _kind in log.lines)
    assert "Usage" in text or "用法" in text
    assert any(kind == "error" for _line, kind in log.lines)


@pytest.mark.asyncio
async def test_permissions_reload_arg_is_case_insensitive(tmp_path, monkeypatch):
    """/permissions RELOAD should behave like /permissions reload."""
    from argos.permissions import config as _cfg
    from argos.tui.app import ArgosApp

    monkeypatch.setattr(_cfg, "CONFIG_PATH", tmp_path / "permissions.json")
    _cfg._reset_config()
    (tmp_path / "permissions.json").write_text(json.dumps({"version": 1}))

    class Log:
        def __init__(self) -> None:
            self.lines: list[tuple[str, str | None]] = []

        async def append_line(self, text: str, kind: str | None = None) -> None:
            self.lines.append((text, kind))

    log = Log()
    await ArgosApp()._permissions_cmd(log, "RELOAD")

    text = "\n".join(line for line, _kind in log.lines)
    assert "Usage" not in text and "用法" not in text
    assert any(kind == "system" for _line, kind in log.lines)
