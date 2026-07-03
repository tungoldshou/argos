from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path

import pytest

from argos.mcp_native import McpManager


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


def test_zero_config_is_honest(tmp_path):
    mgr = McpManager(config_path=tmp_path / "nonexistent.json")
    assert mgr.list_tools() == []
    assert mgr.tools_summary() == ""
    out = mgr.call("whatever", "tool", {})
    assert "未配置任何 MCP server" in out
    mgr.close()


def test_zero_config_error_mentions_configured_path(tmp_path):
    cfg_dir = tmp_path / "custom-config"
    cfg_path = cfg_dir / "mcp.json"
    mgr = McpManager(config_path=cfg_path)
    try:
        out = mgr.call("whatever", "tool", {})
    finally:
        mgr.close()

    assert str(cfg_path) in out
    assert "~/.argos" not in out


def test_default_path_honors_argos_config_dir(tmp_path, monkeypatch):
    import argos.mcp_native as mcp_native

    cfg_dir = tmp_path / ".argos"
    cfg_dir.mkdir()
    (cfg_dir / "mcp.json").write_text(json.dumps({"servers": {}}), encoding="utf-8")
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(cfg_dir))
    monkeypatch.setattr(mcp_native, "CONFIG_PATH", None)

    mgr = McpManager()
    try:
        assert mgr._config_path == cfg_dir / "mcp.json"
    finally:
        mgr.close()


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
        # tools/call intentionally never replies while the server stays alive.
''')


def test_silent_server_call_times_out_not_hangs(tmp_path, monkeypatch):
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


def test_real_echo_server_end_to_end(tmp_path):
    cfg = _write_echo_config(tmp_path)
    mgr = McpManager(config_path=cfg)
    try:
        tools = mgr.list_tools()
        assert len(tools) == 1
        assert tools[0].server == "echo" and tools[0].name == "echo"
        assert "echo back" in tools[0].description
        summary = mgr.tools_summary()
        assert "echo/echo" in summary and "Available MCP tools" in summary
        out = mgr.call("echo", "echo", {"text": "hello"})
        assert out == "ECHO:hello"
        assert mgr.call("echo", "echo", {"text": "world"}) == "ECHO:world"
    finally:
        mgr.close()


def test_unknown_server_and_tool(tmp_path):
    cfg = _write_echo_config(tmp_path)
    mgr = McpManager(config_path=cfg)
    try:
        out = mgr.call("nope", "echo", {})
        assert "未知 MCP server" in out and "echo" in out
    finally:
        mgr.close()


def test_malformed_config_degrades(tmp_path):
    cfg = tmp_path / "mcp.json"
    cfg.write_text("{ not valid json ", encoding="utf-8")
    mgr = McpManager(config_path=cfg)
    assert mgr.list_tools() == []
    mgr.close()


def test_bad_command_server_marked_unavailable(tmp_path):
    cfg = tmp_path / "mcp.json"
    cfg.write_text(json.dumps({
        "servers": {"broken": {"command": "/nonexistent/binary/xyz", "args": []}}
    }), encoding="utf-8")
    mgr = McpManager(config_path=cfg)
    try:
        assert mgr.list_tools() == []
        out = mgr.call("broken", "x", {})
        assert "不可用" in out
    finally:
        mgr.close()


def test_broker_routes_mcp_call(monkeypatch):
    from argos.sandbox.broker import CapabilityBroker, _RISK

    captured = {}

    class FakeMgr:
        def call(self, server, tool, arguments):
            captured["args"] = (server, tool, arguments)
            return "MCP RESULT"

    monkeypatch.setattr("argos.mcp_native.get_manager", lambda: FakeMgr())
    broker = object.__new__(CapabilityBroker)
    broker._mcp_manager = None
    broker._browser_controller = None
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
    broker._mcp_manager = None
    broker._browser_controller = None
    val, _ = broker._execute("mcp_call", {"server": "s", "tool": "t", "arguments": "oops"})
    assert val == "args={}"
