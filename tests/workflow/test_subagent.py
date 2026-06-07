import pytest

from argos_agent.workflow.spec import AgentTask
from argos_agent.workflow.subagent import SubAgentFactory


@pytest.mark.asyncio
async def test_read_scope_subagent_returns_result(
    tmp_path, scripted_model_factory, requires_sandbox,
):
    factory = SubAgentFactory.for_test(workspace=tmp_path, model_factory=scripted_model_factory)
    task = AgentTask(prompt="总结 {item}", tool_scope="read")
    res = await factory.run_task(task, item="README", agent_id="s#0", on_phase=lambda *a: None)
    assert res.agent_id == "s#0"
    assert res.ok is True
    assert isinstance(res.output, str)


@pytest.mark.asyncio
async def test_subagent_failure_is_captured_not_raised(
    tmp_path, failing_model_factory, requires_sandbox,
):
    factory = SubAgentFactory.for_test(workspace=tmp_path, model_factory=failing_model_factory)
    task = AgentTask(prompt="x", tool_scope="read")
    res = await factory.run_task(task, item="i", agent_id="s#0", on_phase=lambda *a: None)
    assert res.ok is False and res.error
