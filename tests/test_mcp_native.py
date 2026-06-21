"""原生 MCP 客户端测试 —— 跑一个真的 stdio JSON-RPC echo server 子进程(非 mock)。

覆盖:
  ① 默认零预配:无 mcp.json → list_tools 空、tools_summary 空、call 诚实报"未配置"。
  ② 真 server 端到端:连接握手(initialize→initialized→tools/list)+ tools/call 回 ECHO。
  ③ 畸形 config / 未知 server / 不可用 server → 诚实降级,不抛。
  ④ broker._execute 把 mcp_call 路由到 manager。
"""
from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path

import pytest

from argos.mcp_native import McpManager


# 一个最小但合规的 stdio MCP echo server(newline-delimited JSON-RPC)。
_ECHO_SERVER = textwrap.dedent('''
    import sys, json
    def send(obj):
        sys.stdout.write(json.dumps(obj) + "\\n"); sys.stdout.flush()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        msg = json.loads(line)
        mid = msg.get("id"); method = msg.get("method")
        if method == "initialize":
            send({"jsonrpc":"2.0","id":mid,"result":{"protocolVersion":"2024-11-05",
                  "capabilities":{},"serverInfo":{"name":"echo","version":"1"}}})
        elif method == "notifications/initialized":
            pass
        elif method == "tools/list":
            send({"jsonrpc":"2.0","id":mid,"result":{"tools":[
                  {"name":"echo","description":"echo back the given text",
                   "inputSchema":{"type":"object","properties":{"text":{"type":"string"}}}}]}})
        elif method == "tools/call":
            args = (msg.get("params") or {}).get("arguments") or {}
            send({"jsonrpc":"2.0","id":mid,"result":{"content":[
                  {"type":"text","text":"ECHO:" + str(args.get("text",""))}]}})
        else:
            send({"jsonrpc":"2.0","id":mid,"error":{"code":-32601,"message":"method not found"}})
''')


def _write_echo_config(tmp_path: Path) -> Path:
    server = tmp_path / "echo_server.py"
    server.write_text(_ECHO_SERVER, encoding="utf-8")
    cfg = tmp_path / "mcp.json"
    cfg.write_text(json.dumps({
        "servers": {"echo": {"command": sys.executable, "args": [str(server)]}}
    }), encoding="utf-8")
    return cfg


# ── ① 默认零预配 ──────────────────────────────────────────────────────────────
def test_zero_config_is_honest(tmp_path):
    mgr = McpManager(config_path=tmp_path / "nonexistent.json")
    assert mgr.list_tools() == []
    assert mgr.tools_summary() == ""
    out = mgr.call("whatever", "tool", {})
    assert "未配置任何 MCP server" in out
    mgr.close()


# 应答握手但对 tools/call 永不回应的 server(模拟"活着但沉默"——常见 MCP 挂法)。
_SILENT_CALL_SERVER = textwrap.dedent('''
    import sys, json
    def send(obj):
        sys.stdout.write(json.dumps(obj) + "\\n"); sys.stdout.flush()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        msg = json.loads(line); mid = msg.get("id"); method = msg.get("method")
        if method == "initialize":
            send({"jsonrpc":"2.0","id":mid,"result":{"protocolVersion":"2024-11-05",
                  "capabilities":{},"serverInfo":{"name":"silent","version":"1"}}})
        elif method == "notifications/initialized":
            pass
        elif method == "tools/list":
            send({"jsonrpc":"2.0","id":mid,"result":{"tools":[
                  {"name":"hang","description":"never replies","inputSchema":{"type":"object"}}]}})
        # tools/call:故意永不回应(server 活着但沉默)
''')


def test_silent_server_call_times_out_not_hangs(tmp_path, monkeypatch):
    """#3 排查修复:server 应答握手却对 tools/call 永不回应(活着但沉默)→ call() 必须按
    _CALL_TIMEOUT_S 超时返回诚实错误,而不是无界 readline 冻死 run(及 daemon 路径的 host loop)。"""
    import time

    import argos.mcp_native as mcp_native
    monkeypatch.setattr(mcp_native, "_CALL_TIMEOUT_S", 0.5)
    server = tmp_path / "silent_server.py"
    server.write_text(_SILENT_CALL_SERVER, encoding="utf-8")
    cfg = tmp_path / "mcp.json"
    cfg.write_text(json.dumps({
        "servers": {"silent": {"command": sys.executable, "args": [str(server)]}}
    }), encoding="utf-8")
    mgr = McpManager(config_path=cfg)
    try:
        assert len(mgr.list_tools()) == 1, "握手应成功(initialize/tools/list 正常应答)"
        t0 = time.time()
        out = mgr.call("silent", "hang", {})
        dt = time.time() - t0
        assert "超时" in out or "TimeoutError" in out, out
        assert dt < 5.0, f"应在 ~0.5s 超时,实际 {dt:.1f}s —— 无界挂起未修复"
    finally:
        mgr.close()


