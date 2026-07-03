from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest

from argos.daemon.events import RunMeta
from argos.daemon.manager import RunManager
from argos.daemon.worker import FakeLoop, RunWorker


def _meta(run_id: str = "abc123def456") -> RunMeta:
    return RunMeta(
        run_id=run_id, goal="x", workspace="/tmp", model="m",
        created_at=time.time(), approval_level="confirm",
    )


@pytest.mark.asyncio
async def test_worker_runs_to_completion(tmp_path: Path):
    mgr = RunManager(runs_dir=tmp_path / "runs", index_path=tmp_path / "index.json")
    rid = await mgr.create_run(goal="x", workspace="/tmp")
    worker = RunWorker(
        run_id=rid, manager=mgr, loop_factory=lambda: FakeLoop(steps=5, delay_s=0.0),
    )
    await worker.run()
    entry = mgr.get_run(rid)
    assert entry.state == "completed"
    events = list(mgr.store.replay(rid))
    assert any(e.get("kind") == "state_change" and e.get("to") == "completed" for e in events)


@pytest.mark.asyncio
async def test_worker_pause_at_step_boundary(tmp_path: Path):
    mgr = RunManager(runs_dir=tmp_path / "runs", index_path=tmp_path / "index.json")
    rid = await mgr.create_run(goal="x", workspace="/tmp")
    worker = RunWorker(
        run_id=rid, manager=mgr,
        loop_factory=lambda: FakeLoop(steps=50, delay_s=0.02),
    )

    t = asyncio.create_task(worker.run())
    for _ in range(50):
        if mgr.get_run(rid).state == "running":
            break
        await asyncio.sleep(0.005)
    assert mgr.get_run(rid).state == "running"
    # pause
    assert await mgr.request_pause(rid) is True
    for _ in range(50):
        if mgr.get_run(rid).state == "paused":
            break
        await asyncio.sleep(0.01)
    assert mgr.get_run(rid).state == "paused"
    # resume
    assert await mgr.request_resume(rid) is True
    await mgr.request_cancel(rid)
    try:
        await asyncio.wait_for(t, timeout=2.0)
    except asyncio.TimeoutError:
        t.cancel()
        try:
            await t
        except (asyncio.CancelledError, Exception):
            pass
    events = list(mgr.store.replay(rid))
    assert any(e.get("kind") == "run_checkpoint" for e in events)


@pytest.mark.asyncio
async def test_worker_suspend_at_step_boundary(tmp_path: Path):
    mgr = RunManager(runs_dir=tmp_path / "runs", index_path=tmp_path / "index.json")
    rid = await mgr.create_run(goal="x", workspace="/tmp")
    worker = RunWorker(
        run_id=rid, manager=mgr,
        loop_factory=lambda: FakeLoop(steps=50, delay_s=0.02),
    )
    t = asyncio.create_task(worker.run())
    for _ in range(50):
        if mgr.get_run(rid).state == "running":
            break
        await asyncio.sleep(0.005)
    assert mgr.get_run(rid).state == "running"
    assert await mgr.request_suspend(rid) is True
    await asyncio.wait_for(t, timeout=2.0)
    assert mgr.get_run(rid).state == "suspended"
    events = list(mgr.store.replay(rid))
    assert any(e.get("kind") == "run_checkpoint" for e in events)
    assert any(e.get("kind") == "state_change" and e.get("to") == "suspended"
               for e in events)
    assert await mgr.request_suspend(rid) is False


@pytest.mark.asyncio
async def test_worker_cancel_immediately(tmp_path: Path):
    mgr = RunManager(runs_dir=tmp_path / "runs", index_path=tmp_path / "index.json")
    rid = await mgr.create_run(goal="x", workspace="/tmp")
    worker = RunWorker(
        run_id=rid, manager=mgr,
        loop_factory=lambda: FakeLoop(steps=100, delay_s=0.05),
    )

    t = asyncio.create_task(worker.run())
    for _ in range(20):
        if mgr.get_run(rid).state == "running":
            break
        await asyncio.sleep(0.01)
    # cancel
    assert await mgr.request_cancel(rid) is True
    try:
        await asyncio.wait_for(t, timeout=2.0)
    except asyncio.TimeoutError:
        t.cancel()
        try:
            await t
        except (asyncio.CancelledError, Exception):
            pass
    assert mgr.get_run(rid).state == "cancelled"


@pytest.mark.asyncio
async def test_worker_sse_fanout(tmp_path: Path):
    mgr = RunManager(runs_dir=tmp_path / "runs", index_path=tmp_path / "index.json")
    rid = await mgr.create_run(goal="x", workspace="/tmp")
    q1 = mgr.subscribe(rid)
    q2 = mgr.subscribe(rid)
    await mgr.fanout(rid, {"kind": "test", "ts": 1.0})
    e1 = q1.get_nowait()
    e2 = q2.get_nowait()
    assert e1["kind"] == "test"
    assert e2["kind"] == "test"


