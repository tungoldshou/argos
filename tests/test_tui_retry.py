"""/retry 命令端到端。

校准(对照 Task 10 实际实现):
- Transcript 类名不是 TranscriptLog
- busy 守卫字段是 _run_active(非 _busy)
- store 不在 App 字段,需通过 _loop_factory() 借 .store 属性注入
- transcript 断言用 rendered_text(私有 _lines 不可外访)
"""
import pytest

from argos_agent.tui.app import ArgosApp
from argos_agent.tui.widgets.transcript import Transcript as TranscriptLog


def _make_app(*, run_active: bool, loop_factory, session_id: str = "sess-test") -> ArgosApp:
    """工厂:跳过 __init__,装 _run_active / _loop_factory / _session_id。"""
    app = ArgosApp.__new__(ArgosApp)
    app._session_id = session_id
    app._run_active = run_active
    app._loop_factory = loop_factory
    return app


@pytest.mark.asyncio
async def test_retry_resends_last_user_message():
    """正常路径:有 user 消息 → 取最后一条 → 调 start_run 重发。"""
    class _StubStore:
        def get_messages(self, sid):
            return [
                {"role": "user", "text": "first"},
                {"role": "assistant", "text": "ok"},
                {"role": "user", "text": "second goal"},
            ]
    class _StubLoop:
        store = _StubStore()
    # stub start_run 捕获重发的 goal
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
    """busy 时 /retry 报"先 Esc 打断",不发。"""
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
    """store 有但 get_messages 返空 → 报"没有可重试的消息"。"""
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
    """store 无 get_messages 属性 → 报"当前 store 不支持"。"""
    class _BareStore:
        pass
    class _StubLoop:
        store = _BareStore()
    app = _make_app(run_active=False, loop_factory=lambda: _StubLoop())
    log = TranscriptLog()
    await app._retry(log)  # type: ignore[attr-defined]
    assert "当前 store 不支持" in log.rendered_text


@pytest.mark.asyncio
async def test_retry_no_loop_factory():
    """_loop_factory 返 None → 报"当前 store 不支持"。"""
    app = _make_app(run_active=False, loop_factory=lambda: None)
    log = TranscriptLog()
    await app._retry(log)  # type: ignore[attr-defined]
    assert "当前 store 不支持" in log.rendered_text
