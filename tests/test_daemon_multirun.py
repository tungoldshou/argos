"""Internal documentation."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
import pytest_asyncio

from argos.daemon.manager import RunManager
from argos.daemon.registry import RunRegistry
from argos.daemon.server import DaemonHTTPServer
from argos.daemon.worktree import WorktreeManager


# ── fixtures ────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def mr_server(tmp_path: Path):
    """Internal documentation."""
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
        yield srv, manager, registry
    finally:
        await srv.stop()
        manager.close()


async def _req(socket_path: Path, method: str, path: str, *,
               session_id: str | None = None, body: dict | None = None,
               timeout: float = 5.0):
    from argos.daemon.client import DaemonClient
    cli = DaemonClient(socket_path, timeout=timeout)
    return await cli._request(method, path, session_id=session_id, body=body)


async def _create_session(socket_path: Path) -> str:
    status, _, raw = await _req(socket_path, "POST", "/sessions")
    assert status == 201
    return json.loads(raw.decode("utf-8"))["session_id"]




@pytest.mark.asyncio
async def test_create_run_returns_id(mr_server, tmp_path: Path):
    srv, _, _ = mr_server
    sid = await _create_session(srv.socket_path)
    status, _, raw = await _req(srv.socket_path, "POST", "/runs",
                                 session_id=sid, body={"goal": "refactor auth.py"})
    assert status == 201
    rid = json.loads(raw.decode("utf-8"))["run_id"]
    assert len(rid) == 12


@pytest.mark.asyncio
async def test_concurrent_create_runs_all_register(mr_server, tmp_path: Path):
    """Internal documentation."""
    srv, _, reg = mr_server
    sid = await _create_session(srv.socket_path)
    rids = []
    for i in range(5):
        status, _, raw = await _req(srv.socket_path, "POST", "/runs",
                                     session_id=sid, body={"goal": f"g{i}"})
        assert status == 201
        rids.append(json.loads(raw.decode("utf-8"))["run_id"])
    assert len(set(rids)) == 5
    for rid in rids:
        assert reg.get(rid) is not None
    assert reg.active_count == 5


@pytest.mark.asyncio
async def test_post_runs_returns_503_when_max_reached(mr_server, tmp_path: Path):
    """Internal documentation."""
    srv, _, reg = mr_server
    sid = await _create_session(srv.socket_path)
    for _ in range(5):
        await reg.acquire_slot()
    status, _, raw = await _req(srv.socket_path, "POST", "/runs",
                                 session_id=sid, body={"goal": "g6"})
    assert status == 503
    body = json.loads(raw.decode("utf-8"))
    assert body["code"] == "busy"
    assert "max_concurrent_runs_reached" in body["error"]
    assert "max=5" in body["error"]


@pytest.mark.asyncio
async def test_post_runs_after_cancel_frees_slot(mr_server, tmp_path: Path):
    """Internal documentation."""
    srv, mgr, reg = mr_server
    sid = await _create_session(srv.socket_path)
    rids = []
    for i in range(5):
        status, _, raw = await _req(srv.socket_path, "POST", "/runs",
                                     session_id=sid, body={"goal": f"g{i}"})
        rids.append(json.loads(raw.decode("utf-8"))["run_id"])
    for _ in range(5):
        await reg.acquire_slot()
    await reg.cleanup(run_id=rids[0], terminal_state="cancelled")
    status, _, _ = await _req(srv.socket_path, "POST", "/runs",
                               session_id=sid, body={"goal": "g6"})
    assert status == 201


# ── worktree ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_post_runs_with_isolation_creates_worktree(mr_server, tmp_path: Path):
    """Internal documentation."""
    import subprocess
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=repo, check=True)
    (repo / "a").write_text("x")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)

    srv, _, reg = mr_server
    sid = await _create_session(srv.socket_path)
    status, _, raw = await _req(srv.socket_path, "POST", "/runs",
                                 session_id=sid,
                                 body={"goal": "x", "workspace": str(repo),
                                       "isolation": "worktree"})
    assert status == 201
    rid = json.loads(raw.decode("utf-8"))["run_id"]
    entry = reg.get(rid)
    assert entry.worktree_path is not None
    assert (tmp_path / "wt" / rid).exists()


@pytest.mark.asyncio
async def test_post_runs_workspace_not_found_returns_400(mr_server, tmp_path: Path):
    """Internal documentation."""
    srv, _, _ = mr_server
    sid = await _create_session(srv.socket_path)
    status, _, _ = await _req(srv.socket_path, "POST", "/runs",
                               session_id=sid, body={"goal": "x"})
    assert status == 201




@pytest.mark.asyncio
async def test_list_runs_includes_cost_worktree_focus(mr_server, tmp_path: Path):
    srv, _, reg = mr_server
    sid = await _create_session(srv.socket_path)
    status, _, raw = await _req(srv.socket_path, "POST", "/runs",
                                 session_id=sid, body={"goal": "x"})
    rid = json.loads(raw.decode("utf-8"))["run_id"]
    reg.add_cost(run_id=rid, tokens_in_delta=100, tokens_out_delta=20, cost_usd_delta=0.01)
    reg.set_focus(run_id=rid, session_id=sid)
    status, _, raw = await _req(srv.socket_path, "GET", "/runs", session_id=sid)
    assert status == 200
    runs = json.loads(raw.decode("utf-8"))
    target = next(r for r in runs if r["run_id"] == rid)
    assert target["tokens_in"] == 100
    assert target["tokens_out"] == 20
    assert target["cost_usd"] == 0.01
    assert target["focus_session_id"] == sid


@pytest.mark.asyncio
async def test_get_run_includes_cost_worktree_focus(mr_server, tmp_path: Path):
    srv, _, reg = mr_server
    sid = await _create_session(srv.socket_path)
    status, _, raw = await _req(srv.socket_path, "POST", "/runs",
                                 session_id=sid, body={"goal": "x"})
    rid = json.loads(raw.decode("utf-8"))["run_id"]
    reg.add_cost(run_id=rid, tokens_in_delta=50, tokens_out_delta=10, cost_usd_delta=0.005)
    status, _, raw = await _req(srv.socket_path, "GET", f"/runs/{rid}",
                                 session_id=sid)
    assert status == 200
    body = json.loads(raw.decode("utf-8"))
    assert body["tokens_in"] == 50
    assert body["tokens_out"] == 10
    assert body["cost_usd"] == 0.005
    assert "worktree_path" in body
    assert "focus_session_id" in body
