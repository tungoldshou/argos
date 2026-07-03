"""Internal documentation."""
from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── helpers ────────────────────────────────────────────────────────────────

def _make_app():
    """Internal documentation."""
    from argos.tui.app import ArgosApp
    app = ArgosApp()
    app.run_worker = MagicMock()
    return app


def _fake_suggestion_event():
    from argos.protocol.events import ProactiveSuggestionEvent
    return ProactiveSuggestionEvent(
        suggestion_id="sug-001",
        order_id="ord-001",
        goal="run tests",
        reason_human="Tests haven't run in a while",
        suggested_at=time.time(),
    )



def test_conductor_subscription_idempotent():
    """Internal documentation."""
    from argos.tui.daemon_source import DaemonEventSource

    app = _make_app()
    app._conductor_source = MagicMock()

    with patch("argos.tui.daemon_source.DaemonEventSource") as mock_cls:
        app._start_conductor_subscription(Path("/tmp/fake.sock"), "sess-x")

    mock_cls.assert_not_called()
    assert app.run_worker.call_count == 0



@pytest.mark.asyncio
async def test_setup_daemon_mode_starts_conductor_subscription(monkeypatch):
    """Internal documentation."""
    from argos.tui.app import ArgosApp
    from argos.daemon.client import DaemonClient

    monkeypatch.delenv("ARGOS_NO_DAEMON", raising=False)
    app = _make_app()

    status_bar_mock = MagicMock()

    def _query_one(selector, cls=None):
        if cls is not None and cls.__name__ == "StatusBar":
            return status_bar_mock
        raise Exception(f"not mounted: {selector}")

    app.query_one = _query_one

    called_with: list = []

    def _fake_start(sock, sid):
        called_with.append((sock, sid))

    app._start_conductor_subscription = _fake_start
    app._start_daemon_heartbeat = MagicMock()

    with patch("argos.tui.daemon_spawn.probe_or_spawn", new=AsyncMock(return_value=True)):
        with patch.object(DaemonClient, "create_session", new=AsyncMock(return_value="sess-abc")):
            with patch.dict(os.environ, {"ARGOS_DAEMON_SOCKET": "/tmp/_argos_test_conductor.sock"}):
                await app._setup_daemon_mode()

    assert len(called_with) == 1, "expected _start_conductor_subscription called once"
    _sock, sid = called_with[0]
    assert sid == "sess-abc"



@pytest.mark.asyncio
async def test_conductor_event_reaches_apply_event():
    """Internal documentation."""
    from argos.tui.daemon_source import DaemonEventSource
    from argos.protocol.events import ProactiveSuggestionEvent

    app = _make_app()
    suggestion = _fake_suggestion_event()

    captured_work: list = []

    def _capture_worker(work, exclusive=False):
        captured_work.append(work)
        return MagicMock()

    app.run_worker = _capture_worker

    # mock _apply_event
    applied: list = []

    async def _fake_apply(ev):
        applied.append(ev)

    app._apply_event = _fake_apply  # type: ignore[method-assign]

    # fake _subscribe_once: yield one ProactiveSuggestionEvent dict then end
    async def _fake_subscribe(since: int = 0):
        yield {
            "kind": "proactive_suggestion",
            "suggestion_id": suggestion.suggestion_id,
            "order_id": suggestion.order_id,
            "goal": suggestion.goal,
            "reason_human": suggestion.reason_human,
            "suggested_at": suggestion.suggested_at,
            "requires_confirmation": True,
            "action": "run",
            "_seq": 1,
        }

    with patch("argos.tui.daemon_source.DaemonEventSource") as mock_cls:
        fake_source = DaemonEventSource.__new__(DaemonEventSource)
        fake_source._stopped = False
        fake_source._last_seq = 0
        fake_source._max_retries = 3
        fake_source._run_id = "_conductor"
        fake_source._session_id = "sess-t"
        fake_source._socket_path = Path("/tmp/fake.sock")
        fake_source._subscribe_once = _fake_subscribe  # type: ignore[method-assign]
        mock_cls.return_value = fake_source

        app._start_conductor_subscription(Path("/tmp/fake.sock"), "sess-t")

    assert len(captured_work) == 1, "expected one worker"
    work = captured_work[0]
    await (work() if callable(work) else work)

    assert len(applied) == 1, f"expected 1 event applied, got {len(applied)}"
    ev = applied[0]
    assert isinstance(ev, ProactiveSuggestionEvent)
    assert ev.suggestion_id == suggestion.suggestion_id
    assert ev.goal == suggestion.goal



