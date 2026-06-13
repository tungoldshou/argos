"""6 个 broker-gated LSP 工具 e2e(用 in-process fake server 模拟 pyright,slow)。

跳过条件:用 fake 替 pyright,所以不需要 pyright-langserver 二进制。"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from urllib.parse import quote

import pytest

from argos.lsp.client import LspClient, encode_frame
from argos.lsp.config import LspConfig, LspServerConfig
from argos.lsp.manager import LspManager, set_spawn_proc_fn, set_event_emit_fn
from argos.lsp.tools import (
    lsp_definition_gated, lsp_references_gated, lsp_hover_gated,
    lsp_document_symbols_gated, lsp_workspace_symbols_gated,
    lsp_diagnostics_gated,
)
from test_lsp_manager import _FakeProc, _read_one_frame


def _make_route_handler() -> dict:
    """返一个 route handler,模拟 pyright 返回定义/引用/hover/symbols 的合理 shape。"""
    return {
        "textDocument/definition": [{
            "uri": "file:///tmp/lsp-e2e/a.py",
            "range": {"start": {"line": 0, "character": 4},
                      "end": {"line": 0, "character": 7}},
        }],
        "textDocument/references": [
            {"uri": "file:///tmp/lsp-e2e/a.py",
             "range": {"start": {"line": 0, "character": 0},
                       "end": {"line": 0, "character": 3}}},
            {"uri": "file:///tmp/lsp-e2e/a.py",
             "range": {"start": {"line": 2, "character": 0},
                       "end": {"line": 2, "character": 3}}},
        ],
        "textDocument/hover": {"contents": {"kind": "markdown", "value": "**def** foo()"},
                                "range": None},
        "textDocument/documentSymbol": [
            {"name": "foo", "kind": 12, "range": {
                "start": {"line": 0, "character": 0},
                "end": {"line": 1, "character": 8}}},
        ],
        "workspace/symbol": [
            {"name": "foo_unique", "kind": 12, "location": {
                "uri": "file:///tmp/lsp-e2e/a.py",
                "range": {"start": {"line": 0, "character": 4},
                          "end": {"line": 0, "character": 14}}}},
        ],
    }


@pytest.fixture
def fake_lsp(tmp_path, monkeypatch):
    """起 fake server,route handler 模拟 pyright,workspace = tmp_path。"""
    handlers = _make_route_handler()
    tasks: list[asyncio.Task] = []

    async def _serve(stream):
        first = await _read_one_frame(stream)
        await stream.send(encode_frame({
            "jsonrpc": "2.0", "id": first["id"],
            "result": {"capabilities": {}},
        }))
        while True:
            msg = await _read_one_frame(stream)
            if msg is None:
                return
            if msg.get("id") is not None:
                method = msg.get("method", "")
                # 处理 diagnostics 推送(等真有 server 时用,本测试不验)
                if method == "textDocument/didOpen" or method == "textDocument/didChange":
                    await stream.send(encode_frame({
                        "jsonrpc": "2.0", "id": msg["id"], "result": None,
                    }))
                    continue
                if method in handlers:
                    await stream.send(encode_frame({
                        "jsonrpc": "2.0", "id": msg["id"],
                        "result": handlers[method],
                    }))
                else:
                    await stream.send(encode_frame({
                        "jsonrpc": "2.0", "id": msg["id"], "result": None,
                    }))

    async def _spawn(self, name, sc, env, cwd):
        proc = _FakeProc()
        client = LspClient(proc)
        tasks.append(asyncio.create_task(_serve(proc.stream)))
        return proc, client

    set_spawn_proc_fn(_spawn)
    set_event_emit_fn(None)
    # 写一个测试 file 到 workspace
    f = tmp_path / "a.py"
    f.write_text("def foo():\n    pass\n\nfoo()\n")
    yield tmp_path
    set_spawn_proc_fn(None)
    for t in tasks:
        t.cancel()


@pytest.mark.asyncio
@pytest.mark.slow
async def test_lsp_definition_returns_location(fake_lsp):
    """lsp_definition → JSON 含 locations[] 列表(1+ 个)。"""
    ws = fake_lsp
    cfg = LspConfig(servers={
        "python": LspServerConfig(command=("fake",), filetypes=(".py",)),
    })
    mgr = LspManager(cfg)
    r = json.loads(lsp_definition_gated(
        server_name="python", file="a.py", line=4, col=1,
        manager=mgr, workspace=ws,
    ))
    assert "locations" in r
    assert len(r["locations"]) >= 1
    assert r["locations"][0]["line"] >= 1


@pytest.mark.asyncio
@pytest.mark.slow
async def test_lsp_references_returns_list(fake_lsp):
    """lsp_references → JSON 含 locations[](2 个:def + 调)。"""
    ws = fake_lsp
    cfg = LspConfig(servers={
        "python": LspServerConfig(command=("fake",), filetypes=(".py",)),
    })
    mgr = LspManager(cfg)
    r = json.loads(lsp_references_gated(
        server_name="python", file="a.py", line=1, col=5,
        include_declaration=True, manager=mgr, workspace=ws,
    ))
    assert "locations" in r
    assert len(r["locations"]) >= 2


@pytest.mark.asyncio
@pytest.mark.slow
async def test_lsp_hover_returns_markdown(fake_lsp):
    """lsp_hover → JSON 含 contents 字段(可能空 markdown)。"""
    ws = fake_lsp
    cfg = LspConfig(servers={
        "python": LspServerConfig(command=("fake",), filetypes=(".py",)),
    })
    mgr = LspManager(cfg)
    r = json.loads(lsp_hover_gated(
        server_name="python", file="a.py", line=1, col=5,
        manager=mgr, workspace=ws,
    ))
    assert "contents" in r
    assert isinstance(r["contents"], str)


@pytest.mark.asyncio
@pytest.mark.slow
async def test_lsp_document_symbols_returns_list(fake_lsp):
    """lsp_document_symbols → JSON 含 symbols[] 列表(>= 1 个)。"""
    ws = fake_lsp
    cfg = LspConfig(servers={
        "python": LspServerConfig(command=("fake",), filetypes=(".py",)),
    })
    mgr = LspManager(cfg)
    r = json.loads(lsp_document_symbols_gated(
        server_name="python", file="a.py", manager=mgr, workspace=ws,
    ))
    assert "symbols" in r
    assert len(r["symbols"]) >= 1
    assert r["symbols"][0]["name"] == "foo"
    assert r["symbols"][0]["kind"] == "Function"


@pytest.mark.asyncio
@pytest.mark.slow
async def test_lsp_workspace_symbols_returns_list(fake_lsp):
    """lsp_workspace_symbols(query) → JSON 含 symbols[](含匹配的 name)。"""
    ws = fake_lsp
    cfg = LspConfig(servers={
        "python": LspServerConfig(command=("fake",), filetypes=(".py",)),
    })
    mgr = LspManager(cfg)
    r = json.loads(lsp_workspace_symbols_gated(
        server_name="python", query="foo", manager=mgr, workspace=ws,
    ))
    assert "symbols" in r
    names = [s.get("name", "") for s in r["symbols"]]
    assert any("foo" in n for n in names)


@pytest.mark.asyncio
@pytest.mark.slow
async def test_lsp_diagnostics_returns_empty_list_when_no_diag(fake_lsp):
    """无 diagnostics 推送时 → lsp_diagnostics 返空 list(不抛)。"""
    ws = fake_lsp
    cfg = LspConfig(servers={
        "python": LspServerConfig(command=("fake",), filetypes=(".py",)),
    })
    mgr = LspManager(cfg)
    r = json.loads(lsp_diagnostics_gated(
        server_name="python", file="a.py", manager=mgr, workspace=ws,
    ))
    assert "diagnostics" in r
    assert isinstance(r["diagnostics"], list)
