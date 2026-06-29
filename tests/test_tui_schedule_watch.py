"""Task 2.3: /schedule and /watch slash commands create StandingOrders via daemon.

Covers:
  T1. /schedule every 1h: summarize logs → POST /orders with kind=schedule
  T2. /watch *.py run tests → POST /orders with kind=file_trigger
  T3. Inline mode (no daemon) → honest daemon-required message, no crash
  T4. Malformed /schedule (missing ':') → usage hint
  T5. Malformed /watch (missing goal) → usage hint
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from argos.tui.app import ArgosApp
from argos.tui.commands import parse_slash
from argos.tui.fakeloop import FakeLoop
from argos.tui.widgets.transcript import Transcript


def _make_app() -> ArgosApp:
    return ArgosApp(loop_factory=lambda: FakeLoop())


async def _dispatch(app: ArgosApp, text: str) -> str:
    await app._dispatch_slash(parse_slash(text))
    return app.query_one("#transcript", Transcript).rendered_text


def _mock_daemon_client(status: int = 201, data: dict | None = None) -> MagicMock:
    client = MagicMock()
    client.create_order = AsyncMock(return_value=(status, data or {"id": "abc123"}))
    return client


# ── T1: /schedule in daemon mode ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_schedule_posts_order_to_daemon() -> None:
    """T1: /schedule every 1h: summarize logs → create_order called with kind=schedule."""
    app = _make_app()
    async with app.run_test() as pilot:
        await pilot.pause()
        # wire a mock daemon client
        app._with_daemon = True
        app._daemon_client = _mock_daemon_client()
        app._daemon_session_id = "sess-1"

        txt = await _dispatch(app, "/schedule every 1h: summarize logs")

    app._daemon_client.create_order.assert_called_once()
    call_body = app._daemon_client.create_order.call_args[0][0]
    assert call_body["kind"] == "schedule"
    assert call_body["schedule"] == "every 1h"
    assert call_body["goal_template"] == "summarize logs"
    assert "abc123" in txt or "created" in txt.lower()


# ── T2: /watch in daemon mode ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_watch_posts_order_to_daemon() -> None:
    """T2: /watch *.py run tests → create_order called with kind=file_trigger."""
    app = _make_app()
    async with app.run_test() as pilot:
        await pilot.pause()
        app._with_daemon = True
        app._daemon_client = _mock_daemon_client()
        app._daemon_session_id = "sess-1"

        txt = await _dispatch(app, "/watch *.py run tests")

    app._daemon_client.create_order.assert_called_once()
    call_body = app._daemon_client.create_order.call_args[0][0]
    assert call_body["kind"] == "file_trigger"
    assert call_body["trigger_glob"] == "*.py"
    assert call_body["goal_template"] == "run tests"
    assert "abc123" in txt or "created" in txt.lower()


# ── T3: inline mode (no daemon) → honest message ─────────────────────────────


@pytest.mark.asyncio
async def test_schedule_no_daemon_honest_message() -> None:
    """T3a: /schedule in inline mode emits daemon-required message, no crash."""
    app = _make_app()
    async with app.run_test() as pilot:
        await pilot.pause()
        # default: _with_daemon=False, _daemon_client=None
        txt = await _dispatch(app, "/schedule every 1h: summarize logs")

    assert "daemon" in txt.lower() or "argosd" in txt.lower()
    # no AttributeError / crash — if we're here the test passed


@pytest.mark.asyncio
async def test_watch_no_daemon_honest_message() -> None:
    """T3b: /watch in inline mode emits daemon-required message, no crash."""
    app = _make_app()
    async with app.run_test() as pilot:
        await pilot.pause()
        txt = await _dispatch(app, "/watch *.py run tests")

    assert "daemon" in txt.lower() or "argosd" in txt.lower()


# ── T4: malformed /schedule (missing ':') → usage hint ───────────────────────


@pytest.mark.asyncio
async def test_schedule_malformed_no_colon() -> None:
    """T4: /schedule without ':' separator → usage hint, no crash."""
    app = _make_app()
    async with app.run_test() as pilot:
        await pilot.pause()
        app._with_daemon = True
        app._daemon_client = _mock_daemon_client()
        app._daemon_session_id = "sess-1"

        txt = await _dispatch(app, "/schedule every 1h summarize logs")

    # usage hint — no order created
    app._daemon_client.create_order.assert_not_called()
    assert "schedule" in txt.lower()


# ── T5: malformed /watch (missing goal) → usage hint ─────────────────────────


@pytest.mark.asyncio
async def test_watch_malformed_no_goal() -> None:
    """T5: /watch with only glob and no goal → usage hint, no crash."""
    app = _make_app()
    async with app.run_test() as pilot:
        await pilot.pause()
        app._with_daemon = True
        app._daemon_client = _mock_daemon_client()
        app._daemon_session_id = "sess-1"

        txt = await _dispatch(app, "/watch *.py")

    app._daemon_client.create_order.assert_not_called()
    assert "watch" in txt.lower()
