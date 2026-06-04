"""Phase 3:工具注册表(契约 §4)。纯沙箱放原函数、broker-gated 经 _broker 包装;
ALL_TOOL_NAMES 实长 = UI 工具数(禁 seed 谎报)。"""
from __future__ import annotations

import asyncio

import pytest

from argos_agent import tools
from argos_agent.tools import files


def test_all_tool_names_exact():
    assert tools.ALL_TOOL_NAMES == [
        "read_file", "write_file", "edit_file", "search_files",
        "run_command", "web_search", "web_extract", "propose_verify",
    ]


def test_all_tool_names_count_is_8():
    """MVP 核心工具恰好 8 个(含真验证门 propose_verify)— 确保 playwright 未混入
    (保证 UI 数字诚实:工具数必须等于真实可调用工具数)。"""
    assert len(tools.ALL_TOOL_NAMES) == 8


def test_allowed_cmds_and_git_readonly_present():
    assert {"python", "pytest", "git", "rg"} <= tools.ALLOWED_CMDS
    assert {"status", "diff", "log"} <= tools.GIT_READONLY_SUBCMDS
    # 危险子命令不在只读集
    assert "push" not in tools.GIT_READONLY_SUBCMDS


def test_child_namespace_pure_tools_are_raw_functions():
    ns = tools.build_child_namespace(broker=None)
    assert ns["read_file"] is files.read_file
    assert ns["write_file"] is files.write_file
    assert ns["search_files"] is files.search_files


def test_child_namespace_gated_tools_call_broker():
    calls = []

    class FakeStub:
        def request(self, action, args):
            calls.append((action, args))
            return f"FAKE[{action}]"

    ns = tools.build_child_namespace(broker=FakeStub())
    out = ns["run_command"]("pytest -q")
    assert out == "FAKE[run_command]"
    assert calls == [("run_command", {"command": "pytest -q"})]
    ns["web_search"]("hello", 3)
    assert calls[-1] == ("web_search", {"query": "hello", "limit": 3})


def test_child_namespace_no_broker_missing_gated():
    """broker=None 时,broker-gated 工具不注入(纯沙箱单测场景)。"""
    ns = tools.build_child_namespace(broker=None)
    assert "run_command" not in ns
    assert "web_search" not in ns
    assert "web_extract" not in ns
    # 但纯沙箱工具照常可用
    assert "read_file" in ns


def test_build_namespace_includes_all_tools():
    """build_namespace(broker) 同时包含纯沙箱和 broker-gated 工具。"""
    calls = []

    class FakeBroker:
        async def request(self, action, args):
            calls.append(action)
            return "ok"

    ns = tools.build_namespace(broker=FakeBroker())
    assert "read_file" in ns
    assert "write_file" in ns
    assert "run_command" in ns
    assert "web_search" in ns
    assert "web_extract" in ns
    # 所有 7 个工具都在
    for name in tools.ALL_TOOL_NAMES:
        assert name in ns, f"{name} missing from build_namespace"
