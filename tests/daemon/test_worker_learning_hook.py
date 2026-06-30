"""Loop-4 power-on: daemon worker passes a real runner_factory to on_run_completed.

Verifies that _maybe_run_learning_hook builds runner_factory from loop_factory +
worktree and passes it into on_run_completed (not None).
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_fake_manager(tmp_path: Path, run_id: str, verdict_status: str = "passed"):
    """Minimal manager stub for RunWorker._maybe_run_learning_hook."""
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)

    events = [
        {"kind": "session_start", "goal": "do x", "seq": 0},
        {"kind": "verify_verdict",
         "verdict": {"status": verdict_status, "verify_cmd": "pytest -q"}, "seq": 1},
    ]
    p = runs_dir / f"{run_id}.jsonl"
    with p.open("w") as fh:
        for ev in events:
            fh.write(json.dumps(ev) + "\n")

    store = MagicMock()
    store.runs_dir.return_value = runs_dir
    store.replay.return_value = iter(events)

    index = MagicMock()
    entry = MagicMock()
    entry.goal = "do x"
    entry.workspace = str(tmp_path / "workspace")
    index.get.return_value = entry

    manager = MagicMock()
    manager.store = store
    manager.index = index
    manager.get_run.return_value = entry
    return manager


@pytest.mark.asyncio
async def test_worker_passes_runner_factory_to_hook(tmp_path, monkeypatch):
    """Worker builds runner_factory (not None) when loop_factory + worktree are set."""
    from argos.daemon.worker import RunWorker

    hook_calls: list[dict] = []

    async def _fake_on_run_completed(**kw):
        hook_calls.append(kw)

    monkeypatch.setattr(
        "argos.learning.hook.on_run_completed",
        _fake_on_run_completed,
    )

    run_id = "test000abc12"
    manager = _make_fake_manager(tmp_path, run_id)

    fake_loop = MagicMock()
    loop_factory = lambda: fake_loop  # noqa: E731

    fake_worktree = MagicMock()
    fake_worktree.create.return_value = str(tmp_path / "wt")
    fake_worktree.cleanup.return_value = None

    worker = RunWorker(
        run_id=run_id,
        manager=manager,
        loop_factory=loop_factory,
        worktree=fake_worktree,
    )

    entry = manager.get_run(run_id)
    await worker._maybe_run_learning_hook(entry)

    assert len(hook_calls) == 1
    kw = hook_calls[0]
    # runner_factory must NOT be None — Loop-4 is powered on
    assert kw["runner_factory"] is not None, (
        "runner_factory must be non-None when loop_factory and worktree are available"
    )
    # calling it returns an EvalRunner-like object
    runner = kw["runner_factory"]()
    assert runner is not None


@pytest.mark.asyncio
async def test_worker_falls_back_to_none_without_worktree(tmp_path, monkeypatch):
    """Without worktree, runner_factory gracefully falls back to None."""
    from argos.daemon.worker import RunWorker

    hook_calls: list[dict] = []

    async def _fake_on_run_completed(**kw):
        hook_calls.append(kw)

    monkeypatch.setattr(
        "argos.learning.hook.on_run_completed",
        _fake_on_run_completed,
    )

    run_id = "test000abc12"
    manager = _make_fake_manager(tmp_path, run_id)

    worker = RunWorker(
        run_id=run_id,
        manager=manager,
        loop_factory=lambda: MagicMock(),
        worktree=None,  # no worktree → runner_factory stays None
    )

    entry = manager.get_run(run_id)
    await worker._maybe_run_learning_hook(entry)

    assert hook_calls[0]["runner_factory"] is None


@pytest.mark.asyncio
async def test_worker_falls_back_to_none_without_loop_factory(tmp_path, monkeypatch):
    """Without loop_factory, runner_factory gracefully falls back to None."""
    from argos.daemon.worker import RunWorker

    hook_calls: list[dict] = []

    async def _fake_on_run_completed(**kw):
        hook_calls.append(kw)

    monkeypatch.setattr(
        "argos.learning.hook.on_run_completed",
        _fake_on_run_completed,
    )

    run_id = "test000abc12"
    manager = _make_fake_manager(tmp_path, run_id)
    fake_worktree = MagicMock()

    worker = RunWorker(
        run_id=run_id,
        manager=manager,
        loop_factory=None,  # no loop_factory → runner_factory stays None
        worktree=fake_worktree,
    )

    entry = manager.get_run(run_id)
    await worker._maybe_run_learning_hook(entry)

    assert hook_calls[0]["runner_factory"] is None
