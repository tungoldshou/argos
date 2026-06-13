"""并行子 agent 写文件的端到端铁证(真 Seatbelt + ScriptedModel,CI 离线)。

两条不变量:
  · isolation=none —— 子 agent 写在共享工作区,改动直接落地(父/用户可见)。
  · isolation=worktree —— 子 agent 写在隔离 worktree,RAII 拆 worktree 前把改动抓成
    unified diff 回到 AgentResult.output(v1 不自动合并,给 diff 供父/用户决定);
    主工作区不被污染,worktree 拆净。
"""
from __future__ import annotations

import subprocess
import sys

import pytest

from argos.workflow.engine import WorkflowEngine
from argos.workflow.spec import parse_spec

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="真 Seatbelt 沙箱仅 macOS")


def _writer_factory(filenames):
    """stateful model factory:第 i 次构造的子 agent step0 写第 i 个文件,step1 收尾。"""
    from tests.e2e.scripted_model import ScriptedModelClient

    state = {"i": 0}

    def make(profile=None):
        i = state["i"]
        state["i"] += 1
        fn = filenames[min(i, len(filenames) - 1)]
        return ScriptedModelClient([
            f"```python\nwrite_file({fn!r}, 'V = {i}\\n')\n```",
            "已写入,完成。",
        ])

    return make


@pytest.mark.asyncio
async def test_fanout_full_scope_shared_workspace_writes_persist(tmp_path, requires_sandbox):
    # isolation=none:并行子 agent 写不重叠文件 → 直接落共享工作区。
    spec = parse_spec({"name": "build", "description": "并行写两文件", "stages": [
        {"id": "w", "op": "fan_out", "over": ["x", "y"], "cap": 2,
         "agent": {"prompt": "写 {item}", "tool_scope": "full", "isolation": "none"}}]})
    engine = WorkflowEngine.for_test(workspace=tmp_path,
                                     model_factory=_writer_factory(["wf_a.py", "wf_b.py"]))
    [ev async for ev in engine.run(spec)]
    res = engine.last_result
    assert all(r.ok for r in res.stages[0].results)
    assert (tmp_path / "wf_a.py").exists(), "isolation=none 子 agent 写的文件应落共享工作区"
    assert (tmp_path / "wf_b.py").exists()


@pytest.mark.asyncio
async def test_fanout_worktree_captures_diff(tmp_path, requires_sandbox):
    # isolation=worktree:子 agent 在隔离 worktree 写,改动以 diff 回到结果(拆 worktree 不丢)。
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "seed.txt").write_text("seed")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "-c", "user.email=a@b.c", "-c", "user.name=t",
                    "commit", "-qm", "init"], cwd=tmp_path, check=True)
    spec = parse_spec({"name": "iso", "description": "隔离写", "stages": [
        {"id": "w", "op": "fan_out", "over": ["x"], "cap": 1,
         "agent": {"prompt": "写 {item}", "tool_scope": "full", "isolation": "worktree"}}]})
    engine = WorkflowEngine.for_test(workspace=tmp_path,
                                     model_factory=_writer_factory(["iso_out.py"]))
    [ev async for ev in engine.run(spec)]
    res = engine.last_result
    out = res.stages[0].results[0].output
    assert "iso_out.py" in out and "diff" in out.lower(), "worktree 改动应以 diff 回到结果"
    # 主工作区未被污染(隔离),worktree 已拆。
    assert not (tmp_path / "iso_out.py").exists()
    assert not (tmp_path / ".argos_worktrees").exists() or \
        not list((tmp_path / ".argos_worktrees").iterdir())