@pytest.mark.asyncio
async def test_worker_sse_slow_subscriber_drops(tmp_path: Path):
    mgr = RunManager(runs_dir=tmp_path / "runs", index_path=tmp_path / "index.json")
    rid = await mgr.create_run(goal="x", workspace="/tmp")
    q = mgr.subscribe(rid, maxsize=2)
    for i in range(2):
        await mgr.fanout(rid, {"kind": "t", "i": i})
    await mgr.fanout(rid, {"kind": "t", "i": 99})
    assert q.qsize() == 2


@pytest.mark.asyncio
async def test_worker_exception_marks_failed(tmp_path: Path):
    mgr = RunManager(runs_dir=tmp_path / "runs", index_path=tmp_path / "index.json")
    rid = await mgr.create_run(goal="x", workspace="/tmp")

    class BoomLoop:
        async def run(self, goal, session_id):
            yield {"kind": "token_delta", "text": "ok"}
            raise RuntimeError("boom")

    worker = RunWorker(run_id=rid, manager=mgr, loop_factory=BoomLoop)
    await worker.run()
    assert mgr.get_run(rid).state == "failed"
    events = list(mgr.store.replay(rid))
    assert any(e.get("kind") == "run_failure" for e in events)


@pytest.mark.asyncio
async def test_worker_suspended_keeps_run(tmp_path: Path):
    mgr = RunManager(runs_dir=tmp_path / "runs", index_path=tmp_path / "index.json")
    rid = await mgr.create_run(goal="x", workspace="/tmp")
    mgr.mark_running(rid)
    mgr.mark_suspended(rid, last_step=3, msg_count=10, last_event_seq=15)
    assert mgr.get_run(rid).state == "suspended"
    events = list(mgr.store.replay(rid))
    assert any(e.get("kind") == "run_checkpoint" for e in events)
    assert any(e.get("kind") == "state_change" and e.get("to") == "suspended" for e in events)


@pytest.mark.asyncio
async def test_worker_event_seq_increments(tmp_path: Path):
    mgr = RunManager(runs_dir=tmp_path / "runs", index_path=tmp_path / "index.json")
    rid = await mgr.create_run(goal="x", workspace="/tmp")
    worker = RunWorker(
        run_id=rid, manager=mgr, loop_factory=lambda: FakeLoop(steps=3, delay_s=0.0),
    )
    await worker.run()
    seqs = [e.get("_seq") for e in mgr.store.replay(rid) if e.get("_seq") is not None]
    assert len(seqs) >= 9
    assert seqs == sorted(seqs)
    assert len(set(seqs)) == len(seqs)


@pytest.mark.asyncio
async def test_worker_drives_loop_in_project_mode(tmp_path: Path):
    from argos import runtime

    captured: dict = {}

    class _SpyLoop:
        async def run(self, goal, session_id=None, **kwargs):
            ctx = runtime.current()
            captured["project_mode"] = ctx.project_mode
            captured["verify_eq_ws"] = ctx.verify_dir == ctx.workspace
            for _ in ():
                yield {}

    ws = tmp_path / "ws"
    ws.mkdir()
    mgr = RunManager(runs_dir=tmp_path / "runs", index_path=tmp_path / "index.json")
    rid = await mgr.create_run(goal="x", workspace=str(ws))
    worker = RunWorker(run_id=rid, manager=mgr, loop_factory=lambda: _SpyLoop())
    await worker.run()
    assert captured.get("project_mode") is True
    assert captured.get("verify_eq_ws") is True


@pytest.mark.asyncio
async def test_worker_uses_run_conversation_session(tmp_path: Path):
    captured: dict = {}

    class _SpyLoop:
        async def run(self, goal, session_id=None, **kwargs):
            captured["goal"] = goal
            captured["session_id"] = session_id
            for _ in ():
                yield {}

    ws = tmp_path / "ws"
    ws.mkdir()
    mgr = RunManager(runs_dir=tmp_path / "runs", index_path=tmp_path / "index.json")
    rid = await mgr.create_run(
        goal="成都", workspace=str(ws), session_id="tui-session-1",
    )
    worker = RunWorker(run_id=rid, manager=mgr, loop_factory=lambda: _SpyLoop())
    await worker.run()
    assert captured == {"goal": "成都", "session_id": "tui-session-1"}


@pytest.mark.asyncio
async def test_worker_hard_cancel_interrupts_blocked_loop(tmp_path: Path):
    class _BlockingLoop:
        async def run(self, goal, session_id=None, **kwargs):
            yield {"kind": "token_delta", "text": "start"}
            await asyncio.sleep(100)
            yield {"kind": "token_delta", "text": "never"}

    ws = tmp_path / "ws"
    ws.mkdir()
    mgr = RunManager(runs_dir=tmp_path / "runs", index_path=tmp_path / "index.json")
    rid = await mgr.create_run(goal="x", workspace=str(ws))
    worker = RunWorker(run_id=rid, manager=mgr, loop_factory=lambda: _BlockingLoop())
    task = asyncio.create_task(worker.run())
    for _ in range(200):
        if mgr.get_run(rid).state == "running":
            break
        await asyncio.sleep(0.01)
    assert mgr.get_run(rid).state == "running"
    await mgr.request_cancel(rid)
    assert worker.request_hard_cancel() is True
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=2.0)
    assert mgr.get_run(rid).state == "cancelled"
