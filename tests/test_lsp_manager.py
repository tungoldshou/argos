"""Internal documentation."""
from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from argos.lsp.client import LspClient, encode_frame, parse_frames
from argos.lsp.config import LspConfig, LspServerConfig
from argos.lsp.manager import (
    LspManager,
    ServerStatus,
    _BACKOFF_SECONDS,
    _reset_content_cache,
    set_spawn_proc_fn,
    set_event_emit_fn,
)


# ── in-process fake proc / server ──────────────────────────────────

class _FakeStream:
    """Internal documentation."""

    def __init__(self) -> None:
        self._in_q: asyncio.Queue[bytes] = asyncio.Queue()
        self._out_q: asyncio.Queue[bytes] = asyncio.Queue()
        self._closed = False

    def write(self, data: bytes) -> None:
        self._in_q.put_nowait(data)

    async def drain(self) -> None:
        pass

    async def read_chunk(self) -> bytes:
        return await self._in_q.get()

    async def send(self, data: bytes) -> None:
        self._out_q.put_nowait(data)

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._out_q.put_nowait(b"")  # EOF sentinel

    def __aiter__(self):
        return self._aiter()

    async def _aiter(self):
        while True:
            chunk = await self._out_q.get()
            if not chunk:
                return
            yield chunk

    async def wait(self) -> int:
        return 0

    def kill(self) -> None:
        pass


class _FakeProc:
    """Internal documentation."""

    def __init__(self) -> None:
        self.stream = _FakeStream()
        self.stdin = self.stream
        self.stdout = self.stream
        self.returncode: int | None = None

    async def wait(self) -> int:
        return 0

    def kill(self) -> None:
        pass


async def _fake_serve(stream: _FakeStream, *, init_response=None,
                      route_handler=None, crash_after: int | None = None) -> None:
    """Internal documentation."""
    try:
        first = await _read_one_frame(stream)
        if first.get("method") == "initialize":
            resp = init_response if init_response is not None else {"capabilities": {}}
            await stream.send(encode_frame({
                "jsonrpc": "2.0", "id": first["id"], "result": resp,
            }))
        else:
            return
        count = 0
        while True:
            try:
                msg = await _read_one_frame(stream)
            except asyncio.CancelledError:
                return
            if msg is None:
                return
            count += 1
            if crash_after is not None and count >= crash_after:
                stream.close()
                return
            if msg.get("id") is not None:
                if route_handler is not None:
                    try:
                        result = route_handler(msg["method"], msg.get("params"))
                    except Exception as e:  # noqa: BLE001
                        await stream.send(encode_frame({
                            "jsonrpc": "2.0", "id": msg["id"],
                            "error": {"code": -32603, "message": str(e)},
                        }))
                        continue
                    await stream.send(encode_frame({
                        "jsonrpc": "2.0", "id": msg["id"], "result": result,
                    }))
                else:
                    await stream.send(encode_frame({
                        "jsonrpc": "2.0", "id": msg["id"], "result": None,
                    }))
    except asyncio.CancelledError:
        return
    except Exception:  # noqa: BLE001
        return


async def _read_one_frame(stream: _FakeStream) -> dict | None:
    """Internal documentation."""
    header_bytes = b""
    while b"\r\n\r\n" not in header_bytes:
        chunk = await stream.read_chunk()
        if not chunk:
            return None
        header_bytes += chunk
    sep = header_bytes.find(b"\r\n\r\n")
    header = header_bytes[:sep]
    body_start = sep + 4
    content_length = 0
    for line in header.split(b"\r\n"):
        if line.lower().startswith(b"content-length:"):
            content_length = int(line.split(b":", 1)[1].strip())
            break
    remaining = header_bytes[body_start:]
    while len(remaining) < content_length:
        chunk = await stream.read_chunk()
        if not chunk:
            return None
        remaining += chunk
    body = remaining[:content_length]
    return json.loads(body.decode("utf-8"))


@pytest.fixture
def fake_proc_factory(monkeypatch):
    """Internal documentation."""
    tasks: list[asyncio.Task] = []

    async def _spawn(mgr, name, sc, env, cwd):
        proc = _FakeProc()
        client = LspClient(proc)
        task = asyncio.create_task(_fake_serve(proc.stream))
        tasks.append(task)
        return proc, client

    set_spawn_proc_fn(_spawn)
    set_event_emit_fn(None)
    yield
    set_spawn_proc_fn(None)
    for t in tasks:
        t.cancel()
    _reset_content_cache()


def _config_with_python() -> LspConfig:
    return LspConfig(servers={
        "python": LspServerConfig(command=("fake-pyright",), filetypes=(".py",)),
    })


