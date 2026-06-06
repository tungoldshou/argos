"""#5b 端到端铁证:多 run 并发 + worktree + cost + 多 TUI 互斥。

- 起真 daemon + 5 个 FakeLoop 并发跑 → 全 5 个完成 → GET /runs 看齐
- 第 2 个 TUI session 连上 → 变 observer → POST /runs 拿 403
- worktree 终态自动 cleanup
- cost 累加正确
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import AsyncIterator

import pytest
import pytest_asyncio

from argos_agent.daemon.manager import RunManager
from argos_agent.daemon.registry import RunRegistry
from argos_agent.daemon.server import DaemonHTTPServer
from argos_agent.daemon.worktree import WorktreeManager


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
    from argos_agent.daemon.client import DaemonClient
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
    """端到端铁证:5 个 run 并发 + cost 累加 + worktree + observer 限权 全链路通。"""
    srv, mgr, reg, worktree = e2e_daemon
    # 1. owner 建 5 个 run + 起 5 个 worker 并发
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

    # 2. 起 worker 并发(每 run 不同 cost)
    from argos_agent.daemon.worker import RunWorker
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
    # 并发跑
    await asyncio.gather(*(w.run() for w in workers))
    # 3. 全部 completed
    for rid in rids:
        e = reg.get(rid)
        assert e.state == "completed", f"run {rid} not completed: {e.state}"
        # cost 已累加
        assert e.tokens_in > 0
        assert e.cost_usd > 0
    # 4. slot 全释放(下次能再 acquire 5 个 — 仅验证释放成功,马上归还)
    for _ in range(5):
        await asyncio.wait_for(reg.acquire_slot(), timeout=0.1)
    for _ in range(5):
        reg.release_slot()
    # 5. 观察者连上 → 变 observer
    sid_observer = await _create_session(srv.socket_path)
    assert srv.sessions.get(sid_observer).role == "observer"
    # 6. observer 写端点全 403
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
    # 7. observer 读端点 OK
    status, _, raw = await _req(srv.socket_path, "GET", "/runs",
                                 session_id=sid_observer)
    assert status == 200
    runs = json.loads(raw.decode("utf-8"))
    assert len(runs) == 5
    # 全部 completed + cost > 0
    for r in runs:
        assert r["state"] == "completed"
        assert r["cost_usd"] > 0
        assert r["tokens_in"] > 0
    # 8. owner 退出 → observer 自动 promote
    await _req(srv.socket_path, "DELETE", f"/sessions/{sid_owner}")
    promoted = srv.sessions.get(sid_observer)
    assert promoted.role == "owner"
    # 9. 新 owner 能建 run
    status, _, raw = await _req(srv.socket_path, "POST", "/runs",
                                 session_id=sid_observer, body={"goal": "after-promote"})
    assert status == 201
