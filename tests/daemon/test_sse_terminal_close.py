"""Internal documentation."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
import pytest_asyncio

from argos.daemon.client import DaemonClient
from argos.daemon.manager import RunManager
from argos.daemon.server import DaemonHTTPServer
from argos.daemon.state_machine import TERMINAL_STATES
from argos.daemon.worker import FakeLoop, RunWorker


# ── fixtures / helpers ──────────────────────────────────────────────────

@pytest_asyncio.fixture
async def server(tmp_path: Path):
    manager = RunManager(runs_dir=tmp_path / "runs", index_path=tmp_path / "index.json")
    srv = DaemonHTTPServer(manager=manager, socket_path=tmp_path / "daemon.sock")
    await srv.start()
    try:
        yield srv, manager
    finally:
        await srv.stop()
        manager.close()


async def _create_session(socket_path: Path) -> str:
    cli = DaemonClient(socket_path, timeout=5.0)
    status, _, raw = await cli._request("POST", "/sessions")
    assert status == 201
    return json.loads(raw.decode("utf-8"))["session_id"]


async def _create_run(socket_path: Path, sid: str, goal: str = "你好") -> str:
    cli = DaemonClient(socket_path, timeout=5.0)
    status, _, raw = await cli._request(
        "POST", "/runs", session_id=sid, body={"goal": goal}
    )
    assert status == 201
    return json.loads(raw.decode("utf-8"))["run_id"]


async def _poll_done(task: asyncio.Task, timeout: float) -> bool:
    """Internal documentation."""
    waited = 0.0
    while not task.done() and waited < timeout:
        await asyncio.sleep(0.05)
        waited += 0.05
    return task.done()



@pytest.mark.asyncio
async def test_sse_stream_closes_when_run_completes(server):
    """Internal documentation."""
    srv, mgr = server
    sid = await _create_session(srv.socket_path)
    rid = await _create_run(srv.socket_path, sid)
    mgr.mark_running(rid)

    client = DaemonClient(srv.socket_path, timeout=10.0)
    gen = client.subscribe_events(rid, sid, since=0)
    ev = await asyncio.wait_for(anext(gen), timeout=3.0)
    assert ev["kind"] == "run_meta"

    mgr.mark_completed(rid)

    async def _drain() -> None:
        async for _ in gen:
            pass

    await asyncio.wait_for(_drain(), timeout=5.0)


@pytest.mark.asyncio
async def test_sse_stream_closes_when_run_cancelled(server):
    """Internal documentation."""
    srv, mgr = server
    sid = await _create_session(srv.socket_path)
    rid = await _create_run(srv.socket_path, sid)
    mgr.mark_running(rid)

    client = DaemonClient(srv.socket_path, timeout=10.0)
    gen = client.subscribe_events(rid, sid, since=0)
    await asyncio.wait_for(anext(gen), timeout=3.0)

    mgr.mark_cancelled(rid)

    async def _drain() -> None:
        async for _ in gen:
            pass

    await asyncio.wait_for(_drain(), timeout=5.0)



@pytest.mark.asyncio
async def test_worker_fans_out_terminal_state_change_on_completion(tmp_path: Path):
    """Internal documentation."""
    mgr = RunManager(runs_dir=tmp_path / "runs", index_path=tmp_path / "index.json")
    rid = await mgr.create_run(goal="你好", workspace="/tmp")
    q = mgr.subscribe(rid)
    worker = RunWorker(
        run_id=rid, manager=mgr, loop_factory=lambda: FakeLoop(steps=2, delay_s=0.0),
    )
    await worker.run()
    assert mgr.get_run(rid).state == "completed"

    events = []
    while not q.empty():
        events.append(q.get_nowait())
    assert any(
        e.get("kind") == "state_change" and e.get("to") in TERMINAL_STATES
        for e in events
    ), "worker 必须广播终态 state_change,SSE 订阅者才能立即关流"



@pytest.mark.asyncio
async def test_worker_watchdog_hard_cancels_when_timeout_exceeded(
    tmp_path: Path, monkeypatch
):
    """Internal documentation."""
    monkeypatch.setenv("ARGOS_RUN_TIMEOUT_S", "0.3")

    class _HangLoop:
        async def run(self, goal, session_id=None, **kwargs):
            yield {"kind": "token_delta", "text": "start"}  # → running
            await asyncio.sleep(100)
            yield {"kind": "token_delta", "text": "never"}

    ws = tmp_path / "ws"
    ws.mkdir()
    mgr = RunManager(runs_dir=tmp_path / "runs", index_path=tmp_path / "index.json")
    rid = await mgr.create_run(goal="x", workspace=str(ws))
    worker = RunWorker(run_id=rid, manager=mgr, loop_factory=lambda: _HangLoop())
    task = asyncio.create_task(worker.run())

    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=3.0)
    assert mgr.get_run(rid).state == "cancelled"


@pytest.mark.asyncio
async def test_worker_watchdog_disabled_by_default(tmp_path: Path):
    """Internal documentation."""
    mgr = RunManager(runs_dir=tmp_path / "runs", index_path=tmp_path / "index.json")
    rid = await mgr.create_run(goal="x", workspace="/tmp")
    worker = RunWorker(
        run_id=rid, manager=mgr, loop_factory=lambda: FakeLoop(steps=3, delay_s=0.0),
    )
    await worker.run()
    assert mgr.get_run(rid).state == "completed"



@pytest.mark.asyncio
async def test_daemon_event_source_stream_ends_on_completion(server):
    """Internal documentation."""
    from argos.tui.daemon_source import DaemonEventSource

    srv, mgr = server
    sid = await _create_session(srv.socket_path)
    rid = await _create_run(srv.socket_path, sid)
    mgr.mark_running(rid)

    source = DaemonEventSource(srv.socket_path, rid, sid)
    collected: list = []

    async def _consume() -> None:
        async for ev in source.stream():
            collected.append(ev)

    task = asyncio.create_task(_consume())
    await asyncio.sleep(0.5)
    mgr.mark_completed(rid)

    done = await _poll_done(task, timeout=6.0)
    if not done:
        task.cancel()
    assert done, "DaemonEventSource.stream() 未随 run 完成而收尾 → bus 永不关 → guard 卡死"



@pytest.mark.asyncio
async def test_conductor_sse_subscribes_without_404(server):
    """Internal documentation."""
    from argos.daemon.conductor_supervisor import CONDUCTOR_RUN_ID

    srv, mgr = server
    sid = await _create_session(srv.socket_path)

    client = DaemonClient(srv.socket_path, timeout=10.0)
    gen = client.subscribe_events(CONDUCTOR_RUN_ID, sid, since=0)
    first = asyncio.create_task(anext(gen))
    await asyncio.sleep(0.4)
    await mgr.fanout(CONDUCTOR_RUN_ID, {"kind": "proactive_suggestion", "goal": "x"})

    ev = await asyncio.wait_for(first, timeout=5.0)
    assert ev["kind"] == "proactive_suggestion", "conductor 订阅者必须收到实时 fanout 事件"
    await gen.aclose()
