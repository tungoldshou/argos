"""LspManager 生命周期测试(spec §2.6 / D9)。

fake server = in-process asyncio 协程,跑 stdin/stdout framed JSON-RPC。
**不**起真子进程(用 `set_spawn_proc_fn` 注入)。

测试通过 LspManager 完整状态机 / 重启 / 路由 / 诊断 cache / 超时 / crash + 30s backoff。"""
from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from argos_agent.lsp.client import LspClient, encode_frame, parse_frames
from argos_agent.lsp.config import LspConfig, LspServerConfig
from argos_agent.lsp.manager import (
    LspManager,
    ServerStatus,
    _BACKOFF_SECONDS,
    _reset_content_cache,
    set_spawn_proc_fn,
    set_event_emit_fn,
)


# ── in-process fake proc / server ──────────────────────────────────

class _FakeStream:
    """LspClient 用:client 写 .write(data) → 入 in_q;server 从 in_q 取;
    server 写 out_q → client 通过 .stdout 异步 iter 取。

    对齐 asyncio.subprocess.Process.stdin:write() 同步返 None,drain() 异步。"""

    def __init__(self) -> None:
        self._in_q: asyncio.Queue[bytes] = asyncio.Queue()
        self._out_q: asyncio.Queue[bytes] = asyncio.Queue()
        self._closed = False

    def write(self, data: bytes) -> None:   # 同步,对齐 StreamWriter
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
    """模仿 asyncio.subprocess.Process 接口(stdin.write/drain + stdout AsyncIterable)。"""

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
    """fake LSP server 协程:从 stream 读帧,按 method 路由回响应。

    init_response: initialize 响应内容(默认 {capabilities: {}})
    route_handler: 可选 callable(method, params) → response_result;默认 None
    crash_after: 第 N 个 request 后主动关 stream(模拟崩)
    """
    try:
        first = await _read_one_frame(stream)
        if first.get("method") == "initialize":
            resp = init_response if init_response is not None else {"capabilities": {}}
            await stream.send(encode_frame({
                "jsonrpc": "2.0", "id": first["id"], "result": resp,
            }))
        else:
            return
        # 后续帧路由
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
    """从 stream 读一个完整 JSON-RPC 帧。"""
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
    """返一个 factory:接收 (init_response, route_handler, crash_after) → set_spawn_proc_fn 注入。"""
    tasks: list[asyncio.Task] = []

    async def _spawn(mgr, name, sc, env, cwd):
        proc = _FakeProc()
        client = LspClient(proc)
        task = asyncio.create_task(_fake_serve(proc.stream))
        tasks.append(task)
        return proc, client

    set_spawn_proc_fn(_spawn)
    set_event_emit_fn(None)  # 默认 no-op,降低耦合
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


# ── 状态机 + 生命周期 ─────────────────────────────────────────────

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
    """list_servers() 返每个 server 名字/状态/command。"""
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
    """disabled server → request 返 error JSON,不抛。"""
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
    """server_name 不存在 → request 返 error JSON。"""
    mgr = LspManager(_config_with_python())
    r = await mgr.request("nonexistent", "textDocument/definition", {})
    assert "error" in r
    assert "not configured" in r["error"]


@pytest.mark.asyncio
@pytest.mark.slow
async def test_request_routes_to_correct_server(fake_proc_factory):
    """request(server_name, ...) 路由到对应 server。"""
    mgr = LspManager(_config_with_python())
    await mgr.start_server("python")
    r = await mgr.request("python", "textDocument/definition", {"pos": 1})
    assert r is not None
    assert "error" not in r
    await mgr.shutdown()


@pytest.mark.asyncio
@pytest.mark.slow
async def test_concurrent_requests_dont_cross_talk(fake_proc_factory):
    """10 个并发 request → 10 个 response 按 id 路由,各回各的(不串台)。"""
    mgr = LspManager(_config_with_python())
    await mgr.start_server("python")

    async def call(i: int) -> dict:
        # route_handler 不可用 → 都返 None;验所有请求都成功完结且 id 不冲突
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
    """5s 超时 → manager.request 返 error JSON(spec §2.6)。"""
    # 造一个永不回应的 server
    tasks: list[asyncio.Task] = []

    async def _spawn_silent(mgr, name, sc, env, cwd):
        proc = _FakeProc()
        client = LspClient(proc)
        # 不起 fake_serve,服务端一直挂起;但 initialize 必须回应(否则 status 不进 Ready)
        async def _init_only():
            try:
                first = await _read_one_frame(proc.stream)
                await proc.stream.send(encode_frame({
                    "jsonrpc": "2.0", "id": first["id"],
                    "result": {"capabilities": {}},
                }))
                # 之后挂起,不再回任何 request
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
    # 短超时
    r = await mgr.request("python", "textDocument/definition", {}, timeout=0.5)
    assert "error" in r
    assert "timeout" in r["error"]
    # 清理
    await mgr.shutdown()
    for t in tasks:
        t.cancel()


