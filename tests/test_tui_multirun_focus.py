from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import AsyncIterator
from unittest.mock import patch

import pytest
import pytest_asyncio

from argos.daemon.manager import RunManager
from argos.daemon.registry import RunRegistry
from argos.daemon.worktree import WorktreeManager


class _ScriptLoop:
    def __init__(self, events: list[dict]):
        self._events = events

    async def run(self, goal: str, session_id: str) -> AsyncIterator[dict]:
        for ev in self._events:
            yield ev


@pytest_asyncio.fixture
async def mr_daemon(tmp_path: Path):
    runs_dir = tmp_path / "runs"
    index_path = tmp_path / "index.json"
    socket_path = tmp_path / "daemon.sock"
    manager = RunManager(runs_dir=runs_dir, index_path=index_path)
    registry = RunRegistry(max_concurrent=5, max_history=100)
    worktree = WorktreeManager(base_dir=tmp_path / "wt")
    from argos.daemon.server import DaemonHTTPServer
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




@pytest.mark.asyncio
async def test_app_compose_mounts_tab_strip():
    from argos.tui.app import ArgosApp
    from argos.tui.widgets.tab_strip import TabStrip

    app = ArgosApp()
    async with app.run_test() as pilot:
        strip = app.query_one(TabStrip)
        assert strip is not None


@pytest.mark.asyncio
async def test_app_calls_focus_on_tab_change(mr_daemon, tmp_path: Path):
    srv, _, reg = mr_daemon
    from argos.daemon.client import DaemonClient
    from argos.tui.app import ArgosApp
    from argos.tui.widgets.tab_strip import TabStrip

    app = ArgosApp()
    app._daemon_client = DaemonClient(srv.socket_path)
    app._with_daemon = True
    sid = await app._daemon_client.create_session()
    app._daemon_session_id = sid
    status, _, raw = await app._daemon_client._request(
        "POST", "/runs", session_id=sid, body={"goal": "g1"},
    )
    rid1 = json.loads(raw.decode("utf-8"))["run_id"]
    status, _, raw = await app._daemon_client._request(
        "POST", "/runs", session_id=sid, body={"goal": "g2"},
    )
    rid2 = json.loads(raw.decode("utf-8"))["run_id"]
    status, _, raw = await app._daemon_client._request(
        "POST", f"/runs/{rid2}/focus", session_id=sid,
    )
    assert status == 200
    assert reg.get(rid2).focus_session_id == sid
    async with app.run_test() as pilot:
        strip = app.query_one(TabStrip)
        strip.update_tabs(
            [
                {"run_id": rid1, "goal": "g1", "state": "running", "cost_usd": 0.01},
                {"run_id": rid2, "goal": "g2", "state": "running", "cost_usd": 0.02},
            ],
            active=rid1,
        )
        reg.set_focus(run_id=rid2, session_id=None)
        assert reg.get(rid2).focus_session_id is None
        await app._on_tab_activated(rid2)
        await pilot.pause()
    assert reg.get(rid2).focus_session_id == sid


@pytest.mark.asyncio
async def test_app_handles_tab_activated_message(mr_daemon, tmp_path: Path):
    from argos.daemon.client import DaemonClient
    from argos.tui.app import ArgosApp

    app = ArgosApp()
    async with app.run_test() as pilot:
        class FakeClient:
            def __init__(self):
                self.focused = []

            async def _request(self, method, path, *, session_id=None, body=None):
                if "/focus" in path:
                    self.focused.append(path)
                return 200, {}, b"{}"
        app._daemon_client = FakeClient()
        app._daemon_session_id = "sess"
        app._daemon_run_id = "a" * 12
        app._with_daemon = True
        await app._on_tab_activated("b" * 12)
        await pilot.pause()
        assert app._daemon_client.focused == ["/runs/" + "b" * 12 + "/focus"]
        assert app._daemon_run_id == "b" * 12


