"""daemon run 完成信号缺口修复 —— SSE 终态关闭 + worker 终态广播 + 看门狗。

根因(memory 6932):daemon 完成一个 run 后,既不关闭 SSE 流、也不广播任何"终止"事件;
而 TUI 客户端(DaemonEventSource)恰恰靠"流关闭(EOF)"判定 run 结束。两端约定对不上 →
`app._run_active` guard 永不清零 → 后续输入被 t("tui.run.busy") 顶回("任务进行中")。
现象:发"你好"秒回后,report 一栏永远转圈,再发任何消息都被拒。

本文件锁死四条契约:
  B1  server 在 run 进入终态(completed/failed/cancelled)时关闭 SSE 流 → client EOF。
  B2  worker 在 run 收尾时广播一个终态 state_change → SSE 订阅者立即醒来关流(免等 keepalive)。
  B3  worker 看门狗:ARGOS_RUN_TIMEOUT_S 超时 → 硬取消卡死的 loop(真·死循环防御,opt-in)。
  B4  端到端:DaemonEventSource.stream() 随 run 完成而结束(→ bus 关 → guard 清)。
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
import pytest_asyncio

from argos.daemon.client import DaemonClient
from argos.daemon.manager import RunManager
from argos.daemon.server import DaemonHTTPServer
from argos.daemon.state_machine import TERMINAL_STATES
from argos.daemon.worker import FakeLoop, RunWorker


# ── fixtures / helpers ──────────────────────────────────────────────────

@pytest_asyncio.fixture
async def server(tmp_path: Path):
    manager = RunManager(runs_dir=tmp_path / "runs", index_path=tmp_path / "index.json")
    srv = DaemonHTTPServer(manager=manager, socket_path=tmp_path / "daemon.sock")
    await srv.start()
    try:
        yield srv, manager
    finally:
        await srv.stop()
        manager.close()


async def _create_session(socket_path: Path) -> str:
    cli = DaemonClient(socket_path, timeout=5.0)
    status, _, raw = await cli._request("POST", "/sessions")
    assert status == 201
    return json.loads(raw.decode("utf-8"))["session_id"]


async def _create_run(socket_path: Path, sid: str, goal: str = "你好") -> str:
    cli = DaemonClient(socket_path, timeout=5.0)
    status, _, raw = await cli._request(
        "POST", "/runs", session_id=sid, body={"goal": goal}
    )
    assert status == 201
    return json.loads(raw.decode("utf-8"))["run_id"]


async def _poll_done(task: asyncio.Task, timeout: float) -> bool:
    """等任务【自然】完成,绝不主动 cancel。

    关键:asyncio.wait_for 超时会 cancel 内层任务,而 DaemonEventSource.stream() 有
    `except CancelledError: return` 会把取消吞成正常结束 → wait_for 反而不抛 → 假绿灯。
    所以这里只轮询 task.done(),让"流是否随 run 完成而自己收尾"成为唯一被观测的信号。
    """
    waited = 0.0
    while not task.done() and waited < timeout:
        await asyncio.sleep(0.05)
        waited += 0.05
    return task.done()


# ── B1:server 在终态关闭 SSE 流 ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_sse_stream_closes_when_run_completes(server):
    """run → completed 后,SSE 流必须在数秒内 EOF(client 生成器结束),而非无限挂。

    这是"你好卡死"的根因回归:client 靠 EOF 判完成,server 不关 → 流永挂。
    """
    srv, mgr = server
    sid = await _create_session(srv.socket_path)
    rid = await _create_run(srv.socket_path, sid)
    mgr.mark_running(rid)

    client = DaemonClient(srv.socket_path, timeout=10.0)
    gen = client.subscribe_events(rid, sid, since=0)
    ev = await asyncio.wait_for(anext(gen), timeout=3.0)
    assert ev["kind"] == "run_meta"

    mgr.mark_completed(rid)

    async def _drain() -> None:
        async for _ in gen:
            pass

    # 不能挂:终态后流必须收尾
    await asyncio.wait_for(_drain(), timeout=5.0)


@pytest.mark.asyncio
async def test_sse_stream_closes_when_run_cancelled(server):
    """终态关闭对 cancelled 一视同仁(不只 completed)。"""
    srv, mgr = server
    sid = await _create_session(srv.socket_path)
    rid = await _create_run(srv.socket_path, sid)
    mgr.mark_running(rid)

    client = DaemonClient(srv.socket_path, timeout=10.0)
    gen = client.subscribe_events(rid, sid, since=0)
    await asyncio.wait_for(anext(gen), timeout=3.0)

    mgr.mark_cancelled(rid)

    async def _drain() -> None:
        async for _ in gen:
            pass

    await asyncio.wait_for(_drain(), timeout=5.0)


# ── B2:worker 收尾广播终态 state_change ─────────────────────────────────

@pytest.mark.asyncio
async def test_worker_fans_out_terminal_state_change_on_completion(tmp_path: Path):
    """worker 跑完一个普通对话轮后,必须向 SSE 订阅者广播一个终态 state_change。

    没有它,SSE handler 只能等 2s keepalive tick 才发现终态 → report spinner 多挂 2s。
    有它则订阅者立即醒来关流。
    """
    mgr = RunManager(runs_dir=tmp_path / "runs", index_path=tmp_path / "index.json")
    rid = await mgr.create_run(goal="你好", workspace="/tmp")
    q = mgr.subscribe(rid)
    worker = RunWorker(
        run_id=rid, manager=mgr, loop_factory=lambda: FakeLoop(steps=2, delay_s=0.0),
    )
    await worker.run()
    assert mgr.get_run(rid).state == "completed"

    events = []
    while not q.empty():
        events.append(q.get_nowait())
    assert any(
        e.get("kind") == "state_change" and e.get("to") in TERMINAL_STATES
        for e in events
    ), "worker 必须广播终态 state_change,SSE 订阅者才能立即关流"


# ── B3:worker 看门狗(opt-in 死循环防御)─────────────────────────────────

@pytest.mark.asyncio
async def test_worker_watchdog_hard_cancels_when_timeout_exceeded(
    tmp_path: Path, monkeypatch
):
    """ARGOS_RUN_TIMEOUT_S 超时 → 看门狗硬取消卡死的 loop,run 转 cancelled,不无限挂。"""
    monkeypatch.setenv("ARGOS_RUN_TIMEOUT_S", "0.3")

    class _HangLoop:
        async def run(self, goal, session_id=None, **kwargs):
            yield {"kind": "token_delta", "text": "start"}  # → running
            await asyncio.sleep(100)                          # 卡死(模拟 stream 不返)
            yield {"kind": "token_delta", "text": "never"}

    ws = tmp_path / "ws"
    ws.mkdir()
    mgr = RunManager(runs_dir=tmp_path / "runs", index_path=tmp_path / "index.json")
    rid = await mgr.create_run(goal="x", workspace=str(ws))
    worker = RunWorker(run_id=rid, manager=mgr, loop_factory=lambda: _HangLoop())
    task = asyncio.create_task(worker.run())

    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=3.0)
    assert mgr.get_run(rid).state == "cancelled"


@pytest.mark.asyncio
async def test_worker_watchdog_disabled_by_default(tmp_path: Path):
    """默认(未设 ARGOS_RUN_TIMEOUT_S)不启看门狗 —— 正常 run 不受影响,无误杀。"""
    mgr = RunManager(runs_dir=tmp_path / "runs", index_path=tmp_path / "index.json")
    rid = await mgr.create_run(goal="x", workspace="/tmp")
    worker = RunWorker(
        run_id=rid, manager=mgr, loop_factory=lambda: FakeLoop(steps=3, delay_s=0.0),
    )
    await worker.run()
    assert mgr.get_run(rid).state == "completed"


# ── B4:端到端 —— DaemonEventSource.stream() 随完成结束 ─────────────────

@pytest.mark.asyncio
async def test_daemon_event_source_stream_ends_on_completion(server):
    """TUI 客户端栈:run 完成 → DaemonEventSource.stream() 结束 → bus 关 → _run_active 清。"""
    from argos.tui.daemon_source import DaemonEventSource

    srv, mgr = server
    sid = await _create_session(srv.socket_path)
    rid = await _create_run(srv.socket_path, sid)
    mgr.mark_running(rid)

    source = DaemonEventSource(srv.socket_path, rid, sid)
    collected: list = []

    async def _consume() -> None:
        async for ev in source.stream():
            collected.append(ev)

    task = asyncio.create_task(_consume())
    await asyncio.sleep(0.5)        # 订阅建立 + run_meta 到达
    mgr.mark_completed(rid)

    # stream 必须【自己】结束(server EOF),否则 bus 不关、guard 不清、下一条输入被拒。
    # 只轮询、不 cancel —— 否则 stream() 吞掉 cancel 正常返回会假装"结束"。
    done = await _poll_done(task, timeout=6.0)
    if not done:
        task.cancel()
    assert done, "DaemonEventSource.stream() 未随 run 完成而收尾 → bus 永不关 → guard 卡死"
