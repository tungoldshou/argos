from __future__ import annotations

import asyncio
import json
import time
import uuid
from pathlib import Path
from typing import AsyncIterator

import pytest
import pytest_asyncio

from argos.daemon.manager import RunManager
from argos.daemon.server import DaemonHTTPServer


# ── fixtures ────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def server(tmp_path: Path):
    runs_dir = tmp_path / "runs"
    index_path = tmp_path / "index.json"
    socket_path = tmp_path / "daemon.sock"
    manager = RunManager(runs_dir=runs_dir, index_path=index_path)
    srv = DaemonHTTPServer(manager=manager, socket_path=socket_path)
    await srv.start()
    try:
        yield srv, manager
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


# ── /health /version ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_health_endpoint(tmp_path: Path):
    socket_path = tmp_path / "s.sock"
    runs_dir = tmp_path / "runs"
    mgr = RunManager(runs_dir=runs_dir, index_path=tmp_path / "i.json")
    srv = DaemonHTTPServer(manager=mgr, socket_path=socket_path)
    await srv.start()
    try:
        status, _, raw = await _req(socket_path, "GET", "/health")
        assert status == 200
        body = json.loads(raw.decode("utf-8"))
        assert body["status"] == "ok"
        assert "uptime_s" in body
        assert body["other_tuis"] == 0
    finally:
        await srv.stop()
        mgr.close()


@pytest.mark.asyncio
async def test_version_endpoint(tmp_path: Path):
    socket_path = tmp_path / "s.sock"
    mgr = RunManager(runs_dir=tmp_path / "runs", index_path=tmp_path / "i.json")
    srv = DaemonHTTPServer(manager=mgr, socket_path=socket_path)
    await srv.start()
    try:
        status, _, raw = await _req(socket_path, "GET", "/version")
        assert status == 200
        body = json.loads(raw.decode("utf-8"))
        from argos import __version__ as _argos_version
        from argos.protocol import PROTOCOL_VERSION
        assert body["protocol"] == PROTOCOL_VERSION
        assert body["daemon"] == _argos_version
    finally:
        await srv.stop()
        mgr.close()


# ── /sessions ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_session(tmp_path: Path):
    socket_path = tmp_path / "s.sock"
    mgr = RunManager(runs_dir=tmp_path / "runs", index_path=tmp_path / "i.json")
    srv = DaemonHTTPServer(manager=mgr, socket_path=socket_path)
    await srv.start()
    try:
        status, _, raw = await _req(socket_path, "POST", "/sessions")
        assert status == 201
        sid = json.loads(raw.decode("utf-8"))["session_id"]
        uuid.UUID(sid)
    finally:
        await srv.stop()
        mgr.close()


@pytest.mark.asyncio
async def test_missing_session_header_returns_400(tmp_path: Path):
    socket_path = tmp_path / "s.sock"
    mgr = RunManager(runs_dir=tmp_path / "runs", index_path=tmp_path / "i.json")
    srv = DaemonHTTPServer(manager=mgr, socket_path=socket_path)
    await srv.start()
    try:
        status, _, raw = await _req(socket_path, "GET", "/runs")
        assert status == 400
        body = json.loads(raw.decode("utf-8"))
        assert body["code"] == "missing_session"
    finally:
        await srv.stop()
        mgr.close()


# ── /runs POST/GET ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_run_returns_id(server, tmp_path: Path):
    srv, _ = server
    sid = await _create_session(srv.socket_path)
    status, _, raw = await _req(srv.socket_path, "POST", "/runs",
                                 session_id=sid, body={"goal": "refactor auth.py"})
    assert status == 201
    rid = json.loads(raw.decode("utf-8"))["run_id"]
    assert len(rid) == 12
    int(rid, 16)   # hex


@pytest.mark.asyncio
async def test_create_run_persists_owner_session_for_context(server):
    """POST /runs must keep the TUI session id for multi-turn model context."""
    srv, mgr = server
    sid = await _create_session(srv.socket_path)
    status, _, raw = await _req(
        srv.socket_path, "POST", "/runs",
        session_id=sid, body={"goal": "帮我查看今天的天气"},
    )
    assert status == 201
    rid = json.loads(raw.decode("utf-8"))["run_id"]
    meta = next(mgr.store.replay(rid))
    assert meta["session_id"] == sid
    assert mgr.get_run(rid).session_id == sid


