"""MCP 接线测试:/mcp/servers 端点 + 工具合并进 agent。"""
import pytest
from fastapi.testclient import TestClient

from argos_agent import server, mcp_client


def test_mcp_servers_endpoint_returns_status(monkeypatch):
    fake_status = [
        {"name": "filesystem", "status": "connected", "tools": 11, "transport": "stdio", "trust": "builtin", "desc": "fs"},
        {"name": "github", "status": "disabled", "tools": 0, "transport": "stdio", "trust": "builtin", "desc": "gh"},
    ]

    async def fake_ensure():
        return None
    monkeypatch.setattr(mcp_client, "ensure_loaded", fake_ensure)
    monkeypatch.setattr(mcp_client, "server_status", lambda: fake_status)

    client = TestClient(server.app)
    r = client.get("/mcp/servers")
    assert r.status_code == 200
    body = r.json()
    assert body["servers"] == fake_status


@pytest.mark.asyncio
async def test_run_merges_mcp_tools_into_agent(monkeypatch):
    """_run_stream 应把内置 ALL_TOOLS + MCP 工具一起传给 build_agent_with_gate。"""
    from argos_agent import tools as tools_mod
    captured = {}

    class _FakeAgent:
        async def astream(self, _inp, stream_mode=None):
            from langchain_core.messages import AIMessage
            yield ("values", {"messages": [AIMessage(content="hi")]})

    def fake_build(tools=None, **kw):
        captured["tools"] = tools
        return _FakeAgent(), None

    async def fake_ensure():
        return None
    sentinel = object()
    monkeypatch.setattr(mcp_client, "ensure_loaded", fake_ensure)
    monkeypatch.setattr(mcp_client, "mcp_tools", lambda: [sentinel])
    monkeypatch.setattr(server, "build_agent_with_gate", fake_build)
    server.SESSIONS.clear()

    gen = server._run_stream("做点事")
    async for _ in gen:
        pass
    # 合并后的工具集应同时含内置工具和 MCP sentinel
    assert sentinel in captured["tools"]
    assert all(t in captured["tools"] for t in tools_mod.ALL_TOOLS)
