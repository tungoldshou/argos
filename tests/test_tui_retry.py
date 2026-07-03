import pytest

from argos.tui.app import ArgosApp
from argos.tui.widgets.transcript import Transcript as TranscriptLog


def _make_app(*, run_active: bool, loop_factory, session_id: str = "sess-test") -> ArgosApp:
    app = ArgosApp.__new__(ArgosApp)
    app._session_id = session_id
    app._run_active = run_active
    app._loop_factory = loop_factory
    app._input_history = []
    app._input_history_max = 50
    return app


@pytest.mark.asyncio
async def test_retry_resends_last_user_message():
    class _StubStore:
        def get_messages(self, sid):
            return [
                {"role": "user", "text": "first"},
                {"role": "assistant", "text": "ok"},
                {"role": "user", "text": "second goal"},
            ]
    class _StubLoop:
        store = _StubStore()
    sent: list[str] = []
    async def _fake_start_run(goal: str) -> None:
        sent.append(goal)
    app = _make_app(run_active=False, loop_factory=lambda: _StubLoop())
    app.start_run = _fake_start_run  # type: ignore[method-assign]
    log = TranscriptLog()
    await app._retry(log)  # type: ignore[attr-defined]
    assert sent == ["second goal"]


@pytest.mark.asyncio
async def test_retry_busy_blocks():
    sent: list[str] = []
    async def _fake_start_run(goal: str) -> None:
        sent.append(goal)
    app = _make_app(run_active=True, loop_factory=lambda: None)
    app.start_run = _fake_start_run  # type: ignore[method-assign]
    log = TranscriptLog()
    await app._retry(log)  # type: ignore[attr-defined]
    assert "先 Esc 打断" in log.rendered_text
    assert sent == []


@pytest.mark.asyncio
async def test_retry_no_messages():
    class _EmptyStore:
        def get_messages(self, sid):
            return []
    class _StubLoop:
        store = _EmptyStore()
    app = _make_app(run_active=False, loop_factory=lambda: _StubLoop())
    log = TranscriptLog()
    await app._retry(log)  # type: ignore[attr-defined]
    assert "没有可重试" in log.rendered_text


@pytest.mark.asyncio
async def test_retry_no_get_messages_attribute():
    class _BareStore:
        pass
    class _StubLoop:
        store = _BareStore()
    app = _make_app(run_active=False, loop_factory=lambda: _StubLoop())
    log = TranscriptLog()
    await app._retry(log)  # type: ignore[attr-defined]
    assert "持久 store" in log.rendered_text


@pytest.mark.asyncio
async def test_retry_no_loop_factory():
    app = _make_app(run_active=False, loop_factory=lambda: None)
    log = TranscriptLog()
    await app._retry(log)  # type: ignore[attr-defined]
    assert "持久 store" in log.rendered_text
