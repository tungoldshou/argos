import pytest
from argos.workflow.spec import parse_spec
from argos.workflow.engine import WorkflowEngine


@pytest.mark.asyncio
async def test_fan_out_runs_one_agent_per_item(tmp_path, scripted_model_factory):
    spec = parse_spec({"name": "x", "description": "", "stages": [
        {"id": "r", "op": "fan_out", "over": ["a", "b", "c"], "cap": 2,
         "agent": {"prompt": "看 {item}", "tool_scope": "read"}}]})
    engine = WorkflowEngine.for_test(workspace=tmp_path, model_factory=scripted_model_factory)
    events = [ev async for ev in engine.run(spec)]
    res = engine.last_result
    assert len(res.stages[0].results) == 3
    assert all(r.ok for r in res.stages[0].results)
    assert res.synthesis
    assert any(getattr(e, "agent_id", None) for e in events)


@pytest.mark.asyncio
async def test_cap_bounds_concurrency(tmp_path, counting_model_factory):
    spec = parse_spec({"name": "x", "description": "", "stages": [
        {"id": "r", "op": "fan_out", "over": ["a","b","c","d","e"], "cap": 2,
         "agent": {"prompt": "{item}", "tool_scope": "read"}}]})
    engine = WorkflowEngine.for_test(workspace=tmp_path, model_factory=counting_model_factory)
    [ev async for ev in engine.run(spec)]
    assert counting_model_factory.peak_concurrency <= 2
