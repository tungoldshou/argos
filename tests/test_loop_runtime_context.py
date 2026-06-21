"""P0 护城河洞:inline 路径(build_loop_factory)必须像 daemon worker 一样建立 runtime context。

现状 bug:daemon 在 worker.py 外部 set_context(project_mode=True),inline 路径却从不设 →
runtime.current() 落默认沙盒(project_mode=False)→ guard_project_tests 直接返 0(篡改检测
整条哑掉)、verify 命令跑在 ~/.argos/verify 空目录而非用户项目。打包 binary 不含 argosd →
真实用户恒走 inline → 三道防线第③道(篡改可见)对发版用户失效。

修复:AgentLoop 增 manage_runtime_context + project_mode;managed 时 run() 起始自建 project
上下文(与 daemon worker.py:322 对称)。build_loop_factory(inline)开此开关。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from argos.core.loop import AgentLoop, LoopConfig
from argos.core.verify_gate import Verifier
from argos.tui.events import EventBus
from tests.test_loop_codeact import FakeModel, FakeStore


class _CapturingSandbox:
    """spawn 时快照 runtime.current() —— 验证 run() 在 spawn(loop.py:845)前已建立上下文。"""

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
    """manage_runtime_context=True + project_mode=True → run() 在 spawn 前建立 project 上下文
    (workspace=verify_dir=loop workspace,project_mode=True),让篡改检测/verify 在正确目录通电。"""
    ws = tmp_path / "proj"
    ws.mkdir()
    (ws / "test_existing.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")

    from argos import runtime
    snap = runtime._current_var.get()
    # 模拟 inline 启动现状:默认沙盒上下文(project_mode=False)
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
        # 篡改检测通电:run 起始已快照既有测试 → 现在改它能被抓(此前 project_mode=False 返 0,抓不到)
        cur = runtime.current()
        assert cur.project_mode is True and cur.workspace == ws
        (ws / "test_existing.py").write_text("def test_ok():\n    assert False\n", encoding="utf-8")
        assert any("test_existing.py" in c for c in runtime.detect_tampering())
    finally:
        runtime._current_var.set(snap)


@pytest.mark.asyncio
async def test_unmanaged_loop_leaves_context_untouched(tmp_path):
    """默认 manage_runtime_context=False(daemon 路径:worker 在外部自设上下文)→ run() 不动上下文。"""
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
        # 未管理:spawn 时上下文仍是调用方所设(daemon 在外部自管,行为零变更)
        assert sb.captured == (False, ws, ws / "v")
    finally:
        runtime._current_var.set(snap)
