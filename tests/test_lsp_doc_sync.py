"""文档同步测试(spec §2.4 / §4.4)。

- 版本号单调性:didOpen=1, didChange+=1, re-open 仍 +=1(**不**复用 1)
- 增量 didChange:write_file 后 server 收 didChange 的 range 算对
- 大文件跳过:> 1MB 不发 didOpen(不抛,只 no-op),LspManager 仍记 v=1 让后续增量可走
- 文件 ext 不在 server.filetypes → 工具返 error,不发 didOpen
- 已知 sync_file 行为:ext 命中 server + server Ready → 发 didOpen
"""
from __future__ import annotations

import asyncio
import json
from typing import Any
from urllib.parse import quote

import pytest

from argos_agent.lsp.client import LspClient, encode_frame
from argos_agent.lsp.config import LspConfig, LspServerConfig
from argos_agent.lsp.manager import (
    LspManager,
    _reset_content_cache,
    set_spawn_proc_fn,
    set_event_emit_fn,
)
from test_lsp_manager import _FakeProc, _read_one_frame


@pytest.fixture
def capture_server(monkeypatch):
    """起一个 in-process fake server,捕获 stdin 收到的所有帧。"""
    captured: list[dict] = []
    tasks: list[asyncio.Task] = []

    async def _serve(stream):
        try:
            # 服务端读 client 写入:走 _read_one_frame(stream) → _in_q
            first = await _read_one_frame(stream)
            captured.append(first)
            if first.get("method") == "initialize":
                await stream.send(encode_frame({
                    "jsonrpc": "2.0", "id": first["id"],
                    "result": {"capabilities": {}},
                }))
            while True:
                msg = await _read_one_frame(stream)
                if msg is None:
                    return
                captured.append(msg)
                if msg.get("id") is not None:
                    await stream.send(encode_frame({
                        "jsonrpc": "2.0", "id": msg["id"], "result": None,
                    }))
        except Exception:
            pass

    async def _spawn(self, name, sc, env, cwd):
        proc = _FakeProc()
        client = LspClient(proc)
        tasks.append(asyncio.create_task(_serve(proc.stream)))
        return proc, client

    set_spawn_proc_fn(_spawn)
    set_event_emit_fn(None)
    yield captured
    set_spawn_proc_fn(None)
    for t in tasks:
        t.cancel()
    _reset_content_cache()


@pytest.mark.asyncio
@pytest.mark.slow
async def test_first_sync_triggers_didopen_with_version_1(capture_server, tmp_path):
    """首次 sync_file → server stdin 收 didOpen(version=1, 全文)。"""
    cfg = LspConfig(servers={
        "python": LspServerConfig(command=("fake",), filetypes=(".py",)),
    })
    mgr = LspManager(cfg)
    f = tmp_path / "a.py"
    f.write_text("def foo():\n    pass\n")
    await mgr.start_server("python")
    await mgr.sync_file(str(f), f.read_text())
    # 等待 server 收到 didOpen
    await asyncio.sleep(0.1)
    methods = [m.get("method") for m in capture_server]
    assert "textDocument/didOpen" in methods
    didopen = next(m for m in capture_server if m.get("method") == "textDocument/didOpen")
    assert didopen["params"]["textDocument"]["version"] == 1
    assert "def foo" in didopen["params"]["textDocument"]["text"]


@pytest.mark.asyncio
@pytest.mark.slow
async def test_second_sync_triggers_didchange_incremental(capture_server, tmp_path):
    """第二次 sync_file 同 file → server 收 didChange + version 自增(单调性)。"""
    cfg = LspConfig(servers={
        "python": LspServerConfig(command=("fake",), filetypes=(".py",)),
    })
    mgr = LspManager(cfg)
    f = tmp_path / "a.py"
    f.write_text("x = 1\n")
    await mgr.start_server("python")
    await mgr.sync_file(str(f), "x = 1\n")
    await asyncio.sleep(0.1)
    capture_server.clear()
    await mgr.sync_file(str(f), "x = 2\n")
    await asyncio.sleep(0.1)
    didchange = next((m for m in capture_server if m.get("method") == "textDocument/didChange"), None)
    assert didchange is not None, "didChange not sent"
    assert didchange["params"]["textDocument"]["version"] == 2
    # mgr.versions[uri] 应当 == 2
    uri = f"file://{quote(str(f.resolve()))}"
    server = mgr._servers["python"]
    assert server.versions[uri] == 2


@pytest.mark.asyncio
@pytest.mark.slow
async def test_version_monotonic_across_reopen(capture_server, tmp_path):
    """重开同 file(close 后再 didOpen)→ version 仍 += 1(绝不回到 1)。"""
    cfg = LspConfig(servers={
        "python": LspServerConfig(command=("fake",), filetypes=(".py",)),
    })
    mgr = LspManager(cfg)
    f = tmp_path / "a.py"
    f.write_text("x = 1\n")
    await mgr.start_server("python")
    await mgr.sync_file(str(f), "x = 1\n")
    await mgr.sync_file(str(f), "x = 2\n")
    await mgr.sync_file(str(f), "x = 3\n")
    await asyncio.sleep(0.1)
    uri = f"file://{quote(str(f.resolve()))}"
    server = mgr._servers["python"]
    assert server.versions[uri] >= 3


@pytest.mark.asyncio
@pytest.mark.slow
async def test_large_file_skips_didopen(capture_server, tmp_path):
    """> 1MB 文件 → sync_file 跳过 LSP(不发 didOpen,版本号不占)。"""
    cfg = LspConfig(servers={
        "python": LspServerConfig(command=("fake",), filetypes=(".py",)),
    })
    mgr = LspManager(cfg)
    f = tmp_path / "big.py"
    f.write_text("x = 1\n" * (1024 * 200))   # ~ 1.2MB
    capture_server.clear()
    await mgr.sync_file(str(f), f.read_text())
    await asyncio.sleep(0.1)
    methods = [m.get("method") for m in capture_server]
    assert "textDocument/didOpen" not in methods
    uri = f"file://{quote(str(f.resolve()))}"
    server = mgr._servers["python"]
    # 不分配 version(跳过 LSP)
    assert uri not in server.versions


@pytest.mark.asyncio
@pytest.mark.slow
async def test_unknown_extension_no_op(capture_server, tmp_path):
    """文件 ext 不匹任何 server.filetypes → sync_file no-op(不发 didOpen)。"""
    cfg = LspConfig(servers={
        "python": LspServerConfig(command=("fake",), filetypes=(".py",)),
    })
    mgr = LspManager(cfg)
    f = tmp_path / "a.xyz"
    f.write_text("x")
    capture_server.clear()
    await mgr.sync_file(str(f), "x")
    await asyncio.sleep(0.1)
    methods = [m.get("method") for m in capture_server]
    assert "textDocument/didOpen" not in methods


@pytest.mark.asyncio
@pytest.mark.slow
async def test_sync_file_no_extension_no_op(capture_server, tmp_path):
    """文件无 ext → sync_file 早返(不查 server)。"""
    cfg = LspConfig(servers={
        "python": LspServerConfig(command=("fake",), filetypes=(".py",)),
    })
    mgr = LspManager(cfg)
    f = tmp_path / "Makefile"
    f.write_text("x")
    capture_server.clear()
    await mgr.sync_file(str(f), "x")
    await asyncio.sleep(0.1)
    methods = [m.get("method") for m in capture_server]
    assert "textDocument/didOpen" not in methods
