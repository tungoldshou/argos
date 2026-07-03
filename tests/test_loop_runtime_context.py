"""Internal documentation."""
from __future__ import annotations

from pathlib import Path

import pytest

from argos.core.loop import AgentLoop, LoopConfig
from argos.core.verify_gate import Verifier
from argos.tui.events import EventBus
from tests.test_loop_codeact import FakeModel, FakeStore


class _CapturingSandbox:
    """Internal documentation."""

    def __init__(self) -> None:
        self.captured: tuple | None = None

    def spawn(self, *, workspace, namespace, allow_workflow=True, read_only=False) -> None:
        from argos import runtime
        cur = runtime.current()
        self.captured = (cur.project_mode, Path(cur.workspace), Path(cur.verify_dir))

    def exec_code(self, code):
        from argos.sandbox.backend import ExecResult
        return ExecResult(stdout="ok", value_repr="", exc="")

    def close(self) -> None:
        pass


@pytest.mark.asyncio
async def test_managed_loop_establishes_project_context_at_spawn(tmp_path):
    """Internal documentation."""
    ws = tmp_path / "proj"
    ws.mkdir()
    (ws / "test_existing.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")

    from argos import runtime
    snap = runtime._current_var.get()
    runtime._current_var.set(runtime._make_default_ctx())
    sb = _CapturingSandbox()
    try:
        loop = AgentLoop(
            store=FakeStore(), bus=EventBus(), sandbox=sb, broker=None,
            model=FakeModel(["完成。"]), verifier=Verifier(),
            config=LoopConfig(verify_cmd=None),
            workspace=ws, verify_dir=ws,
            manage_runtime_context=True, project_mode=True,
        )
        async for _ in loop.run("看看", "s"):
            pass
        assert sb.captured == (True, ws, ws), f"spawn 时应已建立 project 上下文,实得 {sb.captured}"
        cur = runtime.current()
        assert cur.project_mode is True and cur.workspace == ws
        (ws / "test_existing.py").write_text("def test_ok():\n    assert False\n", encoding="utf-8")
        assert any("test_existing.py" in c for c in runtime.detect_tampering())
    finally:
        runtime._current_var.set(snap)


@pytest.mark.asyncio
async def test_unmanaged_loop_leaves_context_untouched(tmp_path):
    """Internal documentation."""
    ws = tmp_path / "proj"
    ws.mkdir()

    from argos import runtime
    from argos.runtime import RunContext
    snap = runtime._current_var.get()
    runtime._current_var.set(RunContext(workspace=ws, verify_dir=ws / "v", project_mode=False))
    sb = _CapturingSandbox()
    try:
        loop = AgentLoop(
            store=FakeStore(), bus=EventBus(), sandbox=sb, broker=None,
            model=FakeModel(["完成。"]), verifier=Verifier(),
            config=LoopConfig(verify_cmd=None),
            workspace=ws, verify_dir=ws,
        )
        async for _ in loop.run("看看", "s"):
            pass
        assert sb.captured == (False, ws, ws / "v")
    finally:
        runtime._current_var.set(snap)
