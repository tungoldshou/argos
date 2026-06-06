"""Task 9 集成铁证:父 agent 在 act 段提议工作流 → loop 钩子校验+审批(AUTO 放行)+
异步跑引擎+结果回灌。真起父+子沙箱(慢点正常)。"""
import pytest


@pytest.mark.asyncio
async def test_parent_proposes_workflow_runs_and_feeds_back(workflow_loop):
    events = [ev async for ev in workflow_loop.run("并行审计 a", session_id="t")]
    kinds = [type(e).__name__ for e in events]
    assert "WorkflowProposed" in kinds
    assert "WorkflowProgress" in kinds
    assert "WorkflowDone" in kinds
