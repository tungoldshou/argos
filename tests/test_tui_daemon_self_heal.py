from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from argos.daemon.client import DaemonClient, DaemonError
from argos.daemon.protocol import CODE_MISSING_SESSION


def test_daemon_error_exposes_status_and_code():
    c = DaemonClient(Path("/tmp/_argos_fake.sock"))
    with pytest.raises(DaemonError) as ei:
        c._check(
            401,
            {"code": "missing_session", "error": "session expired or unknown"},
            (201,),
        )
    assert ei.value.status == 401
    assert ei.value.code == "missing_session"
    assert "missing_session" in str(ei.value)


def test_daemon_error_plain_message_defaults_safe():
    e = DaemonError("empty response")
    assert e.code == ""
    assert e.status is None


def _app_with_fake_client(create_run_side_effect, *, new_sid="sess-new"):
    from argos.tui.app import ArgosApp

    app = ArgosApp()
    app._with_daemon = True
    app._workspace = Path("/tmp")
    app._daemon_session_id = "sess-old"
    fake = AsyncMock()
    fake.create_run = AsyncMock(side_effect=create_run_side_effect)
    fake.create_session = AsyncMock(return_value=new_sid)
    app._daemon_client = fake
    return app, fake


@pytest.mark.asyncio
async def test_daemon_create_run_retries_after_rehandshake_on_missing_session():
    expired = DaemonError("HTTP 401 (code=missing_session): session expired or unknown",
                          status=401, code=CODE_MISSING_SESSION)
    app, fake = _app_with_fake_client([expired, "run-2"], new_sid="sess-new")

    run_id = await app._daemon_create_run("hello", [])

    assert run_id == "run-2"
    assert app._daemon_session_id == "sess-new"
    assert fake.create_session.await_count == 1
    assert fake.create_run.await_count == 2


@pytest.mark.asyncio
async def test_daemon_create_run_propagates_non_session_errors():
    busy = DaemonError("HTTP 409 (code=busy): run in flight", status=409, code="busy")
    app, fake = _app_with_fake_client([busy])

    with pytest.raises(DaemonError) as ei:
        await app._daemon_create_run("hello", [])
    assert ei.value.code == "busy"
    assert fake.create_session.await_count == 0
    assert fake.create_run.await_count == 1


@pytest.mark.asyncio
async def test_daemon_create_run_happy_path_no_rehandshake():
    app, fake = _app_with_fake_client(["run-1"])
    run_id = await app._daemon_create_run("hello", [])
    assert run_id == "run-1"
    assert fake.create_session.await_count == 0
    assert app._daemon_session_id == "sess-old"


@pytest.mark.asyncio
async def test_heartbeat_tick_pings_daemon():
    from argos.tui.app import ArgosApp

    app = ArgosApp()
    app._with_daemon = True
    app._daemon_session_id = "sess-1"
    fake = AsyncMock()
    fake.heartbeat = AsyncMock(return_value={"ok": True})
    app._daemon_client = fake

    await app._daemon_heartbeat_tick()

    fake.heartbeat.assert_awaited_once_with("sess-1")


@pytest.mark.asyncio
async def test_heartbeat_tick_rehandshakes_when_session_reaped():
    from argos.tui.app import ArgosApp

    app = ArgosApp()
    app._with_daemon = True
    app._daemon_session_id = "sess-old"
    fake = AsyncMock()
    fake.heartbeat = AsyncMock(side_effect=DaemonError(
        "HTTP 401 (code=missing_session): session expired or unknown",
        status=401, code=CODE_MISSING_SESSION))
    fake.create_session = AsyncMock(return_value="sess-fresh")
    app._daemon_client = fake

    await app._daemon_heartbeat_tick()

    assert app._daemon_session_id == "sess-fresh"
    fake.create_session.assert_awaited_once()


@pytest.mark.asyncio
async def test_heartbeat_tick_noop_when_inline():
    from argos.tui.app import ArgosApp

    app = ArgosApp()
    app._with_daemon = False
    app._daemon_client = None
    app._daemon_session_id = None

    await app._daemon_heartbeat_tick()
