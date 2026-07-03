"""Internal documentation."""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from argos.daemon.manager import RunManager
from argos.daemon.server import DaemonHTTPServer
from argos.daemon.worker import FakeLoop, RunWorker


@pytest.mark.asyncio
async def test_spawn_worker_pops_routing_table_on_terminal(tmp_path: Path):
    """Internal documentation."""
    mgr = RunManager(runs_dir=tmp_path / "runs", index_path=tmp_path / "index.json")
    srv = DaemonHTTPServer(manager=mgr, socket_path=tmp_path / "s.sock")
    rid = await mgr.create_run(goal="x", workspace=str(tmp_path))
    worker = RunWorker(run_id=rid, manager=mgr, loop_factory=lambda: FakeLoop(steps=2, delay_s=0.0))

    task = srv._spawn_worker(worker, rid, name=f"run-{rid}")
    assert rid in srv._workers

    await task
    await asyncio.sleep(0)
    assert rid not in srv._workers
