from argos.workflow.spec import parse_spec
from argos.workflow.result import render_preview, AgentResult, StageResult, WorkflowResult


def test_render_preview_lists_agents_and_models():
    spec = parse_spec({
        "name": "audit", "description": "审计",
        "stages": [
            {"id": "review", "op": "fan_out", "over": ["a", "b", "c"],
             "agent": {"prompt": "看 {item}", "model": "cheap", "tool_scope": "read"}},
            {"id": "judge", "op": "panel", "voters": 3, "threshold": 2,
             "agent": {"prompt": "裁判", "model": "smart"}},
        ],
    })
    text = render_preview(spec)
    assert "audit" in text
    assert "review" in text and "3" in text
    assert "cheap" in text and "smart" in text
    assert "judge" in text and "3" in text


def test_workflow_result_aggregates_tokens():
    r = WorkflowResult(
        name="x",
        stages=(StageResult(stage_id="s", results=(
            AgentResult(agent_id="s#0", ok=True, output="done", verdict="passed",
                        tokens_in=10, tokens_out=5),)),),
        synthesis="ok", total_tokens_in=10, total_tokens_out=5, notes=())
    assert r.total_tokens_in == 10
    assert r.stages[0].results[0].verdict == "passed"
