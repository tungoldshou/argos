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
        "update_plan",
        "propose_workflow",
        "browser_navigate", "browser_snapshot", "browser_click",
        "browser_type", "browser_screenshot",
        "mcp_call",
        "lsp_definition", "lsp_references", "lsp_hover",
        "lsp_document_symbols", "lsp_workspace_symbols", "lsp_diagnostics",
        # P6a §10 computer use
        "computer.screenshot", "computer.click", "computer.double_click",
        "computer.type_text", "computer.key", "computer.scroll", "computer.open_app",
    ]


def test_all_tool_names_count_is_29():
    """工具恰好 29 个:10 核心 + 5 浏览器 + 1 MCP + 6 LSP + 7 computer use(P6a §10)。
    UI 工具数必须等于真实可调用工具数(禁 seed 谎报);每个名字都真有 namespace 包装可调。"""
    assert len(tools.ALL_TOOL_NAMES) == 29
    # 浏览器 + MCP + LSP + computer.* 工具确实是 broker-gated 可调用(非占位名)。
    ns = tools.build_child_namespace(broker=_FakeStub())
    for name in ("browser_navigate", "browser_snapshot", "browser_click",
                 "browser_type", "browser_screenshot", "mcp_call",
                 "lsp_definition", "lsp_references", "lsp_hover",
                 "lsp_document_symbols", "lsp_workspace_symbols", "lsp_diagnostics",
                 "computer.screenshot", "computer.click", "computer.double_click",
                 "computer.type_text", "computer.key", "computer.scroll", "computer.open_app"):
        assert callable(ns[name]), f"{name} 不可调用(谎报)"


class _FakeStub:
    def request(self, action, args):
        return f"FAKE[{action}]"


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


# ── /app/ 路径翻译(适配 TB 任务:容器内 /app = 宿主 worktree 根) ──


def test_write_file_strips_app_prefix_for_tb_compat(tmp_path, monkeypatch):
    """write_file('/app/hello.txt', ...) → 写到 <worktree>/hello.txt(等价于 /app/hello.txt 在容器内)。

    这是 TB 任务的"必须"——所有 TB task.yaml 用 /app/... 路径;agent 调 write_file
    不知道宿主 worktree 在哪,只认知 /app。适配器把 /app/... 翻译成 worktree 相对路径。
    """
    from argos_agent import runtime
    from argos_agent.tools import files as ftools
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "existing.txt").write_text("x")
    ctx = runtime.RunContext(workspace=ws, verify_dir=ws, project_mode=True)
    token = runtime.set_context(ctx)
    try:
        # 1) /app/foo 应写到 ws/foo
        result = ftools.write_file("/app/hello.txt", "Hello, world!\n")
        assert "已写入" in result, result
        assert (ws / "hello.txt").read_text() == "Hello, world!\n"
        # 2) 绝对路径非 /app 前缀 → 仍拒
        result = ftools.write_file("/etc/passwd", "x")
        assert "越出" in result or "错误" in result, result
        # 3) 相对路径原样工作
        ftools.write_file("rel.txt", "r")
        assert (ws / "rel.txt").read_text() == "r"
        # 4) read_file 同样处理 /app/
        ftools.write_file("/app/data.txt", "d")
        content = ftools.read_file("/app/data.txt")
        assert "d" in content, content
    finally:
        runtime.reset(token)


def test_safe_path_rejects_traversal_but_allows_app_prefix(tmp_path, monkeypatch):
    """_safe_path:工作区遍历仍拒(/app/ 之外的绝对路径);/app/ 视为相对。"""
    from argos_agent.tools import files as ftools
    from argos_agent import runtime
    ws = tmp_path / "ws"
    ws.mkdir()
    ctx = runtime.RunContext(workspace=ws, verify_dir=ws, project_mode=True)
    token = runtime.set_context(ctx)
    try:
        # /app/... → ws/... 允许
        assert ftools._safe_path("/app/foo") == ws / "foo"
        # ../../../etc/passwd → 仍拒
        assert ftools._safe_path("../../../etc/passwd") is None
        # /etc/passwd → 仍拒(workspace 之外)
        assert ftools._safe_path("/etc/passwd") is None
    finally:
        runtime.reset(token)