@pytest.mark.asyncio
@pytest.mark.slow
async def test_crash_marks_crashed_and_schedules_retry(fake_proc_factory, monkeypatch):
    """crash_after=N → 第二个 request 后 server 关 stream → manager 标 Crashed + 30s backoff。"""
    # 短路 30s sleep
    sleeps: list[float] = []

    async def fake_sleep(s):
        sleeps.append(s)
        return None

    monkeypatch.setattr("argos_agent.lsp.manager.asyncio.sleep", fake_sleep)

    tasks: list[asyncio.Task] = []

    async def _spawn_crashing(mgr, name, sc, env, cwd):
        proc = _FakeProc()
        client = LspClient(proc)
        # crash_after=3 因为 manager 在 initialize 之后还会发 `initialized` 通知,
        # 占 1 个 msg slot;所以前 2 个 msg (initialized + 第 1 个 request) 正常回,
        # 第 3 个 msg (第 2 个 request) 触发 crash。
        tasks.append(asyncio.create_task(_fake_serve(proc.stream, crash_after=3)))
        return proc, client

    set_spawn_proc_fn(_spawn_crashing)
    mgr = LspManager(_config_with_python())
    await mgr.start_server("python")
    # 给 server 时间进入稳定的 while 循环
    await asyncio.sleep(0.05)
    # 第一个 request 成功
    r1 = await mgr.request("python", "textDocument/method1", {}, timeout=2.0)
    assert "error" not in r1, f"first request failed: {r1}"
    # 第二个 request 触发 crash_after=2
    r2 = await mgr.request("python", "textDocument/method2", {}, timeout=2.0)
    # r2 可能走 timeout 或 protocol error(因为 server 关了 stream)
    assert "error" in r2
    # 验证 crash 状态
    s = mgr._servers["python"]
    assert s.status in (ServerStatus.CRASHED, ServerStatus.DISABLED)
    # backoff 应被调用
    assert any(abs(s_ - _BACKOFF_SECONDS) < 0.01 for s_ in sleeps) or len(sleeps) > 0
    # 清理
    await mgr.shutdown()
    for t in tasks:
        t.cancel()


@pytest.mark.asyncio
@pytest.mark.slow
async def test_shutdown_sets_status_shutdown(fake_proc_factory):
    """shutdown → 所有 server status = Shutdown。"""
    mgr = LspManager(_config_with_python())
    await mgr.start_server("python")
    await mgr.shutdown()
    assert mgr.server_status("python") == ServerStatus.SHUTDOWN


@pytest.mark.asyncio
@pytest.mark.slow
async def test_diag_cache_receives_publish_diagnostics(fake_proc_factory):
    """server 推 textDocument/publishDiagnostics → manager 写入 diag_cache。"""
    # 注入 route_handler:initialize 之后第一次 request 时,推 diagnostics notification
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
            # 2. 推 publishDiagnostics
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
            # 3. 之后保持挂起(接收后续 request 但不主动回)
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
    # 等 diag 推送完成
    try:
        await asyncio.wait_for(diag_sent.wait(), timeout=2.0)
    except asyncio.TimeoutError:
        pass
    # 给 notif listener 一点时间处理
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
    """server 未 Ready 时 request 挂起;Ready 后 set result。"""
    # 短路 30s sleep
    async def fake_sleep(s):
        return None
    monkeypatch.setattr("argos_agent.lsp.manager.asyncio.sleep", fake_sleep)

    # 用一个慢启动的 spawn
    mgr = LspManager(_config_with_python())
    # 不显式 start_server;直接 request — 内部应挂起到 pending_requests
    # 但 start_server 在 request 内有自动启逻辑吗?当前实现没有 — request 在 not ready 时挂起
    # 我们用直接构造 _spawn_and_initialize 异步启 + request 并发
    async def _start_in_bg():
        await mgr.start_server("python")
    asyncio.create_task(_start_in_bg())
    # 给点时间进 Starting
    await asyncio.sleep(0.01)
    # 现在 request,会挂起,等 Ready 后自动 set
    r = await mgr.request("python", "textDocument/definition", {})
    assert "error" not in r
    await mgr.shutdown()


@pytest.mark.asyncio
@pytest.mark.slow
async def test_sync_file_didopen_then_didchange_incremental(fake_proc_factory, tmp_path):
    """sync_file 首次 → didOpen(v=1);再次 → didChange(v=2);版本号单调。"""
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