@pytest.mark.asyncio
async def test_create_run_missing_goal(server):
    srv, _ = server
    sid = await _create_session(srv.socket_path)
    status, _, raw = await _req(srv.socket_path, "POST", "/runs",
                                 session_id=sid, body={})
    assert status == 400
    body = json.loads(raw.decode("utf-8"))
    assert body["code"] == "bad_request"


@pytest.mark.asyncio
async def test_list_runs(server):
    srv, _ = server
    sid = await _create_session(srv.socket_path)
    await _req(srv.socket_path, "POST", "/runs", session_id=sid, body={"goal": "a"})
    await _req(srv.socket_path, "POST", "/runs", session_id=sid, body={"goal": "b"})
    status, _, raw = await _req(srv.socket_path, "GET", "/runs", session_id=sid)
    assert status == 200
    runs = json.loads(raw.decode("utf-8"))
    assert len(runs) >= 2


@pytest.mark.asyncio
async def test_get_run_meta(server):
    srv, mgr = server
    sid = await _create_session(srv.socket_path)
    status, _, raw = await _req(srv.socket_path, "POST", "/runs",
                                 session_id=sid, body={"goal": "x"})
    rid = json.loads(raw.decode("utf-8"))["run_id"]
    status, _, raw = await _req(srv.socket_path, "GET", f"/runs/{rid}",
                                 session_id=sid)
    assert status == 200
    body = json.loads(raw.decode("utf-8"))
    assert body["run_id"] == rid
    assert "state" in body



@pytest.mark.asyncio
async def test_pause_request_returns_202(server):
    srv, mgr = server
    sid = await _create_session(srv.socket_path)
    status, _, raw = await _req(srv.socket_path, "POST", "/runs",
                                 session_id=sid, body={"goal": "x"})
    rid = json.loads(raw.decode("utf-8"))["run_id"]
    status, _, raw = await _req(srv.socket_path, "POST", f"/runs/{rid}/pause",
                                 session_id=sid)
    assert status == 409


@pytest.mark.asyncio
async def test_pause_request_succeeds_on_running(server):
    srv, mgr = server
    sid = await _create_session(srv.socket_path)
    status, _, raw = await _req(srv.socket_path, "POST", "/runs",
                                 session_id=sid, body={"goal": "x"})
    rid = json.loads(raw.decode("utf-8"))["run_id"]
    mgr.mark_running(rid)
    status, _, raw = await _req(srv.socket_path, "POST", f"/runs/{rid}/pause",
                                 session_id=sid)
    assert status == 202
    body = json.loads(raw.decode("utf-8"))
    assert body["state"] == "pause_requested"


@pytest.mark.asyncio
async def test_cancel_returns_202_or_409(server):
    srv, mgr = server
    sid = await _create_session(srv.socket_path)
    status, _, raw = await _req(srv.socket_path, "POST", "/runs",
                                 session_id=sid, body={"goal": "x"})
    rid = json.loads(raw.decode("utf-8"))["run_id"]
    mgr.mark_running(rid)
    status, _, raw = await _req(srv.socket_path, "POST", f"/runs/{rid}/cancel",
                                 session_id=sid)
    assert status == 202



@pytest.mark.asyncio
async def test_sse_event_format(server):
    srv, mgr = server
    sid = await _create_session(srv.socket_path)
    status, _, raw = await _req(srv.socket_path, "POST", "/runs",
                                 session_id=sid, body={"goal": "x"})
    rid = json.loads(raw.decode("utf-8"))["run_id"]
    from argos.daemon.client import DaemonClient
    client = DaemonClient(srv.socket_path, timeout=3.0)
    gen = client.subscribe_events(rid, sid, since=0)
    ev = await asyncio.wait_for(anext(gen), timeout=3.0)
    assert ev["kind"] == "run_meta"
    assert ev["run_id"] == rid
    await gen.aclose()


# ── error paths ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_unknown_run_returns_404(server):
    srv, _ = server
    sid = await _create_session(srv.socket_path)
    status, _, raw = await _req(srv.socket_path, "GET", "/runs/deadbeef0001",
                                 session_id=sid)
    assert status == 404


