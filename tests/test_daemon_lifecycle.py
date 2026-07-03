"""Internal documentation."""
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
    """Internal documentation."""
    runs_dir = tmp_path / "runs"
    index_path = tmp_path / "index.json"
    mgr1 = RunManager(runs_dir=runs_dir, index_path=index_path)
    rid = await mgr1.create_run(goal="x", workspace="/tmp")
    mgr1.mark_running(rid)
    mgr2 = RunManager(runs_dir=runs_dir, index_path=index_path)
    recovered = mgr2.recover()
    assert recovered[rid] == "suspended"
    assert mgr2.get_run(rid).state == "suspended"


@pytest.mark.asyncio
async def test_recover_preserves_completed(tmp_path: Path):
    """Internal documentation."""
    mgr1 = RunManager(runs_dir=tmp_path / "runs", index_path=tmp_path / "index.json")
    rid = await mgr1.create_run(goal="x", workspace="/tmp")
    mgr1.mark_running(rid)
    mgr1.mark_completed(rid)
    mgr2 = RunManager(runs_dir=tmp_path / "runs", index_path=tmp_path / "index.json")
    mgr2.recover()
    assert mgr2.get_run(rid).state == "completed"


@pytest.mark.asyncio
async def test_recover_preserves_paused(tmp_path: Path):
    """Internal documentation."""
    mgr1 = RunManager(runs_dir=tmp_path / "runs", index_path=tmp_path / "index.json")
    rid = await mgr1.create_run(goal="x", workspace="/tmp")
    mgr1.mark_running(rid)
    mgr1.mark_paused(rid, last_step=0, msg_count=0, last_event_seq=0)
    mgr2 = RunManager(runs_dir=tmp_path / "runs", index_path=tmp_path / "index.json")
    mgr2.recover()
    assert mgr2.get_run(rid).state == "paused"


@pytest.mark.asyncio
async def test_recover_marks_pending_as_cancelled(tmp_path: Path):
    """Internal documentation."""
    mgr1 = RunManager(runs_dir=tmp_path / "runs", index_path=tmp_path / "index.json")
    rid = await mgr1.create_run(goal="x", workspace="/tmp")
    mgr2 = RunManager(runs_dir=tmp_path / "runs", index_path=tmp_path / "index.json")
    recovered = mgr2.recover()
    assert recovered[rid] == "cancelled"
    assert mgr2.get_run(rid).state == "cancelled"


@pytest.mark.asyncio
async def test_persistence_across_workers(tmp_path: Path):
    """Internal documentation."""
    mgr1 = RunManager(runs_dir=tmp_path / "runs", index_path=tmp_path / "index.json")
    rid = await mgr1.create_run(goal="x", workspace="/tmp")
    w1 = RunWorker(run_id=rid, manager=mgr1,
                   loop_factory=lambda: FakeLoop(steps=5, delay_s=0.0))
    await w1.run()
    mgr2 = RunManager(runs_dir=tmp_path / "runs", index_path=tmp_path / "index.json")
    entry = mgr2.get_run(rid)
    assert entry.state == "completed"
    assert mgr2.events_count(rid) >= 16


@pytest.mark.asyncio
async def test_corrupt_index_rebuilds_from_jsonl(tmp_path: Path):
    """Internal documentation."""
    index_path = tmp_path / "index.json"
    index_path.write_text("{not valid json", encoding="utf-8")
    mgr = RunManager(runs_dir=tmp_path / "runs", index_path=index_path)
    assert mgr.index.get("anything") is None
    mgr.recover()


@pytest.mark.asyncio
async def test_resume_from_paused(tmp_path: Path):
    """Internal documentation."""
    mgr = RunManager(runs_dir=tmp_path / "runs", index_path=tmp_path / "index.json")
    rid = await mgr.create_run(goal="x", workspace="/tmp")
    mgr.mark_running(rid)
    mgr.mark_paused(rid, last_step=3, msg_count=5, last_event_seq=10)
    # resume
    assert await mgr.request_resume(rid) is True
    assert mgr.get_run(rid).state == "paused"


@pytest.mark.asyncio
async def test_resume_from_suspended(tmp_path: Path):
    """Internal documentation."""
    mgr = RunManager(runs_dir=tmp_path / "runs", index_path=tmp_path / "index.json")
    rid = await mgr.create_run(goal="x", workspace="/tmp")
    mgr.mark_running(rid)
    mgr.mark_suspended(rid, last_step=3, msg_count=5, last_event_seq=10)
    assert await mgr.request_resume(rid) is True
    assert mgr.get_run(rid).state == "suspended"


@pytest.mark.asyncio
async def test_index_state_machine_full_transitions(tmp_path: Path):
    """Internal documentation."""
    mgr = RunManager(runs_dir=tmp_path / "runs", index_path=tmp_path / "index.json")
    from argos.daemon.state_machine import ALLOWED, TERMINAL_STATES
    rid = await mgr.create_run(goal="x", workspace="/tmp")
    for frm, allowed in ALLOWED.items():
        if frm in TERMINAL_STATES:
            continue
        for to in allowed:
            mgr.index.upsert(rid, state=frm)
            try:
                from argos.daemon.state_machine import transition
                transition(current=frm, target=to, index=mgr.index, run_id=rid,
                           store=mgr.store, reason="test")
            except Exception as e:  # noqa: BLE001
                pytest.fail(f"legal transition {frm}->{to} failed: {e}")


def test_recover_skips_corrupt_and_virtual_streams(tmp_path: Path) -> None:
    """Internal documentation."""
    import json
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir(parents=True)
    (runs_dir / "_conductor.jsonl").write_text(
        json.dumps({"kind": "proactive_suggestion", "goal": "x"}) + "\n",
        encoding="utf-8",
    )
    (runs_dir / "deadbeef1234.jsonl").write_text(
        json.dumps({"kind": "token_delta", "text": "x"}) + "\n",
        encoding="utf-8",
    )
    mgr = RunManager(runs_dir=runs_dir, index_path=tmp_path / "index.json")
    assert mgr.recover() == {}