# ── ② 真 server 端到端 ────────────────────────────────────────────────────────
def test_real_echo_server_end_to_end(tmp_path):
    cfg = _write_echo_config(tmp_path)
    mgr = McpManager(config_path=cfg)
    try:
        tools = mgr.list_tools()
        assert len(tools) == 1
        assert tools[0].server == "echo" and tools[0].name == "echo"
        assert "echo back" in tools[0].description
        # tools_summary 给系统提示用(含 server/tool + 描述)。
        summary = mgr.tools_summary()
        assert "echo/echo" in summary and "Available MCP tools" in summary
        # 真调用 → 走完整 JSON-RPC 往返,server 回 ECHO:hello。
        out = mgr.call("echo", "echo", {"text": "hello"})
        assert out == "ECHO:hello"
        # 第二次调用(验证持久连接 + id 递增不串台)。
        assert mgr.call("echo", "echo", {"text": "world"}) == "ECHO:world"
    finally:
        mgr.close()


def test_unknown_server_and_tool(tmp_path):
    cfg = _write_echo_config(tmp_path)
    mgr = McpManager(config_path=cfg)
    try:
        out = mgr.call("nope", "echo", {})
        assert "未知 MCP server" in out and "echo" in out  # 列出可用 server
    finally:
        mgr.close()


# ── ③ 畸形 config 诚实降级 ────────────────────────────────────────────────────
def test_malformed_config_degrades(tmp_path):
    cfg = tmp_path / "mcp.json"
    cfg.write_text("{ not valid json ", encoding="utf-8")
    mgr = McpManager(config_path=cfg)
    assert mgr.list_tools() == []      # 畸形 = 等于零 MCP,不抛
    mgr.close()


def test_bad_command_server_marked_unavailable(tmp_path):
    cfg = tmp_path / "mcp.json"
    cfg.write_text(json.dumps({
        "servers": {"broken": {"command": "/nonexistent/binary/xyz", "args": []}}
    }), encoding="utf-8")
    mgr = McpManager(config_path=cfg)
    try:
        assert mgr.list_tools() == []                  # 连不上 → 无工具
        out = mgr.call("broken", "x", {})
        assert "不可用" in out                          # 诚实报不可用 + 原因
    finally:
        mgr.close()


# ── ④ broker 路由 ─────────────────────────────────────────────────────────────
def test_broker_routes_mcp_call(monkeypatch):
    from argos.sandbox.broker import CapabilityBroker, _RISK

    captured = {}

    class FakeMgr:
        def call(self, server, tool, arguments):
            captured["args"] = (server, tool, arguments)
            return "MCP RESULT"

    monkeypatch.setattr("argos.mcp_native.get_manager", lambda: FakeMgr())
    broker = object.__new__(CapabilityBroker)
    broker._mcp_manager = None        # 无注入 → fallback 到 monkeypatched get_manager
    broker._browser_controller = None  # 无注入 → 此测试不走 browser_*
    val, _exit = broker._execute("mcp_call", {"server": "s", "tool": "t", "arguments": {"a": 1}})
    assert val == "MCP RESULT"
    assert captured["args"] == ("s", "t", {"a": 1})
    assert "mcp_call" in _RISK


def test_broker_mcp_call_coerces_non_dict_arguments(monkeypatch):
    from argos.sandbox.broker import CapabilityBroker

    class FakeMgr:
        def call(self, server, tool, arguments):
            return f"args={arguments!r}"

    monkeypatch.setattr("argos.mcp_native.get_manager", lambda: FakeMgr())
    broker = object.__new__(CapabilityBroker)
    broker._mcp_manager = None        # 无注入 → fallback 到 monkeypatched get_manager
    broker._browser_controller = None  # 无注入 → 此测试不走 browser_*
    # arguments 不是 dict(模型瞎传)→ 强制成 {},不崩。
    val, _ = broker._execute("mcp_call", {"server": "s", "tool": "t", "arguments": "oops"})
    assert val == "args={}"
