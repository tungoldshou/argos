"""Dynamic Workflows Task 10:Esc 取消工作流时 RAII 拆干净资源。

证明:取消正在跑的 run worker(CancelledError 传进 engine.run → gather → 子 agent 的
run_task)时,子 agent 的 `with worktree_for(...)` finally 与 `finally: sandbox.close()`
仍在取消路径上执行 —— 无残留 worktree、CancelledError 正确传播不被误吞成 AgentResult。
"""
import asyncio
import subprocess

import pytest

from argos.workflow.engine import WorkflowEngine
from argos.workflow.spec import parse_spec


def _git_init(p):
    subprocess.run(["git", "init", "-q"], cwd=p, check=True)
    (p / "f.txt").write_text("hi")
    subprocess.run(["git", "add", "-A"], cwd=p, check=True)
    subprocess.run(["git", "-c", "user.email=a@b.c", "-c", "user.name=t",
                    "commit", "-qm", "init"], cwd=p, check=True)


@pytest.mark.slow  # 需要 asyncio.sleep(2.0) 等子 agent 建好 worktree 后再取消 —— 真实时钟等待。
@pytest.mark.asyncio
async def test_cancel_tears_down_worktrees(tmp_path, slow_model_factory):
    _git_init(tmp_path)
    spec = parse_spec({"name": "x", "description": "", "stages": [
        {"id": "r", "op": "fan_out", "over": ["a", "b"], "cap": 2,
         "agent": {"prompt": "看 {item}", "tool_scope": "full", "isolation": "worktree"}}]})
    engine = WorkflowEngine.for_test(workspace=tmp_path, model_factory=slow_model_factory)

    async def _consume():
        async for _ev in engine.run(spec):
            pass

    task = asyncio.create_task(_consume())
    await asyncio.sleep(2.0)        # 让子 agent 起来、建好 worktree、卡在 stream sleep
    # 取消前确认 worktree 确已建出来(否则测的就不是取消路径)
    wt_dir = tmp_path / ".argos_worktrees"
    assert wt_dir.exists() and list(wt_dir.iterdir()), "子 agent 还没建出 worktree,取消时机太早"

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    # 给 finally 清理一点时间
    await asyncio.sleep(0.5)

    residual = [p for p in (wt_dir.iterdir() if wt_dir.exists() else [])]
    assert residual == [], f"取消后仍有残留 worktree:{residual}"
    # git worktree list 也不应有除主仓外的残留
    out = subprocess.run(["git", "-C", str(tmp_path), "worktree", "list"],
                         capture_output=True, text=True).stdout
    assert out.count("\n") <= 1, f"git worktree 仍有残留:{out}"
