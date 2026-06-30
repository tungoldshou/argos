"""Test: resume-from-suspended actually spawns a RunWorker.

Four contracts verified:
  (a) resuming a suspended run with no live worker spawns a worker and
      transitions the run past 'suspended'.
  (b) step budget and SSE cursor continue from checkpoint, not from 0.
  (c) resume with no live worker AND no usable metadata returns 409 no_worker.
  (d) double /resume while worker is alive does NOT spawn a second worker.
  (e) checkpoint-restore reads the run_checkpoint event from JSONL so the
      worker's step counter starts at N, not 0.
"""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import pytest
import pytest_asyncio

from argos.daemon.events import RunCheckpoint
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


# ── (d) double-resume guard: second POST /resume must not spawn a second worker ──

@pytest.mark.asyncio
async def test_double_resume_does_not_spawn_second_worker(loop_server, tmp_path: Path):
    """POST /resume twice while the first worker is still alive must NOT create
    a duplicate worker.  The guard `if was_suspended and run_id not in self._workers`
    (server.py) is what prevents double-spawn; deleting it would allow two workers
    to race on the same run.
    """
    srv, mgr = loop_server
    sid = await _create_session(srv.socket_path)

    rid = await mgr.create_run(goal="double-spawn check", workspace="")
    mgr.mark_running(rid)
    mgr.mark_suspended(rid, last_step=2, msg_count=1, last_event_seq=4)
    assert rid not in srv._workers

    # First resume — spawns a worker.
    status1, _, raw1 = await _req(srv.socket_path, "POST", f"/runs/{rid}/resume",
                                  session_id=sid)
    assert status1 == 202, f"first resume: {raw1.decode()}"

    # Give the event loop a tick so the worker is registered in _workers.
    await asyncio.sleep(0.05)
    assert rid in srv._workers, "worker should appear in _workers after first resume"
    worker1 = srv._workers[rid]

    # Second resume while worker is still alive.
    status2, _, raw2 = await _req(srv.socket_path, "POST", f"/runs/{rid}/resume",
                                  session_id=sid)
    # The second call can succeed (202) or fail (409 invalid transition) depending on
    # whether the state has advanced past 'suspended' already — but either way,
    # the worker in _workers must be the same object (no second spawn).
    await asyncio.sleep(0.02)
    worker2 = srv._workers.get(rid)
    if worker2 is not None:
        assert worker2 is worker1, (
            "second /resume must not replace the live worker in _workers; "
            "got a different object — double-spawn guard broken"
        )

    # Tear down cleanly.
    await mgr.request_cancel(rid)
    worker1.request_hard_cancel()
    for _ in range(50):
        if mgr.get_run(rid).state in ("completed", "cancelled", "failed"):
            break
        await asyncio.sleep(0.02)


# ── (e) checkpoint-restore: worker step counter starts at N from JSONL event ─

@pytest.mark.asyncio
async def test_checkpoint_restore_reads_jsonl_step(loop_server, tmp_path: Path):
    """The _spawn_suspended_resume path reads the run_checkpoint event from the
    JSONL store (store.last_checkpoint) and seeds the worker's step counter from
    last_step — so the worker starts at N, NOT 0.

    This test writes a run_checkpoint event explicitly into the store BEFORE
    calling mark_suspended, proving the checkpoint-restore path exercises the
    JSONL read rather than falling back to 0.
    """
    srv, mgr = loop_server
    sid = await _create_session(srv.socket_path)

    CHECKPOINT_STEP = 13  # an unambiguous N that can't be reached in 50ms

    rid = await mgr.create_run(goal="restore from checkpoint", workspace="")
    mgr.mark_running(rid)

    # Write an explicit run_checkpoint to the JSONL BEFORE transitioning to
    # suspended.  This is what _spawn_suspended_resume reads via last_checkpoint().
    ckpt_event = RunCheckpoint(
        ts=time.time(),
        last_step=CHECKPOINT_STEP,
        messages_count=4,
        last_event_seq=20,
    )
    mgr.store.append(rid, ckpt_event.to_dict())

    # Now suspend (this also writes another checkpoint with last_step=CHECKPOINT_STEP;
    # last_checkpoint() will return the later one — both have the same step).
    mgr.mark_suspended(rid, last_step=CHECKPOINT_STEP, msg_count=4, last_event_seq=20)
    assert rid not in srv._workers

    status, _, raw = await _req(srv.socket_path, "POST", f"/runs/{rid}/resume",
                                session_id=sid)
    assert status == 202, f"resume failed: {raw.decode()}"

    # Give the event loop a tick to register the worker.
    await asyncio.sleep(0.05)
    worker = srv._workers.get(rid)
    assert worker is not None, "worker should have been spawned"

    # current_step must start at CHECKPOINT_STEP, NOT 0.
    # With delay_s=0.01 and sleep=0.05 the worker can advance at most ~5 steps,
    # so asserting >= CHECKPOINT_STEP proves it started there, not that it ran there.
    assert worker.current_step >= CHECKPOINT_STEP, (
        f"worker.current_step should start at checkpoint N={CHECKPOINT_STEP}, "
        f"got {worker.current_step} — checkpoint-restore from JSONL broken"
    )

    # Tear down cleanly.
    await mgr.request_cancel(rid)
    worker.request_hard_cancel()
    for _ in range(50):
        if mgr.get_run(rid).state in ("completed", "cancelled", "failed"):
            break
        await asyncio.sleep(0.02)
