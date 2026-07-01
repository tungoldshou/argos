"""跨 session + crash 恢复测试(spec §2.4 + §2.8)。"""
from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest

from argos.daemon.events import RunMeta
from argos.daemon.manager import RunManager
from argos.daemon.state_machine import transition
from argos.daemon.worker import FakeLoop, RunWorker


@pytest.mark.asyncio
async def test_recover_marks_running_as_suspended(tmp_path: Path):
    """daemon 启动时扫:index 标 running 但实际已 SIGKILL → 改 suspended。"""
    runs_dir = tmp_path / "runs"
    index_path = tmp_path / "index.json"
    mgr1 = RunManager(runs_dir=runs_dir, index_path=index_path)
    rid = await mgr1.create_run(goal="x", workspace="/tmp")
    mgr1.mark_running(rid)
    # "kill -9" → 不写 completed,index 留 running
    mgr2 = RunManager(runs_dir=runs_dir, index_path=index_path)
    recovered = mgr2.recover()
    assert recovered[rid] == "suspended"
    assert mgr2.get_run(rid).state == "suspended"


@pytest.mark.asyncio
async def test_recover_preserves_completed(tmp_path: Path):
    """已完成 run 不被 recover 动(终态写保护)。"""
    mgr1 = RunManager(runs_dir=tmp_path / "runs", index_path=tmp_path / "index.json")
    rid = await mgr1.create_run(goal="x", workspace="/tmp")
    mgr1.mark_running(rid)
    mgr1.mark_completed(rid)
    mgr2 = RunManager(runs_dir=tmp_path / "runs", index_path=tmp_path / "index.json")
    mgr2.recover()
    assert mgr2.get_run(rid).state == "completed"


@pytest.mark.asyncio
async def test_recover_preserves_paused(tmp_path: Path):
    """paused run 不被 recover 动(用户主动,可继续 resume)。"""
    mgr1 = RunManager(runs_dir=tmp_path / "runs", index_path=tmp_path / "index.json")
    rid = await mgr1.create_run(goal="x", workspace="/tmp")
    mgr1.mark_running(rid)
    mgr1.mark_paused(rid, last_step=0, msg_count=0, last_event_seq=0)
    mgr2 = RunManager(runs_dir=tmp_path / "runs", index_path=tmp_path / "index.json")
    mgr2.recover()
    assert mgr2.get_run(rid).state == "paused"


@pytest.mark.asyncio
async def test_recover_marks_pending_as_cancelled(tmp_path: Path):
    """pending 中断(SIGKILL 前还没 promote running)→ cancelled。"""
    mgr1 = RunManager(runs_dir=tmp_path / "runs", index_path=tmp_path / "index.json")
    rid = await mgr1.create_run(goal="x", workspace="/tmp")
    # 不 mark_running → 留 pending
    mgr2 = RunManager(runs_dir=tmp_path / "runs", index_path=tmp_path / "index.json")
    recovered = mgr2.recover()
    assert recovered[rid] == "cancelled"
    assert mgr2.get_run(rid).state == "cancelled"


@pytest.mark.asyncio
async def test_persistence_across_workers(tmp_path: Path):
    """worker 跑 5 步 + 完成 → 新 worker 拿 completed 状态(JSONL 写盘持久)。"""
    mgr1 = RunManager(runs_dir=tmp_path / "runs", index_path=tmp_path / "index.json")
    rid = await mgr1.create_run(goal="x", workspace="/tmp")
    w1 = RunWorker(run_id=rid, manager=mgr1,
                   loop_factory=lambda: FakeLoop(steps=5, delay_s=0.0))
    await w1.run()
    # 新 mgr 读盘
    mgr2 = RunManager(runs_dir=tmp_path / "runs", index_path=tmp_path / "index.json")
    entry = mgr2.get_run(rid)
    assert entry.state == "completed"
    assert mgr2.events_count(rid) >= 16