@pytest.mark.asyncio
async def test_no_conductor_subscription_in_inline_mode():
    """Internal documentation."""
    app = _make_app()
    called = []
    app._start_conductor_subscription = lambda *a: called.append(a)

    status_bar_mock = MagicMock()

    def _query_one(selector, cls=None):
        if cls is not None and cls.__name__ == "StatusBar":
            return status_bar_mock
        raise Exception(f"not mounted: {selector}")

    app.query_one = _query_one

    with patch.dict(os.environ, {"ARGOS_NO_DAEMON": "1"}):
        await app._setup_daemon_mode()

    assert called == [], "conductor subscription must not start in inline mode"
    assert app._kernel_mode == "inline"


# ── T5: conductor reconnect — _conductor_source resets to None after stream ends ──

@pytest.mark.asyncio
async def test_conductor_source_resets_to_none_after_stream_ends():
    """_stream_conductor finally block resets _conductor_source → None, allowing restart."""
    from argos.tui.daemon_source import DaemonEventSource

    app = _make_app()

    captured_work: list = []

    def _capture_worker(work, exclusive=False):
        captured_work.append(work)
        return MagicMock()

    app.run_worker = _capture_worker

    async def _fake_apply(ev):
        pass

    app._apply_event = _fake_apply  # type: ignore[method-assign]

    # empty stream — terminates immediately
    async def _empty_subscribe(since: int = 0):
        return
        yield  # make it an async generator  # noqa: unreachable

    with patch("argos.tui.daemon_source.DaemonEventSource") as mock_cls:
        fake_source = DaemonEventSource.__new__(DaemonEventSource)
        fake_source._stopped = False
        fake_source._last_seq = 0
        fake_source._max_retries = 0  # no retries — exit immediately
        fake_source._run_id = "_conductor"
        fake_source._session_id = "sess-t"
        fake_source._socket_path = Path("/tmp/fake.sock")
        fake_source._subscribe_once = _empty_subscribe  # type: ignore[method-assign]
        mock_cls.return_value = fake_source

        app._start_conductor_subscription(Path("/tmp/fake.sock"), "sess-t")

    assert len(captured_work) == 1
    # _conductor_source is set before stream starts
    assert app._conductor_source is not None

    # run the stream to completion
    work = captured_work[0]
    await (work() if callable(work) else work)

    # _conductor_source should be reset to None after stream ends
    assert app._conductor_source is None, (
        "_conductor_source must be None after stream completes (finally block)"
    )

    # can start a new subscription (idempotent guard now cleared)
    second_captured: list = []

    def _capture2(coro, exclusive=False):
        second_captured.append(coro)
        return MagicMock()

    app.run_worker = _capture2
    with patch("argos.tui.daemon_source.DaemonEventSource") as mock_cls2:
        mock_cls2.return_value = fake_source
        app._start_conductor_subscription(Path("/tmp/fake.sock"), "sess-t")

    assert len(second_captured) == 1, "second subscription should start after source reset"


# ── T6: create_order HTTP error → tui.orders.http_failed surfaced ────────────

@pytest.mark.asyncio
async def test_schedule_http_error_surfaces_http_failed_message():
    """create_order returning status=500 → TUI shows tui.orders.http_failed, no crash."""
    from argos.tui.app import ArgosApp
    from argos.tui.commands import parse_slash
    from argos.tui.fakeloop import FakeLoop
    from argos.tui.widgets.transcript import Transcript
    from argos.i18n import t

    app = ArgosApp(loop_factory=lambda **kw: FakeLoop())
    async with app.run_test() as pilot:
        await pilot.pause()
        app._with_daemon = True
        app._daemon_client = MagicMock()
        app._daemon_client.create_order = AsyncMock(return_value=(500, {"error": "internal"}))
        app._daemon_session_id = "sess-err"

        cmd = parse_slash("/schedule every 1h: test task")
        await app._dispatch_slash(cmd)
        txt = app.query_one("#transcript", Transcript).rendered_text

    expected = t("tui.orders.http_failed", status=500)
    assert "500" in txt or expected in txt, (
        f"TUI should surface http_failed message for status 500, got: {txt!r}"
    )
