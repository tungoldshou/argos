"""RunWorker 集成测试(spec §2.11):fake loop 跑 N 步 → 触发 pause / cancel。"""
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
    """fake loop yield 5 步,worker → state_change(running → completed)。"""
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
    """POST /pause 在 step 2 → worker 在 step 2 边界转 paused,checkpoint 落 JSONL。"""
    mgr = RunManager(runs_dir=tmp_path / "runs", index_path=tmp_path / "index.json")
    rid = await mgr.create_run(goal="x", workspace="/tmp")
    # 用大 delay 保证 pause 能插上
    worker = RunWorker(
        run_id=rid, manager=mgr,
        loop_factory=lambda: FakeLoop(steps=50, delay_s=0.02),
    )

    t = asyncio.create_task(worker.run())
    # 等到 running 状态
    for _ in range(50):
        if mgr.get_run(rid).state == "running":
            break
        await asyncio.sleep(0.005)
    assert mgr.get_run(rid).state == "running"
    # pause
    assert await mgr.request_pause(rid) is True
    # 等到 paused
    for _ in range(50):
        if mgr.get_run(rid).state == "paused":
            break
        await asyncio.sleep(0.01)
    assert mgr.get_run(rid).state == "paused"
    # resume
    assert await mgr.request_resume(rid) is True
    # cancel + 等 worker 收尾
    await mgr.request_cancel(rid)
    try:
        await asyncio.wait_for(t, timeout=2.0)
    except asyncio.TimeoutError:
        t.cancel()
        try:
            await t
        except (asyncio.CancelledError, Exception):
            pass
    # checkpoint 落 JSONL
    events = list(mgr.store.replay(rid))
    assert any(e.get("kind") == "run_checkpoint" for e in events)


@pytest.mark.asyncio
async def test_worker_cancel_immediately(tmp_path: Path):
    """POST /cancel → worker 协程 mark_cancelled。"""
    mgr = RunManager(runs_dir=tmp_path / "runs", index_path=tmp_path / "index.json")
    rid = await mgr.create_run(goal="x", workspace="/tmp")
    worker = RunWorker(
        run_id=rid, manager=mgr,
        loop_factory=lambda: FakeLoop(steps=100, delay_s=0.05),
    )

    t = asyncio.create_task(worker.run())
    # 等 running
    for _ in range(20):
        if mgr.get_run(rid).state == "running":
            break
        await asyncio.sleep(0.01)
    # cancel
    assert await mgr.request_cancel(rid) is True
    # 等 worker 收尾
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
    """2 个 subscriber 收到同事件。"""
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
    """慢 subscriber 队列满 → 丢事件 + 走 log 警告。"""
    mgr = RunManager(runs_dir=tmp_path / "runs", index_path=tmp_path / "index.json")
    rid = await mgr.create_run(goal="x", workspace="/tmp")
    q = mgr.subscribe(rid, maxsize=2)
    for i in range(2):
        await mgr.fanout(rid, {"kind": "t", "i": i})
    await mgr.fanout(rid, {"kind": "t", "i": 99})
    assert q.qsize() == 2


@pytest.mark.asyncio
async def test_worker_exception_marks_failed(tmp_path: Path):
    """loop 抛异常 → state_change(failed) + run_failure 行。"""
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
    """Ctrl+B 后台化 → state_change(running → suspended) + checkpoint 落。"""
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
    """worker 跑 → event_seq 单调递增。"""
    mgr = RunManager(runs_dir=tmp_path / "runs", index_path=tmp_path / "index.json")
    rid = await mgr.create_run(goal="x", workspace="/tmp")
    worker = RunWorker(
        run_id=rid, manager=mgr, loop_factory=lambda: FakeLoop(steps=3, delay_s=0.0),
    )
    await worker.run()
    seqs = [e.get("_seq") for e in mgr.store.replay(rid) if e.get("_seq") is not None]
    assert len(seqs) >= 9   # 3 步 × 3 events
    assert seqs == sorted(seqs)
    assert len(set(seqs)) == len(seqs)


@pytest.mark.asyncio
async def test_worker_drives_loop_in_project_mode(tmp_path: Path):
    """P0 防假绿:daemon worker 的 verify_dir==workspace(测试与解同目录),这是 project_mode 的
    定义场景——也是唯一让 guard_project_tests/detect_tampering 通电的开关。worker 过去以
    project_mode=False 驱动 loop → 篡改检测整条死掉:agent 在 workspace 改自己的测试,verify 跑
    被改后的测试拿假绿且不可见。worker 必须以 project_mode=True 驱动 loop。"""
    from argos import runtime

    captured: dict = {}

    class _SpyLoop:
        async def run(self, goal, session_id=None, **kwargs):
            ctx = runtime.current()
            captured["project_mode"] = ctx.project_mode
            captured["verify_eq_ws"] = ctx.verify_dir == ctx.workspace
            for _ in ():        # 空 async generator
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
async def test_worker_hard_cancel_interrupts_blocked_loop(tmp_path: Path):
    """P2:manager.request_cancel 只 set flag,worker 在事件边界轮询 → 卡在 stream(loop 不 yield)
    时收不到,跑到底(用户取消后可继续 ~5min)。worker.request_hard_cancel() 直接 cancel 包装本
    协程的 task,在 await 点抛 CancelledError 中断,worker 标 cancelled。"""
    class _BlockingLoop:
        async def run(self, goal, session_id=None, **kwargs):
            yield {"kind": "token_delta", "text": "start"}   # 触发 running
            await asyncio.sleep(100)                          # 卡住(模拟 stream 不返)
            yield {"kind": "token_delta", "text": "never"}

    ws = tmp_path / "ws"
    ws.mkdir()
    mgr = RunManager(runs_dir=tmp_path / "runs", index_path=tmp_path / "index.json")
    rid = await mgr.create_run(goal="x", workspace=str(ws))
    worker = RunWorker(run_id=rid, manager=mgr, loop_factory=lambda: _BlockingLoop())
    task = asyncio.create_task(worker.run())
    for _ in range(200):                                       # 等进入 running 且卡住
        if mgr.get_run(rid).state == "running":
            break
        await asyncio.sleep(0.01)
    assert mgr.get_run(rid).state == "running"
    await mgr.request_cancel(rid)                              # 老机制:set flag,不中断 sleep
    assert worker.request_hard_cancel() is True               # 新机制:硬中断
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=2.0)             # 2s 内结束 = 真被中断
    assert mgr.get_run(rid).state == "cancelled"
