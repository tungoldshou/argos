"""/permissions + /permissions reload slash 命令测试。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest


def test_command_help_has_permissions():
    from argos_agent.tui.commands import COMMAND_HELP
    assert "permissions" in COMMAND_HELP


def test_parse_slash_permissions():
    from argos_agent.tui.commands import parse_slash
    cmd = parse_slash("/permissions reload")
    assert cmd is not None
    assert cmd.name == "permissions"
    assert cmd.arg == "reload"
    assert cmd.known is True


def test_parse_slash_permissions_no_arg():
    from argos_agent.tui.commands import parse_slash
    cmd = parse_slash("/permissions")
    assert cmd is not None
    assert cmd.name == "permissions"
    assert cmd.arg == ""
    assert cmd.known is True


def test_match_commands_permissions():
    from argos_agent.tui.commands import match_commands
    matches = match_commands("/per")
    assert any(n == "permissions" for n, _ in matches)


def test_permissions_reload_returns_new_count(tmp_path, monkeypatch):
    """reload 改 json 后切新(同 hooks 模式)。"""
    from argos_agent.permissions import config as _cfg
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
