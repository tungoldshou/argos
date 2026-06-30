"""Test: resume-from-suspended actually spawns a RunWorker.

Three contracts verified:
  (a) resuming a suspended run with no live worker spawns a worker and
      transitions the run past 'suspended'.
  (b) step budget and SSE cursor continue from checkpoint, not from 0.
  (c) resume with no live worker AND no usable metadata returns 409 no_worker.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
import pytest_asyncio

from argos.daemon.manager import RunManager
from argos.daemon.server import DaemonHTTPServer
from argos.daemon.worker import FakeLoop


# ── helpers ───────────────────────────────────────────────────────────────

async def _req(socket_path: Path, method: str, path: str, *,
               session_id: str | None = None, body: dict | None = None):
    from argos.daemon.client import DaemonClient
    cli = DaemonClient(socket_path, timeout=5.0)
    return await cli._request(method, path, session_id=session_id, body=body)


async def _create_session(socket_path: Path) -> str:
    status, _, raw = await _req(socket_path, "POST", "/sessions")
    assert status == 201
    return json.loads(raw.decode())["session_id"]


# ── fixture: server with a FakeLoop so workers can actually run ───────────

@pytest_asyncio.fixture
async def loop_server(tmp_path: Path):
    """DaemonHTTPServer wired with a FakeLoop factory."""
    manager = RunManager(runs_dir=tmp_path / "runs", index_path=tmp_path / "i.json")
    srv = DaemonHTTPServer(
        manager=manager,
        socket_path=tmp_path / "daemon.sock",
        loop_factory=lambda: FakeLoop(steps=20, delay_s=0.01),
    )
    await srv.start()
    try:
        yield srv, manager
    finally:
        await srv.stop()
        manager.close()


# ── (a) suspend then resume spawns a worker and advances state ────────────

@pytest.mark.asyncio
async def test_resume_suspended_spawns_worker(loop_server, tmp_path: Path):
    """Resuming a suspended run with no live worker must spawn a new RunWorker
    and eventually transition the run out of 'suspended' → running/completed.
    """
    srv, mgr = loop_server
    sid = await _create_session(srv.socket_path)

    # Create and manually suspend (simulates a daemon restart with live SIGKILL)
    rid = await mgr.create_run(goal="refactor x.py", workspace="")
    mgr.mark_running(rid)
    mgr.mark_suspended(rid, last_step=3, msg_count=5, last_event_seq=12)
    assert mgr.get_run(rid).state == "suspended"

    # POST /resume — the run has no live worker in _workers
    status, _, raw = await _req(srv.socket_path, "POST", f"/runs/{rid}/resume",
                                 session_id=sid)
    assert status == 202, f"expected 202, got {status}: {raw.decode()}"
    body = json.loads(raw.decode())
    assert body["state"] == "resume_requested"

    # A worker must have been spawned; wait for state to advance past suspended
    for _ in range(100):
        state = mgr.get_run(rid).state
        if state not in ("suspended", "running"):
            break
        await asyncio.sleep(0.02)

    final_state = mgr.get_run(rid).state
    assert final_state in ("completed", "failed", "cancelled"), (
        f"expected terminal state after resume-spawn, got {final_state!r}"
    )


# ── (b) step budget and SSE cursor continue from checkpoint ──────────────

def test_worker_initial_step_and_seq_from_checkpoint(tmp_path: Path):
    """Unit test: RunWorker constructed with initial values honours them.

    Verifies that the constructor wires initial_event_seq and initial_step_count
    into the right fields so that a resumed worker starts from the checkpoint,
    not from 0.
    """
    mgr = RunManager(runs_dir=tmp_path / "runs", index_path=tmp_path / "i.json")
    # Build a worker directly (without actually running it).
    worker = __import__("argos.daemon.worker", fromlist=["RunWorker"]).RunWorker(
        run_id="testrun000001",
        manager=mgr,
        loop_factory=lambda: None,  # never called in this unit test
        initial_event_seq=42,
        initial_step_count=9,
    )
    assert worker.event_seq == 42, (
        f"event_seq should be initialised from checkpoint 42, got {worker.event_seq}"
    )
    assert worker.current_step == 9, (
        f"current_step should be initialised from checkpoint 9, got {worker.current_step}"
    )


@pytest.mark.asyncio
async def test_resume_spawned_worker_continues_step_count(loop_server, tmp_path: Path):
    """Integration: the spawned worker's current_step starts from last_step in
    the checkpoint (7) and never goes below it, proving it didn't restart from 0.
    """
    srv, mgr = loop_server
    sid = await _create_session(srv.socket_path)

    rid = await mgr.create_run(goal="write tests", workspace="")
    mgr.mark_running(rid)
    mgr.mark_suspended(rid, last_step=7, msg_count=3, last_event_seq=5)
    assert mgr.get_run(rid).state == "suspended"
    assert rid not in srv._workers

    status, _, raw = await _req(srv.socket_path, "POST", f"/runs/{rid}/resume",
                                 session_id=sid)
    assert status == 202

    # Give the event loop a tick to register the worker
    await asyncio.sleep(0.05)
    worker = srv._workers.get(rid)
    assert worker is not None, "worker should have been spawned in _workers"

    # current_step starts at last_step (7) and only ever increases — never 0.
    assert worker.current_step >= 7, (
        f"step_count should continue from checkpoint 7, got {worker.current_step}"
    )

    # Tear down cleanly
    await mgr.request_cancel(rid)
    worker.request_hard_cancel()
    for _ in range(50):
        if mgr.get_run(rid).state in ("completed", "cancelled", "failed"):
            break
        await asyncio.sleep(0.02)


# ── (c) honest 409 when no usable metadata (no loop_factory available) ───

@pytest.mark.asyncio
async def test_resume_suspended_no_worker_no_factory_returns_409(tmp_path: Path):
    """Server with no loop_factory/components cannot spawn a worker.
    Resuming a suspended run must return 409 no_worker, NOT a lying 202.
    """
    manager = RunManager(runs_dir=tmp_path / "runs", index_path=tmp_path / "i.json")
    # Deliberately no loop_factory — metadata-only server
    srv = DaemonHTTPServer(
        manager=manager,
        socket_path=tmp_path / "daemon.sock",
        # loop_factory=None  (default)
    )
    await srv.start()
    try:
        # Create session + run, then mark suspended
        status, _, raw = await _req(srv.socket_path, "POST", "/sessions")
        sid = json.loads(raw.decode())["session_id"]
        rid = await manager.create_run(goal="analyse logs", workspace="")
        manager.mark_running(rid)
        manager.mark_suspended(rid, last_step=2, msg_count=1, last_event_seq=5)

        status, _, raw = await _req(srv.socket_path, "POST", f"/runs/{rid}/resume",
                                     session_id=sid)
        assert status == 409, (
            f"expected 409 no_worker for metadata-only server, got {status}: {raw.decode()}"
        )
        body = json.loads(raw.decode())
        assert body.get("code") == "no_worker", (
            f"expected code=no_worker, got {body}"
        )
    finally:
        await srv.stop()
        manager.close()
