"""_autonomous_dream_starter three-guard block test.

Guards:
  1. pipeline.is_running       — daemon is already running dream
  2. self._dream_starting      — TOCTOU: task spawned but coroutine not yet running
  3. pipeline.cross_process_busy() — another process (CLI) holds the cross-process lock

Tests drive _autonomous_dream_starter directly (no HTTP server, no real pipeline)
and assert: each guard true → returns False (no start); all guards false → returns True.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from argos.daemon.manager import RunManager
from argos.daemon.server import DaemonHTTPServer


def _make_server(tmp_path: Path) -> DaemonHTTPServer:
    """Minimal DaemonHTTPServer with no components (no key mode)."""
    store = MagicMock()
    store.runs_dir.return_value = tmp_path / "runs"
    manager = MagicMock(spec=RunManager)
    manager.store = store
    manager.index = MagicMock()

    return DaemonHTTPServer(
        manager=manager,
        socket_path=tmp_path / "daemon.sock",
        components=None,  # no-key mode; we inject _dream_pipeline directly
    )


def _fake_pipeline(*, is_running: bool = False, cross_busy: bool = False) -> MagicMock:
    p = MagicMock()
    p.is_running = is_running
    p.cross_process_busy = MagicMock(return_value=cross_busy)
    # run() returns a coroutine so create_task works
    p.run = AsyncMock(return_value=None)
    return p


def test_dreams_dir_honors_argos_config_dir(tmp_path: Path, monkeypatch):
    from argos import config as C

    cfg_dir = tmp_path / ".argos"
    monkeypatch.delenv("ARGOS_DREAMS_DIR", raising=False)
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(cfg_dir))
    monkeypatch.setattr(C, "_ENV", {})

    assert _make_server(tmp_path)._dreams_dir() == cfg_dir / "dreams"


def test_dreams_dir_expands_explicit_env_override(tmp_path: Path, monkeypatch):
    fake_home = tmp_path / "home"
    monkeypatch.setenv("ARGOS_DREAMS_DIR", "~/argos-dreams")
    monkeypatch.setenv("HOME", str(fake_home))

    assert _make_server(tmp_path)._dreams_dir() == fake_home / "argos-dreams"


def test_dream_pipeline_paths_honor_argos_config_dir(tmp_path: Path, monkeypatch):
    from types import SimpleNamespace
    from argos import config as C

    cfg_dir = tmp_path / ".argos"
    monkeypatch.delenv("ARGOS_DREAMS_DIR", raising=False)
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(cfg_dir))
    monkeypatch.setattr(C, "_ENV", {})

    seen: dict[str, Path] = {}

    class FakeDreamPipeline:
        def __init__(self, **kwargs):  # noqa: ANN003
            seen["candidates_root"] = kwargs["candidates_root"]
            seen["skills_root"] = kwargs["skills_root"]
            seen["memory_dir"] = kwargs["memory_dir"]
            seen["dreams_dir"] = kwargs["dreams_dir"]

    class FakeEvalRunner:
        def __init__(self, *, base_dir, **kwargs):  # noqa: ANN003
            seen["eval_base"] = base_dir

    class FakeModel:
        async def complete(self, *args, **kwargs):  # noqa: ANN002, ANN003
            return "ok"

    monkeypatch.setattr("argos.learning.dream.DreamPipeline", FakeDreamPipeline)
    monkeypatch.setattr("argos.eval.runner.EvalRunner", FakeEvalRunner)
    monkeypatch.setattr(
        "argos.app_factory.build_run_stack",
        lambda *args, **kwargs: SimpleNamespace(loop_factory=lambda: object()),
    )

    srv = _make_server(tmp_path)
    srv._components = SimpleNamespace(model=FakeModel())
    srv._get_dream_pipeline()

    assert seen["candidates_root"] == cfg_dir / "learning" / "candidates"
    assert seen["skills_root"] == cfg_dir / "skills"
    assert seen["memory_dir"] == cfg_dir / "memory"
    assert seen["dreams_dir"] == cfg_dir / "dreams"
    assert seen["eval_base"] == cfg_dir / "dreams" / "eval"


# ── guard 1: is_running → False, no start ────────────────────────────────────

@pytest.mark.asyncio
async def test_guard_is_running_blocks(tmp_path: Path):
    srv = _make_server(tmp_path)
    pipeline = _fake_pipeline(is_running=True)
    srv._dream_pipeline = pipeline  # inject fake

    result = await srv._autonomous_dream_starter(MagicMock())

    assert result is False
    pipeline.run.assert_not_called()


# ── guard 2: _dream_starting → False, no start ───────────────────────────────

@pytest.mark.asyncio
async def test_guard_dream_starting_blocks(tmp_path: Path):
    srv = _make_server(tmp_path)
    pipeline = _fake_pipeline(is_running=False)
    srv._dream_pipeline = pipeline
    srv._dream_starting = True  # TOCTOU flag already set

    result = await srv._autonomous_dream_starter(MagicMock())

    assert result is False
    pipeline.run.assert_not_called()


# ── guard 3: cross_process_busy → False, no start ────────────────────────────

@pytest.mark.asyncio
async def test_guard_cross_process_busy_blocks(tmp_path: Path):
    srv = _make_server(tmp_path)
    pipeline = _fake_pipeline(is_running=False, cross_busy=True)
    srv._dream_pipeline = pipeline

    result = await srv._autonomous_dream_starter(MagicMock())

    assert result is False
    pipeline.run.assert_not_called()


# ── no pipeline (no key) → False, no start ───────────────────────────────────

@pytest.mark.asyncio
async def test_no_pipeline_returns_false(tmp_path: Path):
    srv = _make_server(tmp_path)
    # _dream_pipeline stays None (no components → _get_dream_pipeline returns None)

    result = await srv._autonomous_dream_starter(MagicMock())

    assert result is False


# ── all guards clear → task spawned, returns True ────────────────────────────

@pytest.mark.asyncio
async def test_all_guards_clear_starts_dream(tmp_path: Path):
    srv = _make_server(tmp_path)
    pipeline = _fake_pipeline(is_running=False, cross_busy=False)
    srv._dream_pipeline = pipeline

    result = await srv._autonomous_dream_starter(MagicMock())

    assert result is True
    pipeline.run.assert_called_once()
    # _dream_starting is reset by done_callback after the task completes.
    # AsyncMock resolves on the next iteration; done_callback fires after that.
    # Two yields are enough: one to run the coro, one to fire the callback.
    for _ in range(3):
        await asyncio.sleep(0)
    assert srv._dream_starting is False
