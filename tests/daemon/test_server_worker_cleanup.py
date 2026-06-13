"""#12 server 路由表生命周期:worker 终态自动从 _workers 摘除(防只增不减泄漏)。"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from argos.daemon.manager import RunManager
from argos.daemon.server import DaemonHTTPServer
from argos.daemon.worker import FakeLoop, RunWorker


@pytest.mark.asyncio
async def test_spawn_worker_pops_routing_table_on_terminal(tmp_path: Path):
    """#12:_workers 注册后,run 终态(完成/失败/取消)必须自动摘除。否则常驻 daemon 的路由表
    只增不减,每 run 泄漏 RunWorker(连带其持有的 gate / snapshot / attachments)→ 内存缓慢膨胀。"""
    mgr = RunManager(runs_dir=tmp_path / "runs", index_path=tmp_path / "index.json")
    srv = DaemonHTTPServer(manager=mgr, socket_path=tmp_path / "s.sock")
    rid = await mgr.create_run(goal="x", workspace=str(tmp_path))
    worker = RunWorker(run_id=rid, manager=mgr, loop_factory=lambda: FakeLoop(steps=2, delay_s=0.0))

    task = srv._spawn_worker(worker, rid, name=f"run-{rid}")
    assert rid in srv._workers          # 启动后在路由表

    await task
    await asyncio.sleep(0)              # 让 add_done_callback 跑一拍
    assert rid not in srv._workers     # 终态自动摘除,无泄漏
