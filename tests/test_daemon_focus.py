"""/runs/{id}/focus 端点测试(#5b T2)。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import pytest_asyncio

from argos_agent.daemon.manager import RunManager
from argos_agent.daemon.registry import RunRegistry
from argos_agent.daemon.server import DaemonHTTPServer
from argos_agent.daemon.worktree import WorktreeManager


@pytest_asyncio.fixture
async def focus_server(tmp_path: Path):
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


async def _req(socket_path, method, path, *, session_id=None, body=None):
    from argos_agent.daemon.client import DaemonClient
    cli = DaemonClient(socket_path, timeout=3.0)
    return await cli._request(method, path, session_id=session_id, body=body)


async def _create_session(socket_path) -> str:
    status, _, raw = await _req(socket_path, "POST", "/sessions")
    return json.loads(raw.decode("utf-8"))["session_id"]


@pytest.mark.asyncio
async def test_focus_endpoint_sets_session(focus_server, tmp_path: Path):
    srv, _, reg = focus_server
    sid = await _create_session(srv.socket_path)
    status, _, raw = await _req(srv.socket_path, "POST", "/runs",
                                 session_id=sid, body={"goal": "x"})
    rid = json.loads(raw.decode("utf-8"))["run_id"]
    status, _, raw = await _req(srv.socket_path, "POST", f"/runs/{rid}/focus",
                                 session_id=sid)
    assert status == 200
    body = json.loads(raw.decode("utf-8"))
    assert body["focus_session_id"] == sid
    assert reg.get(rid).focus_session_id == sid


@pytest.mark.asyncio
async def test_focus_unknown_run_returns_404(focus_server, tmp_path: Path):
    srv, _, _ = focus_server
    sid = await _create_session(srv.socket_path)
    status, _, raw = await _req(srv.socket_path, "POST",
                                 "/runs/deadbeef0001/focus", session_id=sid)
    assert status == 404


@pytest.mark.asyncio
async def test_focus_missing_session_returns_400(focus_server, tmp_path: Path):
    srv, _, _ = focus_server
    status, _, raw = await _req(srv.socket_path, "POST", "/runs/abc/focus")
    assert status == 400


@pytest.mark.asyncio
async def test_multiple_focus_calls_last_wins(focus_server, tmp_path: Path):
    srv, _, reg = focus_server
    sid1 = await _create_session(srv.socket_path)
    sid2 = await _create_session(srv.socket_path)
    status, _, raw = await _req(srv.socket_path, "POST", "/runs",
                                 session_id=sid1, body={"goal": "x"})
    rid = json.loads(raw.decode("utf-8"))["run_id"]
    await _req(srv.socket_path, "POST", f"/runs/{rid}/focus", session_id=sid1)
    assert reg.get(rid).focus_session_id == sid1
    await _req(srv.socket_path, "POST", f"/runs/{rid}/focus", session_id=sid2)
    assert reg.get(rid).focus_session_id == sid2


@pytest.mark.asyncio
async def test_focus_can_clear_session(focus_server, tmp_path: Path):
    """focus 也能置空(PASS /runs/{id}/focus with sid 仍能设;本期不实现 clear,留 v1.1)。"""
    srv, _, reg = focus_server
    sid = await _create_session(srv.socket_path)
    status, _, raw = await _req(srv.socket_path, "POST", "/runs",
                                 session_id=sid, body={"goal": "x"})
    rid = json.loads(raw.decode("utf-8"))["run_id"]
    await _req(srv.socket_path, "POST", f"/runs/{rid}/focus", session_id=sid)
    assert reg.get(rid).focus_session_id == sid
