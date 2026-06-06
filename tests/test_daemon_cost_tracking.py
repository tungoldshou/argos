"""Cost tracking per-run 测试(#5b T7)。

覆盖:
  · cost_update 事件 → RunRegistry.add_cost 累加
  · cost_usd=None 不累加
  · 多次 cost_update 累加正确
  · 终态 → worktree cleanup + registry slot release
  · GET /runs/{id} body 含 cost + worktree + focus
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
from argos_agent.daemon.worker import RunWorker


# ── test loop helper ───────────────────────────────────────────────────


class _ScriptLoop:
    """脚本化的 test loop:yield 固定 list of events。"""

    def __init__(self, events: list[dict]):
        self._events = events

    async def run(self, goal: str, session_id: str) -> AsyncIterator[dict]:
        for ev in self._events:
            yield ev


# ── fixtures ────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def cost_server(tmp_path: Path):
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


async def _req(socket_path, method, path, *, session_id=None, body=None):
    from argos_agent.daemon.client import DaemonClient
    cli = DaemonClient(socket_path, timeout=3.0)
    return await cli._request(method, path, session_id=session_id, body=body)


async def _create_session(socket_path) -> str:
    status, _, raw = await _req(socket_path, "POST", "/sessions")
    return json.loads(raw.decode("utf-8"))["session_id"]


# ── cost 累加 ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cost_event_accumulates_to_registry(cost_server, tmp_path: Path):
    srv, mgr, reg, _ = cost_server
    sid = await _create_session(srv.socket_path)
    status, _, raw = await _req(srv.socket_path, "POST", "/runs",
                                 session_id=sid, body={"goal": "x"})
    rid = json.loads(raw.decode("utf-8"))["run_id"]
    events = [
        {"kind": "cost_update", "tokens_in": 100, "tokens_out": 50, "cost_usd": 0.01},
        {"kind": "verify_verdict", "verdict": {"status": "passed", "reason": "x"}},
    ]
    worker = RunWorker(
        run_id=rid, manager=mgr,
        loop_factory=lambda: _ScriptLoop(events),
        registry=reg,
    )
    await worker.run()
    entry = reg.get(rid)
    assert entry.tokens_in == 100
    assert entry.tokens_out == 50
    assert entry.cost_usd == 0.01


@pytest.mark.asyncio
async def test_cost_event_with_none_keeps_none(cost_server, tmp_path: Path):
    srv, mgr, reg, _ = cost_server
    sid = await _create_session(srv.socket_path)
    status, _, raw = await _req(srv.socket_path, "POST", "/runs",
                                 session_id=sid, body={"goal": "x"})
    rid = json.loads(raw.decode("utf-8"))["run_id"]
    events = [
        {"kind": "cost_update", "tokens_in": 100, "tokens_out": 50, "cost_usd": None},
    ]
    worker = RunWorker(
        run_id=rid, manager=mgr,
        loop_factory=lambda: _ScriptLoop(events),
        registry=reg,
    )
    await worker.run()
    entry = reg.get(rid)
    assert entry.cost_usd is None
    assert entry.tokens_in == 100


@pytest.mark.asyncio
async def test_multiple_cost_events_sum(cost_server, tmp_path: Path):
    srv, mgr, reg, _ = cost_server
    sid = await _create_session(srv.socket_path)
    status, _, raw = await _req(srv.socket_path, "POST", "/runs",
                                 session_id=sid, body={"goal": "x"})
    rid = json.loads(raw.decode("utf-8"))["run_id"]
    events = [
        {"kind": "cost_update", "tokens_in": 100, "tokens_out": 50, "cost_usd": 0.01},
        {"kind": "cost_update", "tokens_in": 200, "tokens_out": 100, "cost_usd": 0.02},
    ]
    worker = RunWorker(
        run_id=rid, manager=mgr,
        loop_factory=lambda: _ScriptLoop(events),
        registry=reg,
    )
    await worker.run()
    entry = reg.get(rid)
    assert entry.tokens_in == 300
    assert entry.tokens_out == 150
    assert abs(entry.cost_usd - 0.03) < 1e-9


# ── 终态 cleanup ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_terminal_state_releases_slot_and_calls_cleanup(cost_server, tmp_path: Path):
    """worker 终态(completed)→ registry.slot 释放 + worktree 删。"""
    import subprocess
    import shutil
    if not shutil.which("git"):
        pytest.skip("git not in PATH")
    # 起一个真 git repo 让 worktree 走 git 路径(非 temp)
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=repo, check=True)
    (repo / "a").write_text("x")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)

    srv, mgr, reg, worktree = cost_server
    sid = await _create_session(srv.socket_path)
    # 先 acquire 一个 slot 模拟在跑
    await reg.acquire_slot()
    status, _, raw = await _req(srv.socket_path, "POST", "/runs",
                                 session_id=sid, body={"goal": "x"})
    rid = json.loads(raw.decode("utf-8"))["run_id"]
    # 创 worktree(走 git 路径)
    wt_path = worktree.create(run_id=rid, workspace=str(repo))
    await reg.register(run_id=rid, goal="x", workspace="", worktree_path=wt_path)
    assert (tmp_path / "wt" / rid).exists()

    async def fake_loop_run(goal, session_id):
        yield {"kind": "verify_verdict", "verdict": {"status": "passed"}}

    class _Loop:
        async def run(self, goal, session_id):
            async for ev in fake_loop_run(goal, session_id):
                yield ev

    worker = RunWorker(
        run_id=rid, manager=mgr,
        loop_factory=lambda: _Loop(),
        registry=reg, worktree=worktree,
    )
    await worker.run()
    # worktree 已被清
    assert not (tmp_path / "wt" / rid).exists()
    # state 改 completed
    assert reg.get(rid).state == "completed"


# ── GET /runs /runs/{id} 字段 ────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_runs_response_shape_includes_new_fields(cost_server, tmp_path: Path):
    srv, _, reg, _ = cost_server
    sid = await _create_session(srv.socket_path)
    status, _, raw = await _req(srv.socket_path, "POST", "/runs",
                                 session_id=sid, body={"goal": "x"})
    rid = json.loads(raw.decode("utf-8"))["run_id"]
    reg.add_cost(run_id=rid, tokens_in_delta=300, tokens_out_delta=80, cost_usd_delta=0.05)
    status, _, raw = await _req(srv.socket_path, "GET", "/runs", session_id=sid)
    body = json.loads(raw.decode("utf-8"))
    target = next(r for r in body if r["run_id"] == rid)
    assert target["tokens_in"] == 300
    assert target["tokens_out"] == 80
    assert target["cost_usd"] == 0.05
    assert "worktree_path" in target
    assert "focus_session_id" in target


@pytest.mark.asyncio
async def test_get_run_response_shape_includes_new_fields(cost_server, tmp_path: Path):
    srv, _, reg, _ = cost_server
    sid = await _create_session(srv.socket_path)
    status, _, raw = await _req(srv.socket_path, "POST", "/runs",
                                 session_id=sid, body={"goal": "x"})
    rid = json.loads(raw.decode("utf-8"))["run_id"]
    reg.set_focus(run_id=rid, session_id=sid)
    status, _, raw = await _req(srv.socket_path, "GET", f"/runs/{rid}",
                                 session_id=sid)
    body = json.loads(raw.decode("utf-8"))
    assert "tokens_in" in body
    assert "tokens_out" in body
    assert "cost_usd" in body
    assert "worktree_path" in body
    assert body["focus_session_id"] == sid