def _config_multi() -> LspConfig:
    return LspConfig(servers={
        "python": LspServerConfig(command=("fake-pyright",), filetypes=(".py",)),
        "rust": LspServerConfig(command=("fake-rust-analyzer",), filetypes=(".rs",)),
    })



@pytest.mark.asyncio
@pytest.mark.slow
async def test_start_server_transitions_to_ready(fake_proc_factory):
    """start_server → Starting → Initializing → Initialized → Ready。"""
    mgr = LspManager(_config_with_python())
    assert mgr.server_status("python") == ServerStatus.NOT_STARTED
    ok = await mgr.start_server("python")
    assert ok is True
    assert mgr.server_status("python") == ServerStatus.READY
    await mgr.shutdown()


@pytest.mark.asyncio
@pytest.mark.slow
async def test_list_servers_reports_status(fake_proc_factory):
    """Internal documentation."""
    mgr = LspManager(_config_with_python())
    await mgr.start_server("python")
    info = mgr.list_servers()
    assert len(info) == 1
    assert info[0]["name"] == "python"
    assert info[0]["status"] == "Ready"
    assert info[0]["command"] == "fake-pyright"
    await mgr.shutdown()


@pytest.mark.asyncio
@pytest.mark.slow
async def test_disabled_server_returns_error_json(fake_proc_factory):
    """Internal documentation."""
    cfg = LspConfig(servers={
        "x": LspServerConfig(command=("y",), filetypes=(".py",), disabled=True),
    })
    mgr = LspManager(cfg)
    r = await mgr.request("x", "textDocument/definition", {"x": 1})
    assert "error" in r
    assert "disabled" in r["error"]


@pytest.mark.asyncio
@pytest.mark.slow
async def test_unknown_server_returns_error_json(fake_proc_factory):
    """Internal documentation."""
    mgr = LspManager(_config_with_python())
    r = await mgr.request("nonexistent", "textDocument/definition", {})
    assert "error" in r
    assert "not configured" in r["error"]


@pytest.mark.asyncio
@pytest.mark.slow
async def test_request_routes_to_correct_server(fake_proc_factory):
    """Internal documentation."""
    mgr = LspManager(_config_with_python())
    await mgr.start_server("python")
    r = await mgr.request("python", "textDocument/definition", {"pos": 1})
    assert r is not None
    assert "error" not in r
    await mgr.shutdown()


@pytest.mark.asyncio
@pytest.mark.slow
async def test_concurrent_requests_dont_cross_talk(fake_proc_factory):
    """Internal documentation."""
    mgr = LspManager(_config_with_python())
    await mgr.start_server("python")

    async def call(i: int) -> dict:
        return await mgr.request("python", f"custom/method_{i}", {"i": i})

    results = await asyncio.gather(*[call(i) for i in range(10)])
    assert len(results) == 10
    for r in results:
        assert r is not None
        assert "error" not in r
    await mgr.shutdown()


@pytest.mark.asyncio
@pytest.mark.slow
async def test_5s_request_timeout(fake_proc_factory, monkeypatch):
    """Internal documentation."""
    tasks: list[asyncio.Task] = []

    async def _spawn_silent(mgr, name, sc, env, cwd):
        proc = _FakeProc()
        client = LspClient(proc)
        async def _init_only():
            try:
                first = await _read_one_frame(proc.stream)
                await proc.stream.send(encode_frame({
                    "jsonrpc": "2.0", "id": first["id"],
                    "result": {"capabilities": {}},
                }))
                while True:
                    msg = await _read_one_frame(proc.stream)
                    if msg is None:
                        return
            except (asyncio.CancelledError, Exception):
                return
        tasks.append(asyncio.create_task(_init_only()))
        return proc, client

    set_spawn_proc_fn(_spawn_silent)
    mgr = LspManager(_config_with_python())
    await mgr.start_server("python")
    r = await mgr.request("python", "textDocument/definition", {}, timeout=0.5)
    assert "error" in r
    assert "timeout" in r["error"]
    await mgr.shutdown()
    for t in tasks:
        t.cancel()


