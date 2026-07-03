"""Internal documentation."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import pytest_asyncio

from argos.daemon.manager import RunManager
from argos.daemon.registry import RunRegistry
from argos.daemon.server import DaemonHTTPServer
from argos.daemon.sessions import SessionRegistry
from argos.daemon.worktree import WorktreeManager




@pytest.mark.asyncio
async def test_first_session_is_owner():
    reg = SessionRegistry()
    rec = await reg.create()
    assert rec.role == "owner"


@pytest.mark.asyncio
async def test_second_session_is_observer():
    reg = SessionRegistry()
    a = await reg.create()
    b = await reg.create()
    assert a.role == "owner"
    assert b.role == "observer"


@pytest.mark.asyncio
async def test_remove_owner_promotes_oldest_observer():
    reg = SessionRegistry()
    a = await reg.create()
    b = await reg.create()
    c = await reg.create()
    new_owner = await reg.promote_oldest_observer_after_remove(a.session_id)
    assert new_owner == b.session_id
    rec_b = reg.get(b.session_id)
    assert rec_b.role == "owner"


@pytest.mark.asyncio
async def test_remove_owner_no_observer_returns_none():
    reg = SessionRegistry()
    a = await reg.create()
    new = await reg.promote_oldest_observer_after_remove(a.session_id)
    assert new is None
    assert reg.list_active() == []


@pytest.mark.asyncio
async def test_remove_observer_does_not_promote():
    reg = SessionRegistry()
    a = await reg.create()
    b = await reg.create()
    new = await reg.promote_oldest_observer_after_remove(b.session_id)
    assert new is None
    assert reg.get(a.session_id).role == "owner"
    assert reg.get(b.session_id) is None


@pytest.mark.asyncio
async def test_promote_only_observer():
    """Internal documentation."""
    reg = SessionRegistry()
    a = await reg.create()
    b = await reg.create()
    await reg.promote_oldest_observer_after_remove(a.session_id)
    assert reg.get(b.session_id).role == "owner"




@pytest_asyncio.fixture
async def owner_server(tmp_path: Path):
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
    from argos.daemon.client import DaemonClient
    cli = DaemonClient(socket_path, timeout=3.0)
    return await cli._request(method, path, session_id=session_id, body=body)


async def _create_session(socket_path) -> str:
    status, _, raw = await _req(socket_path, "POST", "/sessions")
    return json.loads(raw.decode("utf-8"))["session_id"]


@pytest.mark.asyncio
async def test_owner_can_create_run(owner_server, tmp_path: Path):
    srv, _, _ = owner_server
    sid = await _create_session(srv.socket_path)
    status, _, _ = await _req(srv.socket_path, "POST", "/runs",
                               session_id=sid, body={"goal": "x"})
    assert status == 201


@pytest.mark.asyncio
async def test_observer_cannot_create_run(owner_server, tmp_path: Path):
    """Internal documentation."""
    srv, _, _ = owner_server
    sid1 = await _create_session(srv.socket_path)   # owner
    sid2 = await _create_session(srv.socket_path)   # observer
    assert sid1 != sid2
    status, _, raw = await _req(srv.socket_path, "POST", "/runs",
                                 session_id=sid2, body={"goal": "x"})
    assert status == 403
    body = json.loads(raw.decode("utf-8"))
    assert body["code"] == "session_readonly"


@pytest.mark.asyncio
async def test_observer_cannot_pause(owner_server, tmp_path: Path):
    srv, _, reg = owner_server
    sid1 = await _create_session(srv.socket_path)
    sid2 = await _create_session(srv.socket_path)
    status, _, raw = await _req(srv.socket_path, "POST", "/runs",
                                 session_id=sid1, body={"goal": "x"})
    rid = json.loads(raw.decode("utf-8"))["run_id"]
    reg.mark(run_id=rid, state="running")
    status, _, raw = await _req(srv.socket_path, "POST", f"/runs/{rid}/pause",
                                 session_id=sid2)
    assert status == 403


@pytest.mark.asyncio
async def test_observer_cannot_resume(owner_server, tmp_path: Path):
    srv, _, reg = owner_server
    sid1 = await _create_session(srv.socket_path)
    sid2 = await _create_session(srv.socket_path)
    status, _, raw = await _req(srv.socket_path, "POST", "/runs",
                                 session_id=sid1, body={"goal": "x"})
    rid = json.loads(raw.decode("utf-8"))["run_id"]
    reg.mark(run_id=rid, state="paused")
    status, _, _ = await _req(srv.socket_path, "POST", f"/runs/{rid}/resume",
                               session_id=sid2)
    assert status == 403


@pytest.mark.asyncio
async def test_observer_cannot_cancel(owner_server, tmp_path: Path):
    srv, _, reg = owner_server
    sid1 = await _create_session(srv.socket_path)
    sid2 = await _create_session(srv.socket_path)
    status, _, raw = await _req(srv.socket_path, "POST", "/runs",
                                 session_id=sid1, body={"goal": "x"})
    rid = json.loads(raw.decode("utf-8"))["run_id"]
    reg.mark(run_id=rid, state="running")
    status, _, _ = await _req(srv.socket_path, "POST", f"/runs/{rid}/cancel",
                               session_id=sid2)
    assert status == 403


@pytest.mark.asyncio
async def test_observer_cannot_focus(owner_server, tmp_path: Path):
    """Internal documentation."""
    srv, _, reg = owner_server
    sid1 = await _create_session(srv.socket_path)
    sid2 = await _create_session(srv.socket_path)
    status, _, raw = await _req(srv.socket_path, "POST", "/runs",
                                 session_id=sid1, body={"goal": "x"})
    rid = json.loads(raw.decode("utf-8"))["run_id"]
    status, _, _ = await _req(srv.socket_path, "POST", f"/runs/{rid}/focus",
                               session_id=sid2)
    assert status == 403


@pytest.mark.asyncio
async def test_observer_can_read(owner_server, tmp_path: Path):
    """Internal documentation."""
    srv, _, _ = owner_server
    sid1 = await _create_session(srv.socket_path)
    sid2 = await _create_session(srv.socket_path)
    status, _, raw = await _req(srv.socket_path, "POST", "/runs",
                                 session_id=sid1, body={"goal": "x"})
    rid = json.loads(raw.decode("utf-8"))["run_id"]
    status, _, _ = await _req(srv.socket_path, "GET", "/runs", session_id=sid2)
    assert status == 200
    status, _, _ = await _req(srv.socket_path, "GET", f"/runs/{rid}", session_id=sid2)
    assert status == 200


@pytest.mark.asyncio
async def test_owner_delete_session_promotes_observer(owner_server, tmp_path: Path):
    """Internal documentation."""
    srv, _, _ = owner_server
    sid1 = await _create_session(srv.socket_path)
    sid2 = await _create_session(srv.socket_path)
    status, _, _ = await _req(srv.socket_path, "DELETE", f"/sessions/{sid1}")
    assert status == 204
    status, _, _ = await _req(srv.socket_path, "POST", "/runs",
                               session_id=sid2, body={"goal": "x"})
    assert status == 201


@pytest.mark.asyncio
async def test_owner_lifecycle_sid_first_call_works(owner_server, tmp_path: Path):
    """Internal documentation."""
    srv, _, _ = owner_server
    sid = await _create_session(srv.socket_path)
    rec = srv.sessions.get(sid)
    assert rec.role == "owner"
    status, _, _ = await _req(srv.socket_path, "POST", "/runs",
                               session_id=sid, body={"goal": "x"})
    assert status == 201
