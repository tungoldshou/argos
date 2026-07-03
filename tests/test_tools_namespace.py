"""Internal documentation."""
from __future__ import annotations

import asyncio

import pytest

from argos import tools
from argos.tools import files


def test_all_tool_names_exact():
    assert tools.ALL_TOOL_NAMES == [
        "read_file", "write_file", "edit_file", "search_files",
        "run_command", "web_search", "web_extract", "propose_verify",
        "propose_dom_verify",
        "propose_gui_verify",
        "update_plan",
        "propose_workflow",
        "browser_navigate", "browser_snapshot", "browser_click",
        "browser_type", "browser_screenshot",
        "mcp_call",
        "lsp_definition", "lsp_references", "lsp_hover",
        "lsp_document_symbols", "lsp_workspace_symbols", "lsp_diagnostics",
        "computer_screenshot", "computer_click", "computer_double_click",
        "computer_type_text", "computer_key", "computer_scroll", "computer_open_app",
    ]


def test_all_tool_names_count_is_29():
    """Internal documentation."""
    assert len(tools.ALL_TOOL_NAMES) == 31
    ns = tools.build_child_namespace(broker=_FakeStub())
    for name in ("browser_navigate", "browser_snapshot", "browser_click",
                 "browser_type", "browser_screenshot", "mcp_call",
                 "lsp_definition", "lsp_references", "lsp_hover",
                 "lsp_document_symbols", "lsp_workspace_symbols", "lsp_diagnostics",
                 "computer_screenshot", "computer_click", "computer_double_click",
                 "computer_type_text", "computer_key", "computer_scroll", "computer_open_app"):
        assert callable(ns[name]), f"{name} 不可调用(谎报)"


class _FakeStub:
    def request(self, action, args):
        return f"FAKE[{action}]"


def test_allowed_cmds_verify_whitelist_present():
    assert {"python", "pytest", "git", "rg"} <= tools.ALLOWED_CMDS


def test_child_namespace_pure_tools_are_raw_functions():
    ns = tools.build_child_namespace(broker=None)
    assert ns["read_file"] is files.read_file
    assert ns["search_files"] is files.search_files
    assert "write_file" not in ns and "edit_file" not in ns


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
    """Internal documentation."""
    ns = tools.build_child_namespace(broker=None)
    assert "run_command" not in ns
    assert "web_search" not in ns
    assert "web_extract" not in ns
    assert "read_file" in ns


def test_build_namespace_includes_all_tools():
    """Internal documentation."""
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
    for name in tools.ALL_TOOL_NAMES:
        assert name in ns, f"{name} missing from build_namespace"




def test_write_file_strips_app_prefix_for_tb_compat(tmp_path, monkeypatch):
    """Internal documentation."""
    from argos import runtime
    from argos.tools import files as ftools
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "existing.txt").write_text("x")
    ctx = runtime.RunContext(workspace=ws, verify_dir=ws, project_mode=True)
    token = runtime.set_context(ctx)
    try:
        result = ftools.write_file("/app/hello.txt", "Hello, world!\n")
        assert "已写入" in result, result
        assert (ws / "hello.txt").read_text() == "Hello, world!\n"
        result = ftools.write_file("/etc/passwd", "x")
        assert "越出" in result or "错误" in result, result
        ftools.write_file("rel.txt", "r")
        assert (ws / "rel.txt").read_text() == "r"
        ftools.write_file("/app/data.txt", "d")
        content = ftools.read_file("/app/data.txt")
        assert "d" in content, content
    finally:
        runtime.reset(token)


def test_safe_path_rejects_traversal_but_allows_app_prefix(tmp_path, monkeypatch):
    """Internal documentation."""
    from argos.tools import files as ftools
    from argos import runtime
    ws = tmp_path / "ws"
    ws.mkdir()
    ctx = runtime.RunContext(workspace=ws, verify_dir=ws, project_mode=True)
    token = runtime.set_context(ctx)
    try:
        assert ftools._safe_path("/app/foo") == ws / "foo"
        assert ftools._safe_path("../../../etc/passwd") is None
        assert ftools._safe_path("/etc/passwd") is None
    finally:
        runtime.reset(token)