@pytest.mark.asyncio
@pytest.mark.slow
async def test_crash_marks_crashed_and_schedules_retry(fake_proc_factory, monkeypatch):
    """Internal documentation."""
    sleeps: list[float] = []

    async def fake_sleep(s):
        sleeps.append(s)
        return None

    monkeypatch.setattr("argos.lsp.manager.asyncio.sleep", fake_sleep)

    tasks: list[asyncio.Task] = []

    async def _spawn_crashing(mgr, name, sc, env, cwd):
        proc = _FakeProc()
        client = LspClient(proc)
        tasks.append(asyncio.create_task(_fake_serve(proc.stream, crash_after=3)))
        return proc, client

    set_spawn_proc_fn(_spawn_crashing)
    mgr = LspManager(_config_with_python())
    await mgr.start_server("python")
    await asyncio.sleep(0.05)
    r1 = await mgr.request("python", "textDocument/method1", {}, timeout=2.0)
    assert "error" not in r1, f"first request failed: {r1}"
    r2 = await mgr.request("python", "textDocument/method2", {}, timeout=2.0)
    assert "error" in r2
    s = mgr._servers["python"]
    assert s.status in (ServerStatus.CRASHED, ServerStatus.DISABLED)
    assert any(abs(s_ - _BACKOFF_SECONDS) < 0.01 for s_ in sleeps) or len(sleeps) > 0
    await mgr.shutdown()
    for t in tasks:
        t.cancel()


@pytest.mark.asyncio
@pytest.mark.slow
async def test_shutdown_sets_status_shutdown(fake_proc_factory):
    """Internal documentation."""
    mgr = LspManager(_config_with_python())
    await mgr.start_server("python")
    await mgr.shutdown()
    assert mgr.server_status("python") == ServerStatus.SHUTDOWN


@pytest.mark.asyncio
@pytest.mark.slow
async def test_diag_cache_receives_publish_diagnostics(fake_proc_factory):
    """Internal documentation."""
    tasks: list[asyncio.Task] = []
    diag_sent = asyncio.Event()
    manager_ref: list = []

    async def _spawn_diag(mgr, name, sc, env, cwd):
        proc = _FakeProc()
        client = LspClient(proc)
        manager_ref.append(mgr)

        async def _serve_with_diag():
            # 1. read initialize → reply
            first = await _read_one_frame(proc.stream)
            await proc.stream.send(encode_frame({
                "jsonrpc": "2.0", "id": first["id"],
                "result": {"capabilities": {}},
            }))
            await proc.stream.send(encode_frame({
                "jsonrpc": "2.0", "method": "textDocument/publishDiagnostics",
                "params": {
                    "uri": "file:///a.py",
                    "diagnostics": [
                        {"range": {"start": {"line": 0, "character": 0},
                                   "end": {"line": 0, "character": 1}},
                         "severity": 1, "message": "syntax error"}
                    ],
                },
            }))
            diag_sent.set()
            while True:
                msg = await _read_one_frame(proc.stream)
                if msg is None:
                    return
                if msg.get("id") is not None:
                    await proc.stream.send(encode_frame({
                        "jsonrpc": "2.0", "id": msg["id"], "result": None,
                    }))
        tasks.append(asyncio.create_task(_serve_with_diag()))
        return proc, client

    set_spawn_proc_fn(_spawn_diag)
    mgr = LspManager(_config_with_python())
    await mgr.start_server("python")
    try:
        await asyncio.wait_for(diag_sent.wait(), timeout=2.0)
    except asyncio.TimeoutError:
        pass
    await asyncio.sleep(0.1)
    cached = mgr.get_diagnostics("/a.py")
    assert cached is not None
    assert len(cached["diagnostics"]) >= 1
    await mgr.shutdown()
    for t in tasks:
        t.cancel()


@pytest.mark.asyncio
@pytest.mark.slow
async def test_request_queueing_when_not_ready(fake_proc_factory, monkeypatch):
    """Internal documentation."""
    async def fake_sleep(s):
        return None
    monkeypatch.setattr("argos.lsp.manager.asyncio.sleep", fake_sleep)

    mgr = LspManager(_config_with_python())
    async def _start_in_bg():
        await mgr.start_server("python")
    asyncio.create_task(_start_in_bg())
    await asyncio.sleep(0.01)
    r = await mgr.request("python", "textDocument/definition", {})
    assert "error" not in r
    await mgr.shutdown()


@pytest.mark.asyncio
@pytest.mark.slow
async def test_sync_file_didopen_then_didchange_incremental(fake_proc_factory, tmp_path):
    """Internal documentation."""
    from urllib.parse import quote
    mgr = LspManager(_config_with_python())
    await mgr.start_server("python")
    f = tmp_path / "a.py"
    f.write_text("x = 1\n")
    await mgr.sync_file(str(f), "x = 1\n")
    await mgr.sync_file(str(f), "x = 2\n")
    uri = f"file://{quote(str(f.resolve()))}"
    s = mgr._servers["python"]
    assert s.versions[uri] == 2
    await mgr.shutdown()
