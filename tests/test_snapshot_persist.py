"""Internal documentation."""
from __future__ import annotations

import os
import tarfile
from pathlib import Path

import pytest

import argos.core.snapshot as _snap_mod
from argos.core.snapshot import RunSnapshot, _snapshot_root
from argos.daemon.manager import RunManager



def test_snapshot_root_under_argos_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Internal documentation."""
    fake_home = tmp_path / "argos_home"
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(fake_home))

    root = _snapshot_root()
    assert root == fake_home / "snapshots"
    assert "argos-snapshots" not in str(root)


def test_snapshot_root_honors_env_local_config_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """SNAPSHOT_ROOT should use the same config dir source as model config loading."""
    from argos import config as C

    cfg_dir = tmp_path / "from-env-local"
    monkeypatch.delenv("ARGOS_CONFIG_DIR", raising=False)
    monkeypatch.setattr(C, "_ENV", {"ARGOS_CONFIG_DIR": str(cfg_dir)})

    assert _snapshot_root() == cfg_dir / "snapshots"



def test_snapshot_survives_reboot_simulation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Internal documentation."""
    fake_home = tmp_path / "persistent_argos"
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(fake_home))
    # Patch the module constant so any code that imports SNAPSHOT_ROOT directly also
    # sees the tmp path (recover() does `from argos.core.snapshot import SNAPSHOT_ROOT`).
    monkeypatch.setattr(_snap_mod, "SNAPSHOT_ROOT", _snapshot_root())
    # Prove import-time constant == function output under patched env.
    assert _snap_mod.SNAPSHOT_ROOT == _snapshot_root(), (
        "SNAPSHOT_ROOT module constant diverges from _snapshot_root() under patched env"
    )

    root = _snapshot_root()
    root.mkdir(parents=True, exist_ok=True)
    tar_path = root / "test-session-001.tar"

    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "hello.py").write_text("print('hi')")

    snap = RunSnapshot.take(ws, tar_path)
    assert snap.tar_path.exists()

    root2 = _snapshot_root()
    assert root2 == root
    assert (root2 / "test-session-001.tar").exists()

    ws2 = tmp_path / "ws2"
    ws2.mkdir()
    result = snap.restore(ws2)
    assert "hello.py" in result.restored



def _make_manager(tmp_path: Path) -> RunManager:
    return RunManager(
        runs_dir=tmp_path / "runs",
        index_path=tmp_path / "index.json",
    )


def _place_snapshot(snap_root: Path, run_id: str, ws: Path) -> Path:
    """Internal documentation."""
    snap_root.mkdir(parents=True, exist_ok=True)
    p = snap_root / f"run-{run_id}.tar"
    with tarfile.open(p, "w"):
        pass
    return p


@pytest.mark.asyncio
async def test_recover_prunes_terminal_snapshots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Internal documentation."""
    fake_home = tmp_path / "argos_home"
    # setenv BEFORE _snapshot_root() so the root is computed under the patched env.
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(fake_home))
    # Patch the module constant so recover()'s `from argos.core.snapshot import
    # SNAPSHOT_ROOT` sees the tmp path, not the real ~/.argos/snapshots.
    monkeypatch.setattr(_snap_mod, "SNAPSHOT_ROOT", _snapshot_root())
    # Verify patch ordering: module constant must equal _snapshot_root() here.
    assert _snap_mod.SNAPSHOT_ROOT == _snapshot_root(), (
        "SNAPSHOT_ROOT patch order wrong — recover() will hit real ~/.argos"
    )

    snap_root = _snapshot_root()
    ws = tmp_path / "ws"
    ws.mkdir()

    mgr = _make_manager(tmp_path)

    # completed run
    rid_completed = await mgr.create_run(goal="x", workspace=str(ws))
    mgr.mark_running(rid_completed)
    mgr.mark_completed(rid_completed)
    snap_completed = _place_snapshot(snap_root, rid_completed, ws)

    from argos.daemon.state_machine import transition as _trans
    rid_cancelled = await mgr.create_run(goal="y", workspace=str(ws))
    mgr.mark_running(rid_cancelled)
    _trans(
        current=None, target="cancelled",
        index=mgr.index, run_id=rid_cancelled,
        store=mgr.store, reason="test_cancel",
    )
    snap_cancelled = _place_snapshot(snap_root, rid_cancelled, ws)

    rid_failed = await mgr.create_run(goal="z", workspace=str(ws))
    mgr.mark_running(rid_failed)
    mgr.mark_failed(rid_failed, error="test", error_type="TestError", traceback="", step=0)
    snap_failed = _place_snapshot(snap_root, rid_failed, ws)

    mgr2 = _make_manager(tmp_path)
    mgr2.recover()

    assert not snap_completed.exists(), "completed 快照应被剪枝"
    assert not snap_cancelled.exists(), "cancelled 快照应被剪枝"
    assert not snap_failed.exists(), "failed 快照应被剪枝"


@pytest.mark.asyncio
async def test_recover_keeps_suspended_snapshot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Internal documentation."""
    fake_home = tmp_path / "argos_home"
    # setenv BEFORE _snapshot_root() so the root is computed under the patched env.
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(fake_home))
    monkeypatch.setattr(_snap_mod, "SNAPSHOT_ROOT", _snapshot_root())
    assert _snap_mod.SNAPSHOT_ROOT == _snapshot_root(), (
        "SNAPSHOT_ROOT patch order wrong — recover() will hit real ~/.argos"
    )

    snap_root = _snapshot_root()
    ws = tmp_path / "ws"
    ws.mkdir()

    mgr1 = _make_manager(tmp_path)
    rid = await mgr1.create_run(goal="x", workspace=str(ws))
    mgr1.mark_running(rid)
    snap_path = _place_snapshot(snap_root, rid, ws)

    mgr2 = _make_manager(tmp_path)
    recovered = mgr2.recover()
    assert recovered[rid] == "suspended"
    assert snap_path.exists(), "suspended run 快照不应被剪枝"
