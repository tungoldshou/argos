import pytest
from argos_agent.workflow.spec import parse_spec
from argos_agent.workflow.engine import WorkflowEngine


@pytest.mark.asyncio
async def test_panel_threshold_vote(tmp_path, voting_model_factory):
    spec = parse_spec({"name": "x", "description": "", "stages": [
        {"id": "judge", "op": "panel", "voters": 3, "threshold": 2,
         "agent": {"prompt": "判 X 是否真,给出 [VOTE:YES] 或 [VOTE:NO]", "tool_scope": "read"}}]})
    engine = WorkflowEngine.for_test(workspace=tmp_path, model_factory=voting_model_factory)
    [ev async for ev in engine.run(spec)]
    sr = engine.last_result.stages[0]
    assert len(sr.results) == 3
    assert "通过" in engine.last_result.synthesis or "2/3" in engine.last_result.synthesis


@pytest.mark.asyncio
async def test_pipeline_each_item_through_stages(tmp_path, scripted_model_factory):
    spec = parse_spec({"name": "x", "description": "", "stages": [
        {"id": "p", "op": "pipeline", "over": ["a", "b"],
         "agent": [{"prompt": "阶段1 {item}", "tool_scope": "read"},
                   {"prompt": "阶段2 {item}", "tool_scope": "read"}]}]})
    engine = WorkflowEngine.for_test(workspace=tmp_path, model_factory=scripted_model_factory)
    [ev async for ev in engine.run(spec)]
    assert len(engine.last_result.stages[0].results) == 2


@pytest.mark.asyncio
async def test_loop_until_target_stops(tmp_path, scripted_model_factory):
    spec = parse_spec({"name": "x", "description": "", "stages": [
        {"id": "L", "op": "loop_until", "over": ["a", "b"], "target": 2,
         "agent": {"prompt": "找 {item}", "tool_scope": "read"}}]})
    engine = WorkflowEngine.for_test(workspace=tmp_path, model_factory=scripted_model_factory)
    [ev async for ev in engine.run(spec)]
    # target=2,首轮 2 个成功即达标停;累计成功结果 >= 2
    ok = [r for r in engine.last_result.stages[0].results if r.ok]
    assert len(ok) >= 2