@pytest.mark.asyncio
async def test_unknown_route_returns_404(server):
    srv, _ = server
    status, _, _ = await _req(srv.socket_path, "GET", "/no/such/route")
    assert status == 404


@pytest.mark.asyncio
async def test_create_run_with_verify_cmd_accepted(server):
    """POST /runs with verify_cmd in body → 201 (server accepts the field without error)."""
    srv, mgr = server
    sid = await _create_session(srv.socket_path)
    status, _, raw = await _req(
        srv.socket_path, "POST", "/runs",
        session_id=sid,
        body={"goal": "fix auth tests", "verify_cmd": "pytest -q tests/"},
    )
    assert status == 201, f"expected 201, got {status}: {raw.decode()}"
    rid = json.loads(raw.decode("utf-8"))["run_id"]
    assert len(rid) == 12


@pytest.mark.asyncio
async def test_approval_endpoint_no_worker_returns_404(server):
    srv, mgr = server
    sid = await _create_session(srv.socket_path)
    status, _, raw = await _req(srv.socket_path, "POST", "/runs",
                                 session_id=sid, body={"goal": "x"})
    rid = json.loads(raw.decode("utf-8"))["run_id"]
    status, _, raw = await _req(srv.socket_path, "POST",
                                 f"/runs/{rid}/approval/abc123456789",
                                 session_id=sid, body={"decision": "once"})
    assert status == 404
    body = json.loads(raw.decode("utf-8"))
    assert "worker" in body.get("error", "").lower() or body.get("code") == "not_found"


@pytest.mark.asyncio
async def test_approval_endpoint_invalid_decision(server):
    srv, mgr = server
    sid = await _create_session(srv.socket_path)
    status, _, raw = await _req(srv.socket_path, "POST", "/runs",
                                 session_id=sid, body={"goal": "x"})
    rid = json.loads(raw.decode("utf-8"))["run_id"]
    status, _, raw = await _req(srv.socket_path, "POST",
                                 f"/runs/{rid}/approval/abc123456789",
                                 session_id=sid, body={"decision": "approve"})
    assert status == 400


# ── list_runs state filter ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_runs_filter_state(server):
    srv, mgr = server
    sid = await _create_session(srv.socket_path)
    status, _, raw = await _req(srv.socket_path, "POST", "/runs",
                                 session_id=sid, body={"goal": "x"})
    rid = json.loads(raw.decode("utf-8"))["run_id"]
    mgr.mark_running(rid)
    status, _, raw = await _req(srv.socket_path, "GET", "/runs?state=running",
                                 session_id=sid)
    runs = json.loads(raw.decode("utf-8"))
    assert all(r["state"] == "running" for r in runs)
    assert any(r["run_id"] == rid for r in runs)


# ── /orders session-header tests (A + E from final-review) ────────────────────

@pytest.mark.asyncio
async def test_post_orders_with_session_header_returns_201(server) -> None:
    """POST /orders WITH valid X-Argos-Session header → 201 (real server, no mock).

    This is the server-side complement of fix A: create_order now sends
    session_id, so the server's _require_session gate passes.
    """
    srv, _ = server
    sid = await _create_session(srv.socket_path)
    status, _, raw = await _req(
        srv.socket_path, "POST", "/orders",
        session_id=sid,
        body={
            "utterance": "/schedule every 1h: test",
            "kind": "schedule",
            "schedule": "every 1h",
            "goal_template": "test",
        },
    )
    assert status == 201, f"expected 201 with valid session, got {status}: {raw.decode()}"


@pytest.mark.asyncio
async def test_post_orders_without_session_header_returns_400(server) -> None:
    """POST /orders WITHOUT X-Argos-Session header → 400 (missing_session).

    Proves the pre-fix bug: calling create_order without session_id would
    always hit this gate and fail.
    """
    srv, _ = server
    status, _, raw = await _req(
        srv.socket_path, "POST", "/orders",
        # deliberately omit session_id
        body={
            "utterance": "/schedule every 1h: test",
            "kind": "schedule",
            "schedule": "every 1h",
            "goal_template": "test",
        },
    )
    assert status == 400, f"expected 400 without session header, got {status}: {raw.decode()}"
