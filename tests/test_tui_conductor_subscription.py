"""TUI conductor SSE 订阅测试(Task 2.5).

验收:_conductor DaemonEventSource 上推送的 ProactiveSuggestionEvent
通过 _start_conductor_subscription 最终到达 _apply_event 并触发渲染。
"""
from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── helpers ────────────────────────────────────────────────────────────────

def _make_app():
    """构造最小 ArgosApp(demo=True, 不起 TUI 事件循环)。"""
    from argos.tui.app import ArgosApp
    app = ArgosApp(demo=True)
    app.run_worker = MagicMock()  # 不真起 Textual worker
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


# ── T1: _start_conductor_subscription 幂等 ────────────────────────────────

def test_conductor_subscription_idempotent():
    """_start_conductor_subscription 第二次调用不重复起 worker。"""
    from argos.tui.daemon_source import DaemonEventSource

    app = _make_app()
    app._conductor_source = MagicMock()  # 模拟已存在订阅

    with patch("argos.tui.daemon_source.DaemonEventSource") as mock_cls:
        app._start_conductor_subscription(Path("/tmp/fake.sock"), "sess-x")

    mock_cls.assert_not_called()
    assert app.run_worker.call_count == 0


# ── T2: _setup_daemon_mode 成功后启动 conductor 订阅 ──────────────────────

@pytest.mark.asyncio
async def test_setup_daemon_mode_starts_conductor_subscription(monkeypatch):
    """daemon 连通后 _setup_daemon_mode 应调用 _start_conductor_subscription。"""
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
    app._start_daemon_heartbeat = MagicMock()  # 不起 set_interval

    with patch("argos.tui.daemon_spawn.probe_or_spawn", new=AsyncMock(return_value=True)):
        with patch.object(DaemonClient, "create_session", new=AsyncMock(return_value="sess-abc")):
            with patch.dict(os.environ, {"ARGOS_DAEMON_SOCKET": "/tmp/_argos_test_conductor.sock"}):
                await app._setup_daemon_mode()

    assert len(called_with) == 1, "expected _start_conductor_subscription called once"
    _sock, sid = called_with[0]
    assert sid == "sess-abc"


# ── T3: conductor SSE 事件到达 _apply_event ────────────────────────────────

@pytest.mark.asyncio
async def test_conductor_event_reaches_apply_event():
    """_conductor 流上的 ProactiveSuggestionEvent 经 _start_conductor_subscription 到达 _apply_event。

    模式:
      1. 构造 DaemonEventSource,monkey-patch _subscribe_once yield 一个事件后结束。
      2. 调用 _start_conductor_subscription — 它 run_worker 一个协程。
      3. 捕获该协程并 await 它(绕过 Textual worker 调度)。
      4. 断言 _apply_event 被调用且收到正确事件。
    """
    from argos.tui.daemon_source import DaemonEventSource
    from argos.protocol.events import ProactiveSuggestionEvent

    app = _make_app()
    suggestion = _fake_suggestion_event()

    # 捕获 run_worker 的协程参数
    captured_coro: list = []

    def _capture_worker(coro, exclusive=False):
        captured_coro.append(coro)
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

    assert len(captured_coro) == 1, "expected one worker coroutine"
    await captured_coro[0]

    assert len(applied) == 1, f"expected 1 event applied, got {len(applied)}"
    ev = applied[0]
    assert isinstance(ev, ProactiveSuggestionEvent)
    assert ev.suggestion_id == suggestion.suggestion_id
    assert ev.goal == suggestion.goal


# ── T4: inline 模式下不起 conductor 订阅 ─────────────────────────────────

@pytest.mark.asyncio
async def test_no_conductor_subscription_in_inline_mode():
    """ARGOS_NO_DAEMON=1(inline 模式)时 _setup_daemon_mode 不调 _start_conductor_subscription。"""
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
