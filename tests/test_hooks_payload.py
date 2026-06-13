"""Payload 构造器 + 工具名抽取 + 模板占位(spec §2.3 / §4.4 / D8)。"""
from __future__ import annotations

import pytest

from argos.hooks.payload import (
    build_pre_payload,
    build_post_payload,
    build_stop_payload,
    build_user_prompt_payload,
    build_session_start_payload,
    extract_tool_names,
    render_command,
)


# ── extract_tool_names ─────────────────────────────────────────────────

def test_extract_tool_names_simple():
    """单行 tool 调用:write_file('a') → ['write_file']。"""
    code = "write_file('a.py', 'print(1)')"
    assert extract_tool_names(code) == ["write_file"]


def test_extract_tool_names_compound():
    """多行 / 多调用:write_file + run_command → 2 个,顺序按出现。"""
    code = "write_file('a.py', 'x')\nrun_command('ls')"
    assert extract_tool_names(code) == ["write_file", "run_command"]


def test_extract_tool_names_dedup_preserves_order():
    """重复调同 tool → 只一次(去重保 order)。"""
    code = "write_file('a', '1')\nwrite_file('b', '2')"
    assert extract_tool_names(code) == ["write_file"]


def test_extract_tool_names_no_call_returns_empty():
    """无 tool 调用 → []。"""
    code = "x = 1 + 1\nprint(x)"
    assert extract_tool_names(code) == []


def test_extract_tool_names_unknown_tool_ignored():
    """不在 ALL_TOOL_NAMES 的 tool 名 → 忽略(只匹已知 tool,防误报)。"""
    code = "malicious_function()\nwrite_file('a', '1')"
    assert extract_tool_names(code) == ["write_file"]


# ── 模板占位 ─────────────────────────────────────────────────────────

def test_render_command_replaces_cwd():
    """{cwd} 替换为 workspace 路径。"""
    assert render_command("ls {cwd}", cwd="/tmp/x") == "ls /tmp/x"


def test_render_command_replaces_session_id():
    """{session_id} 替换。"""
    assert render_command("echo {session_id}", session_id="abc") == "echo abc"


def test_render_command_replaces_tool_names():
    """{tool_names} 替换为逗号拼接(无 → 空串)。"""
    assert render_command(
        "echo {tool_names}", tool_names=["write_file", "run_command"]
    ) == "echo write_file,run_command"
    assert render_command("echo {tool_names}", tool_names=[]) == "echo "


# ── payload 构造器 ───────────────────────────────────────────────────

def test_build_pre_payload_fields():
    """PreToolUse payload 含 session_id / cwd / code / tool_names;无 Post/Stop 字段。"""
    p = build_pre_payload(
        session_id="s1", cwd="/ws", code="write_file('a','1')", tool_names=["write_file"],
    )
    assert p["hook_event_name"] == "PreToolUse"
    assert p["session_id"] == "s1"
    assert p["cwd"] == "/ws"
    assert p["code"] == "write_file('a','1')"
    assert p["tool_names"] == ["write_file"]
    # 不带 PostToolUse / Stop 字段
    assert "stdout" not in p
    assert "verdict_status" not in p
    assert "goal" not in p


def test_build_post_payload_fields():
    """PostToolUse payload 含 stdout / value_repr / exc / ok / code;无 Stop / UserPrompt 字段。"""
    p = build_post_payload(
        session_id="s1", cwd="/ws", code="ls()", tool_names=[],
        stdout="out", value_repr="[]", exc="", ok=True,
    )
    assert p["hook_event_name"] == "PostToolUse"
    assert p["stdout"] == "out"
    assert p["ok"] is True
    assert "verdict_status" not in p
    assert "goal" not in p


def test_build_stop_payload_fields():
    """Stop payload 含 goal / verdict_status / actions / elapsed_s / escalated。"""
    p = build_stop_payload(
        session_id="s1", cwd="/ws", goal="do x",
        verdict_status="passed", actions=3, elapsed_s=12.4, escalated=False,
    )
    assert p["hook_event_name"] == "Stop"
    assert p["goal"] == "do x"
    assert p["verdict_status"] == "passed"
    assert p["actions"] == 3
    assert p["elapsed_s"] == 12.4
    assert p["escalated"] is False
    assert "code" not in p


def test_build_user_prompt_payload_fields():
    """UserPromptSubmit payload 含 goal / session_id / cwd。"""
    p = build_user_prompt_payload(session_id="s1", cwd="/ws", goal="fix bug")
    assert p["hook_event_name"] == "UserPromptSubmit"
    assert p["goal"] == "fix bug"
    assert "verdict_status" not in p


def test_build_session_start_payload_fields():
    """SessionStart payload 含 model_tier / session_id / cwd。"""
    p = build_session_start_payload(
        session_id="s1", cwd="/ws", model_tier="default",
    )
    assert p["hook_event_name"] == "SessionStart"
    assert p["model_tier"] == "default"
    assert "goal" not in p
