from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import AsyncIterator

import pytest
import pytest_asyncio

from argos.daemon.manager import RunManager
from argos.daemon.registry import RunRegistry
from argos.daemon.server import DaemonHTTPServer
from argos.daemon.worktree import WorktreeManager


class _ScriptLoop:
    def __init__(self, events: list[dict], delay: float = 0.01):
        self._events = events
        self._delay = delay

    async def run(self, goal, session_id):
        for ev in self._events:
            if self._delay:
                await asyncio.sleep(self._delay)
            yield ev


async def _req(socket_path, method, path, *, session_id=None, body=None):
    from argos.daemon.client import DaemonClient
    cli = DaemonClient(socket_path, timeout=3.0)
    return await cli._request(method, path, session_id=session_id, body=body)


async def _create_session(socket_path) -> str:
    status, _, raw = await _req(socket_path, "POST", "/sessions")
    return json.loads(raw.decode("utf-8"))["session_id"]


@pytest_asyncio.fixture
async def e2e_daemon(tmp_path: Path):
    runs_dir = tmp_path / "runs"
    index_path = tmp_path / "index.json"
    socket_path = tmp_path / "daemon.sock"
    manager = RunManager(runs_dir=runs_dir, index_path=index_path)
    registry = RunRegistry(max_concurrent=5, max_history=100)
    worktree = WorktreeManager(base_dir=tmp_path / "wt")
    srv = DaemonHTTPServer(
        manager=manager, socket_path=socket_path,
        registry=registry, worktree=worktree,
    )
    await srv.start()
    try:
        yield srv, manager, registry, worktree
    finally:
        await srv.stop()
        manager.close()


@pytest.mark.asyncio
async def test_e2e_5_concurrent_runs_with_cost_worktree_observer(e2e_daemon, tmp_path: Path):
    srv, mgr, reg, worktree = e2e_daemon
    sid_owner = await _create_session(srv.socket_path)
    assert srv.sessions.get(sid_owner).role == "owner"
    rids = []
    for i in range(5):
        status, _, raw = await _req(srv.socket_path, "POST", "/runs",
                                     session_id=sid_owner, body={"goal": f"g{i}"})
        assert status == 201
        rids.append(json.loads(raw.decode("utf-8"))["run_id"])
    assert reg.active_count == 5
    assert reg.size == 5

    from argos.daemon.worker import RunWorker
    workers = []
    for i, rid in enumerate(rids):
        events = [
            {"kind": "cost_update", "tokens_in": 100 * (i + 1), "tokens_out": 20 * (i + 1),
             "cost_usd": 0.01 * (i + 1)},
            {"kind": "verify_verdict", "verdict": {"status": "passed"}},
        ]
        w = RunWorker(
            run_id=rid, manager=mgr,
            loop_factory=lambda e=events: _ScriptLoop(e, delay=0.01),
            registry=reg, worktree=worktree,
        )
        workers.append(w)
    await asyncio.gather(*(w.run() for w in workers))
    for rid in rids:
        e = reg.get(rid)
        assert e.state == "completed", f"run {rid} not completed: {e.state}"
        assert e.tokens_in > 0
        assert e.cost_usd > 0
    for _ in range(5):
        await asyncio.wait_for(reg.acquire_slot(), timeout=0.1)
    for _ in range(5):
        reg.release_slot()
    sid_observer = await _create_session(srv.socket_path)
    assert srv.sessions.get(sid_observer).role == "observer"
    status, _, _ = await _req(srv.socket_path, "POST", "/runs",
                               session_id=sid_observer, body={"goal": "x"})
    assert status == 403
    status, _, _ = await _req(srv.socket_path, "POST", f"/runs/{rids[0]}/focus",
                               session_id=sid_observer)
    assert status == 403
    status, _, _ = await _req(srv.socket_path, "POST", f"/runs/{rids[0]}/pause",
                               session_id=sid_observer)
    assert status == 403
    status, _, _ = await _req(srv.socket_path, "POST", f"/runs/{rids[0]}/cancel",
                               session_id=sid_observer)
    assert status == 403
    status, _, raw = await _req(srv.socket_path, "GET", "/runs",
                                 session_id=sid_observer)
    assert status == 200
    runs = json.loads(raw.decode("utf-8"))
    assert len(runs) == 5
    for r in runs:
        assert r["state"] == "completed"
        assert r["cost_usd"] > 0
        assert r["tokens_in"] > 0
    await _req(srv.socket_path, "DELETE", f"/sessions/{sid_owner}")
    promoted = srv.sessions.get(sid_observer)
    assert promoted.role == "owner"
    status, _, raw = await _req(srv.socket_path, "POST", "/runs",
                                 session_id=sid_observer, body={"goal": "after-promote"})
    assert status == 201
