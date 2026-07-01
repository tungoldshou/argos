"""Daemon 会话自愈测试(修真机 401 missing_session 不自愈 bug)。

真机现象:天气查询成功后,空闲 >30s 再敲 'hello' → 连续两条红
  'daemon create_run failed: HTTP 401 (code=missing_session): session expired or unknown'

根因:daemon 会话 30s 无心跳即被回收(sessions.py HEARTBEAT_TIMEOUT_S),
而 TUI 既不发心跳、也不在拿到 401 时重建会话,把原始协议错误直接抛给用户。

修复两道:
  A. DaemonError 结构化暴露 .status / .code —— 上层可程序化判别 missing_session(不靠解析字符串)。
  B. TUI 心跳保活 worker(_daemon_heartbeat_tick)+ create_run 透明重握手重试(_daemon_create_run)。
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from argos.daemon.client import DaemonClient, DaemonError
from argos.daemon.protocol import CODE_MISSING_SESSION


# ── A. DaemonError 结构化字段 ─────────────────────────────────────────────
def test_daemon_error_exposes_status_and_code():
    """_check 抛的 DaemonError 带 .status 与 .code(供 missing_session 自愈判别)。"""
    c = DaemonClient(Path("/tmp/_argos_fake.sock"))
    with pytest.raises(DaemonError) as ei:
        c._check(
            401,
            {"code": "missing_session", "error": "session expired or unknown"},
            (201,),
        )
    assert ei.value.status == 401
    assert ei.value.code == "missing_session"
    # 人类可读 message 仍保留(transcript 兜底显示用)
    assert "missing_session" in str(ei.value)


def test_daemon_error_plain_message_defaults_safe():
    """非 _check 路径(无 code)构造 DaemonError 不崩,字段有安全默认。"""
    e = DaemonError("empty response")
    assert e.code == ""
    assert e.status is None


# ── B. create_run 透明重握手 ──────────────────────────────────────────────
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
    """create_run 撞 missing_session → 重建 session + 重试一次 → 返新 run_id。"""
    expired = DaemonError("HTTP 401 (code=missing_session): session expired or unknown",
                          status=401, code=CODE_MISSING_SESSION)
    app, fake = _app_with_fake_client([expired, "run-2"], new_sid="sess-new")

    run_id = await app._daemon_create_run("hello", [])

    assert run_id == "run-2"
    assert app._daemon_session_id == "sess-new"      # 会话已被透明替换
    assert fake.create_session.await_count == 1       # 重握手一次
    assert fake.create_run.await_count == 2           # 失败 + 重试


@pytest.mark.asyncio
async def test_daemon_create_run_propagates_non_session_errors():
    """非 missing_session 错误(如 busy)不应触发重握手,原样上抛。"""
    busy = DaemonError("HTTP 409 (code=busy): run in flight", status=409, code="busy")
    app, fake = _app_with_fake_client([busy])

    with pytest.raises(DaemonError) as ei:
        await app._daemon_create_run("hello", [])
    assert ei.value.code == "busy"
    assert fake.create_session.await_count == 0       # 没有瞎重建会话
    assert fake.create_run.await_count == 1


@pytest.mark.asyncio
async def test_daemon_create_run_happy_path_no_rehandshake():
    """正常情况:一次成功,不重建会话。"""
    app, fake = _app_with_fake_client(["run-1"])
    run_id = await app._daemon_create_run("hello", [])
    assert run_id == "run-1"
    assert fake.create_session.await_count == 0
    assert app._daemon_session_id == "sess-old"


# ── B. 心跳保活 tick ──────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_heartbeat_tick_pings_daemon():
    """tick 给当前会话续命(调 client.heartbeat)。"""
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
    """tick 撞 missing_session(空闲太久被回收)→ 重建会话,使下一次 run 不再撞 401。"""
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
    """inline 模式(无 daemon)tick 安全空转,不调用 client。"""
    from argos.tui.app import ArgosApp

    app = ArgosApp()
    app._with_daemon = False
    app._daemon_client = None
    app._daemon_session_id = None

    # 不应抛
    await app._daemon_heartbeat_tick()