@pytest.mark.asyncio
async def test_app_does_not_switch_active_tab_when_focus_returns_non_200():
    from argos.tui.app import ArgosApp
    from argos.tui.widgets.tab_strip import TabStrip

    app = ArgosApp()

    class FakeClient:
        async def _request(self, method, path, *, session_id=None, body=None):
            return 403, {}, b'{"code":"session_readonly","error":"readonly"}'

    app._daemon_client = FakeClient()
    app._daemon_session_id = "sess"
    app._daemon_run_id = "a" * 12
    app._with_daemon = True
    async with app.run_test() as pilot:
        strip = app.query_one(TabStrip)
        strip.update_tabs(
            [
                {"run_id": "a" * 12, "goal": "g1", "state": "running", "cost_usd": 0.01},
                {"run_id": "b" * 12, "goal": "g2", "state": "running", "cost_usd": 0.02},
            ],
            active="a" * 12,
        )
        await app._on_tab_activated("b" * 12)
        await pilot.pause()
        assert app._daemon_run_id == "a" * 12
        assert strip.get_active() == "a" * 12




@pytest.mark.asyncio
async def test_runs_command_shows_all_runs_with_cost(mr_daemon, tmp_path: Path):
    from argos.daemon.client import DaemonClient
    from argos.tui.app import ArgosApp

    srv, _, reg = mr_daemon
    app = ArgosApp()
    app._daemon_client = DaemonClient(srv.socket_path)
    sid = await app._daemon_client.create_session()
    app._daemon_session_id = sid
    app._with_daemon = True
    status, _, raw = await app._daemon_client._request(
        "POST", "/runs", session_id=sid, body={"goal": "alpha"},
    )
    rid1 = json.loads(raw.decode("utf-8"))["run_id"]
    status, _, raw = await app._daemon_client._request(
        "POST", "/runs", session_id=sid, body={"goal": "beta"},
    )
    rid2 = json.loads(raw.decode("utf-8"))["run_id"]
    reg.add_cost(run_id=rid1, tokens_in_delta=100, tokens_out_delta=20, cost_usd_delta=0.01)
    reg.mark(run_id=rid1, state="running")
    reg.mark(run_id=rid2, state="completed")
    from argos.tui.widgets.transcript import Transcript
    async with app.run_test() as pilot:
        log_widget = app.query_one(Transcript)
        await app._runs_cmd(log_widget, "")
        await pilot.pause()
        text = log_widget.render()
        runs = await app._daemon_client.list_runs(sid)
        assert any(r["run_id"] == rid1 and r["cost_usd"] == 0.01 for r in runs)
        assert any(r["run_id"] == rid2 for r in runs)


@pytest.mark.asyncio
async def test_runs_command_observer_shows_readonly_banner(mr_daemon, tmp_path: Path):
    from argos.daemon.client import DaemonClient
    from argos.tui.app import ArgosApp

    srv, _, _ = mr_daemon
    app = ArgosApp()
    app._daemon_client = DaemonClient(srv.socket_path)
    sid1 = await app._daemon_client.create_session()
    sid2 = await app._daemon_client.create_session()   # observer
    app._daemon_session_id = sid2
    app._with_daemon = True
    async with app.run_test() as pilot:
        from argos.tui.widgets.transcript import Transcript
        log_widget = app.query_one(Transcript)
        await app._runs_cmd(log_widget, "")
        await pilot.pause()
        rec = srv.sessions.get(sid2)
        assert rec.role == "observer"


@pytest.mark.asyncio
async def test_app_handles_observer_readonly_focus():
    from argos.tui.app import ArgosApp

    app = ArgosApp()
    class FakeClient:
        async def _request(self, method, path, *, session_id=None, body=None):
            if "/focus" in path:
                from argos.daemon.client import DaemonError
                raise DaemonError("HTTP 403 (code=session_readonly): ...")
            return 200, {}, b"{}"
    app._daemon_client = FakeClient()
    app._daemon_session_id = "sess"
    app._daemon_run_id = "a" * 12
    app._with_daemon = True
    async with app.run_test() as pilot:
        await app._on_tab_activated("b" * 12)
        await pilot.pause()
    assert app._daemon_run_id == "a" * 12