@pytest.mark.asyncio
async def test_corrupt_index_rebuilds_from_jsonl(tmp_path: Path):
    """index.json 损坏 → load 空 dict;recover 时不崩。"""
    index_path = tmp_path / "index.json"
    index_path.write_text("{not valid json", encoding="utf-8")
    mgr = RunManager(runs_dir=tmp_path / "runs", index_path=index_path)
    assert mgr.index.get("anything") is None
    mgr.recover()


@pytest.mark.asyncio
async def test_resume_from_paused(tmp_path: Path):
    """paused → resume 续(同 process),不重建 loop。"""
    mgr = RunManager(runs_dir=tmp_path / "runs", index_path=tmp_path / "index.json")
    rid = await mgr.create_run(goal="x", workspace="/tmp")
    mgr.mark_running(rid)
    mgr.mark_paused(rid, last_step=3, msg_count=5, last_event_seq=10)
    # resume
    assert await mgr.request_resume(rid) is True
    # state 仍 paused(worker 没真接到 resume 事件;但 request_resume 已 set event)
    # 实际由 worker 协程 mark_resumed
    assert mgr.get_run(rid).state == "paused"


@pytest.mark.asyncio
async def test_resume_from_suspended(tmp_path: Path):
    """suspended → resume(请求入队;真 resume 在 worker 接单时)。"""
    mgr = RunManager(runs_dir=tmp_path / "runs", index_path=tmp_path / "index.json")
    rid = await mgr.create_run(goal="x", workspace="/tmp")
    mgr.mark_running(rid)
    mgr.mark_suspended(rid, last_step=3, msg_count=5, last_event_seq=10)
    assert await mgr.request_resume(rid) is True
    assert mgr.get_run(rid).state == "suspended"


@pytest.mark.asyncio
async def test_index_state_machine_full_transitions(tmp_path: Path):
    """跑遍所有合法转换。"""
    mgr = RunManager(runs_dir=tmp_path / "runs", index_path=tmp_path / "index.json")
    from argos.daemon.state_machine import ALLOWED, TERMINAL_STATES
    rid = await mgr.create_run(goal="x", workspace="/tmp")
    # 跑遍所有 allowed transitions(从非终态)
    for frm, allowed in ALLOWED.items():
        if frm in TERMINAL_STATES:
            continue
        for to in allowed:
            # 重置
            mgr.index.upsert(rid, state=frm)
            # transition from=frm, target=to 应成功
            try:
                from argos.daemon.state_machine import transition
                transition(current=frm, target=to, index=mgr.index, run_id=rid,
                           store=mgr.store, reason="test")
            except Exception as e:  # noqa: BLE001
                pytest.fail(f"legal transition {frm}->{to} failed: {e}")


def test_recover_skips_corrupt_and_virtual_streams(tmp_path: Path) -> None:
    """损坏文件 / 虚拟事件总线(_conductor)不该让 daemon 启动崩溃。

    regression: ConductorSupervisor 直写 proactive_suggestion 到 _conductor.jsonl
    (无 run_meta 头)→ recover() 里 last_state() 抛 CorruptionError 冒到 asyncio.run(),
    argosd 绑 socket 前就死 → auto-spawn 每次退回 inline(后台/跨 session 永久失效)。
    """
    import json
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir(parents=True)
    # 虚拟事件总线:首行非 run_meta(直写事件,无头)→ 靠 "_" 前缀跳过
    (runs_dir / "_conductor.jsonl").write_text(
        json.dumps({"kind": "proactive_suggestion", "goal": "x"}) + "\n",
        encoding="utf-8",
    )
    # 另一个真损坏的 run 文件(非 _ 前缀)→ 靠 CorruptionError 兜底跳过
    (runs_dir / "deadbeef1234.jsonl").write_text(
        json.dumps({"kind": "token_delta", "text": "x"}) + "\n",
        encoding="utf-8",
    )
    mgr = RunManager(runs_dir=runs_dir, index_path=tmp_path / "index.json")
    # 不该抛;两个文件都被跳过,recover() 返回空
    assert mgr.recover() == {}
