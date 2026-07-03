"""Internal documentation."""
import pytest


@pytest.mark.asyncio
async def test_parent_proposes_workflow_runs_and_feeds_back(workflow_loop):
    events = [ev async for ev in workflow_loop.run("并行审计 a", session_id="t")]
    kinds = [type(e).__name__ for e in events]
    assert "WorkflowProposed" in kinds
    assert "WorkflowProgress" in kinds
    assert "WorkflowDone" in kinds
