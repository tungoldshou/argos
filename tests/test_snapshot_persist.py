"""SNAPSHOT_ROOT 持久化 + recover 剪枝测试。

验证:
  (a) SNAPSHOT_ROOT 解析在 argos home(~/.argos/snapshots/)下,不在系统 tmp
  (b) 快照写入后,重新解析 SNAPSHOT_ROOT 仍指向同一路径(模拟重启)
  (c) recover() 剪枝终态 run(completed/failed/cancelled)的快照,保留 suspended
"""
from __future__ import annotations

import os
import tarfile
from pathlib import Path

import pytest

import argos.core.snapshot as _snap_mod
from argos.core.snapshot import RunSnapshot, _snapshot_root
from argos.daemon.manager import RunManager


# ── (a) SNAPSHOT_ROOT 在 argos home 下,不在 tempfile.gettempdir() ──────────

def test_snapshot_root_under_argos_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """SNAPSHOT_ROOT 使用 ARGOS_CONFIG_DIR(或 ~/.argos),不是 argos-snapshots 固定路径。"""
    fake_home = tmp_path / "argos_home"
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(fake_home))

    root = _snapshot_root()
    # 必须解析到 fake_home/snapshots 下,不是旧的 tempdir/argos-snapshots
    assert root == fake_home / "snapshots"
    assert "argos-snapshots" not in str(root)  # 旧 tempdir 路径消失


# ── (b) 快照写入后重新解析 SNAPSHOT_ROOT 仍可读(模拟跨重启) ───────────────

def test_snapshot_survives_reboot_simulation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """快照写入到 persistent root 后,即使 SNAPSHOT_ROOT 常量重新解析也指同一位置。"""
    fake_home = tmp_path / "persistent_argos"
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(fake_home))

    root = _snapshot_root()
    root.mkdir(parents=True, exist_ok=True)
    tar_path = root / "test-session-001.tar"

    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "hello.py").write_text("print('hi')")

    snap = RunSnapshot.take(ws, tar_path)
    assert snap.tar_path.exists()

    # 模拟"重启":重新调用 _snapshot_root() — 应解析到同一持久路径
    root2 = _snapshot_root()
    assert root2 == root
    assert (root2 / "test-session-001.tar").exists()

    # 可读:restore 成功
    ws2 = tmp_path / "ws2"
    ws2.mkdir()
    result = snap.restore(ws2)
    assert "hello.py" in result.restored


# ── (c) recover() 剪枝终态快照,保留 suspended ──────────────────────────────

def _make_manager(tmp_path: Path) -> RunManager:
    return RunManager(
        runs_dir=tmp_path / "runs",
        index_path=tmp_path / "index.json",
    )


def _place_snapshot(snap_root: Path, run_id: str, ws: Path) -> Path:
    """在 snap_root 放一个 run-{run_id}.tar 快照文件。"""
    snap_root.mkdir(parents=True, exist_ok=True)
    p = snap_root / f"run-{run_id}.tar"
    with tarfile.open(p, "w"):
        pass  # 空 tar 足以测试剪枝逻辑
    return p


@pytest.mark.asyncio
async def test_recover_prunes_terminal_snapshots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """completed/failed/cancelled run 的快照在 recover() 后被删除。"""
    fake_home = tmp_path / "argos_home"
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(fake_home))
    # 重新计算 SNAPSHOT_ROOT 常量,供 manager.recover 内部使用
    monkeypatch.setattr(_snap_mod, "SNAPSHOT_ROOT", _snapshot_root())

    snap_root = _snapshot_root()
    ws = tmp_path / "ws"
    ws.mkdir()

    mgr = _make_manager(tmp_path)

    # completed run
    rid_completed = await mgr.create_run(goal="x", workspace=str(ws))
    mgr.mark_running(rid_completed)
    mgr.mark_completed(rid_completed)
    snap_completed = _place_snapshot(snap_root, rid_completed, ws)

    # cancelled run — 手动转态(直接用 transition 跳过 pending→running 路径)
    from argos.daemon.state_machine import transition as _trans
    rid_cancelled = await mgr.create_run(goal="y", workspace=str(ws))
    mgr.mark_running(rid_cancelled)
    _trans(
        current=None, target="cancelled",
        index=mgr.index, run_id=rid_cancelled,
        store=mgr.store, reason="test_cancel",
    )
    snap_cancelled = _place_snapshot(snap_root, rid_cancelled, ws)

    # failed run — 通过 mark_failed
    rid_failed = await mgr.create_run(goal="z", workspace=str(ws))
    mgr.mark_running(rid_failed)
    mgr.mark_failed(rid_failed, error="test", error_type="TestError", traceback="", step=0)
    snap_failed = _place_snapshot(snap_root, rid_failed, ws)

    mgr2 = _make_manager(tmp_path)
    mgr2.recover()

    # 三个终态快照全被剪枝
    assert not snap_completed.exists(), "completed 快照应被剪枝"
    assert not snap_cancelled.exists(), "cancelled 快照应被剪枝"
    assert not snap_failed.exists(), "failed 快照应被剪枝"


@pytest.mark.asyncio
async def test_recover_keeps_suspended_snapshot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """suspended run(SIGKILL 中断,需 /resume)的快照在 recover() 后保留。"""
    fake_home = tmp_path / "argos_home"
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(fake_home))
    monkeypatch.setattr(_snap_mod, "SNAPSHOT_ROOT", _snapshot_root())

    snap_root = _snapshot_root()
    ws = tmp_path / "ws"
    ws.mkdir()

    mgr1 = _make_manager(tmp_path)
    rid = await mgr1.create_run(goal="x", workspace=str(ws))
    mgr1.mark_running(rid)
    # 不写 completed → 模拟 SIGKILL;index 留 running
    snap_path = _place_snapshot(snap_root, rid, ws)

    mgr2 = _make_manager(tmp_path)
    recovered = mgr2.recover()
    assert recovered[rid] == "suspended"
    # 快照未被剪枝(resume/undo 需要它)
    assert snap_path.exists(), "suspended run 快照不应被剪枝"
