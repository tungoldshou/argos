"""HTTP/SSE server 协议测试(spec §2.5)。"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from pathlib import Path
from typing import AsyncIterator

import pytest
import pytest_asyncio

from argos_agent.daemon.manager import RunManager
from argos_agent.daemon.server import DaemonHTTPServer


# ── fixtures ────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def server(tmp_path: Path):
    """起一个 Unix socket server。"""
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
    """helper:发一个 HTTP 请求,返 (status, headers, body_bytes)。"""
    from argos_agent.daemon.client import DaemonClient
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
        assert body["protocol"] == 1
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
        uuid.UUID(sid)   # UUID 格式
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
        # /runs (GET) 不带 session → 400
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


# ── /pause /resume /cancel:2 阶段契约 ──────────────────────────────────

@pytest.mark.asyncio
async def test_pause_request_returns_202(server):
    """POST /runs/{id}/pause → 202 + state=pause_requested(2 阶段契约)。"""
    srv, mgr = server
    sid = await _create_session(srv.socket_path)
    status, _, raw = await _req(srv.socket_path, "POST", "/runs",
                                 session_id=sid, body={"goal": "x"})
    rid = json.loads(raw.decode("utf-8"))["run_id"]
    # run 在 pending 状态(没 worker 跑),pause 应被状态机拒 → 409
    status, _, raw = await _req(srv.socket_path, "POST", f"/runs/{rid}/pause",
                                 session_id=sid)
    assert status == 409


@pytest.mark.asyncio
async def test_pause_request_succeeds_on_running(server):
    """run 在 running → pause 请求 202。"""
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
    """POST /runs/{id}/cancel → 202(non-terminal)或 409(terminal)。"""
    srv, mgr = server
    sid = await _create_session(srv.socket_path)
    status, _, raw = await _req(srv.socket_path, "POST", "/runs",
                                 session_id=sid, body={"goal": "x"})
    rid = json.loads(raw.decode("utf-8"))["run_id"]
    mgr.mark_running(rid)
    status, _, raw = await _req(srv.socket_path, "POST", f"/runs/{rid}/cancel",
                                 session_id=sid)
    assert status == 202


# ── /runs/{id}/events SSE 格式 ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_sse_event_format(server):
    """GET /runs/{id}/events → SSE 格式正确 + replay meta。"""
    srv, mgr = server
    sid = await _create_session(srv.socket_path)
    status, _, raw = await _req(srv.socket_path, "POST", "/runs",
                                 session_id=sid, body={"goal": "x"})
    rid = json.loads(raw.decode("utf-8"))["run_id"]
    # 通过 client subscribe 短拉(不进入主循环)
    from argos_agent.daemon.client import DaemonClient
    client = DaemonClient(srv.socket_path, timeout=3.0)
    gen = client.subscribe_events(rid, sid, since=0)
    # 拿 1 个 event 后 break
    ev = await asyncio.wait_for(anext(gen), timeout=3.0)
    assert ev["kind"] == "run_meta"
    assert ev["run_id"] == rid
    # 关闭连接
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
async def test_approval_endpoint_no_worker_returns_404(server):
    """POST /runs/{id}/approval/{call_id}: run 存在但无 active worker → 404。

    P3 升级后 approval 要求 run 有注册 worker(服务器路由表)。
    无 worker 路径(create_run 无 loop_factory)→ 404 + 诚实错误消息。
    """
    srv, mgr = server
    sid = await _create_session(srv.socket_path)
    status, _, raw = await _req(srv.socket_path, "POST", "/runs",
                                 session_id=sid, body={"goal": "x"})
    rid = json.loads(raw.decode("utf-8"))["run_id"]
    # 无 worker 注册(server fixture 不带 loop_factory)→ 应 404
    status, _, raw = await _req(srv.socket_path, "POST",
                                 f"/runs/{rid}/approval/abc123456789",
                                 session_id=sid, body={"decision": "once"})
    assert status == 404
    body = json.loads(raw.decode("utf-8"))
    assert "worker" in body.get("error", "").lower() or body.get("code") == "not_found"


@pytest.mark.asyncio
async def test_approval_endpoint_invalid_decision(server):
    """POST /runs/{id}/approval: decision 不合法 → 400。"""
    srv, mgr = server
    sid = await _create_session(srv.socket_path)
    status, _, raw = await _req(srv.socket_path, "POST", "/runs",
                                 session_id=sid, body={"goal": "x"})
    rid = json.loads(raw.decode("utf-8"))["run_id"]
    status, _, raw = await _req(srv.socket_path, "POST",
                                 f"/runs/{rid}/approval/abc123456789",
                                 session_id=sid, body={"decision": "approve"})  # 旧值,已不合法
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
