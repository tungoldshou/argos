"""Phase 5 slash:解析为 (name, arg) 并映射到动作枚举(spec §4.5)。"""
from __future__ import annotations

import pytest

from argos_agent.tui.commands import SlashCommand, parse_slash, COMMAND_NAMES


def test_known_commands_listed():
    assert set(COMMAND_NAMES) == {
        "yolo", "undo", "clear", "retry", "status", "model", "resume", "cost",
        "help", "tools", "skills", "mcp", "plan", "hooks",
        "lsp",  # 2026-06-06:列出 / 重载 LSP 配置(/lsp, /lsp reload)
    }


def test_capability_discovery_commands_known():
    """能力可见命令(/help /tools /skills /mcp)必须 known=True,才会进 _dispatch_slash 分发。"""
    for name in ("help", "tools", "skills", "mcp"):
        cmd = parse_slash(f"/{name}")
        assert cmd is not None and cmd.known is True, f"/{name} 应为已知命令"


def test_parse_plain_text_is_not_a_command():
    assert parse_slash("帮我修个 bug") is None


def test_parse_bare_command():
    cmd = parse_slash("/yolo")
    assert isinstance(cmd, SlashCommand)
    assert cmd.name == "yolo" and cmd.arg == ""


def test_parse_command_with_arg():
    cmd = parse_slash("/model premium")
    assert cmd.name == "model" and cmd.arg == "premium"


def test_parse_strips_whitespace():
    cmd = parse_slash("  /resume   2  ")
    assert cmd.name == "resume" and cmd.arg == "2"


def test_parse_unknown_command_returns_error_marker():
    cmd = parse_slash("/frobnicate")
    assert cmd is not None
    assert cmd.name == "frobnicate"
    assert cmd.known is False


def test_known_flag_true_for_valid():
    assert parse_slash("/cost").known is True
