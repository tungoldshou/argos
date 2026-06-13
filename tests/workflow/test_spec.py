import pytest
from argos.workflow.spec import AgentTask, Stage, WorkflowSpec, parse_spec, WorkflowSpecError


def test_parse_minimal_fan_out():
    raw = {
        "name": "audit", "description": "审计 3 个文件",
        "stages": [{
            "id": "review", "op": "fan_out",
            "over": ["a.py", "b.py", "c.py"],
            "agent": {"prompt": "审查 {item}", "tool_scope": "read"},
        }],
    }
    spec = parse_spec(raw)
    assert isinstance(spec, WorkflowSpec)
    assert spec.name == "audit"
    assert spec.stages[0].op == "fan_out"
    assert spec.stages[0].over == ("a.py", "b.py", "c.py")
    assert spec.stages[0].agent.prompt == "审查 {item}"
    assert spec.stages[0].agent.tool_scope == "read"


def test_invalid_op_rejected():
    with pytest.raises(WorkflowSpecError, match="op"):
        parse_spec({"name": "x", "description": "", "stages": [
            {"id": "s", "op": "frobnicate", "agent": {"prompt": "p"}}]})


def test_over_from_must_reference_earlier_stage():
    with pytest.raises(WorkflowSpecError, match="from"):
        parse_spec({"name": "x", "description": "", "stages": [
            {"id": "s2", "op": "fan_out", "over": {"from": "nope"},
             "agent": {"prompt": "p"}}]})


def test_panel_threshold_le_voters():
    with pytest.raises(WorkflowSpecError, match="threshold"):
        parse_spec({"name": "x", "description": "", "stages": [
            {"id": "s", "op": "panel", "voters": 2, "threshold": 5,
             "agent": {"prompt": "p"}}]})


def test_tool_scope_and_isolation_enums():
    with pytest.raises(WorkflowSpecError, match="tool_scope"):
        parse_spec({"name": "x", "description": "", "stages": [
            {"id": "s", "op": "fan_out", "over": ["a"],
             "agent": {"prompt": "p", "tool_scope": "wat"}}]})


def test_duplicate_stage_id_rejected():
    with pytest.raises(WorkflowSpecError, match="重复"):
        parse_spec({"name": "x", "description": "", "stages": [
            {"id": "s", "op": "fan_out", "over": ["a"], "agent": {"prompt": "p"}},
            {"id": "s", "op": "synthesize", "agent": {"prompt": "q"}}]})


def test_negative_voters_normalized_not_misjudged():
    # voters/threshold 负值/0 规范化为 1,不应误抛 threshold 错误
    spec = parse_spec({"name": "x", "description": "", "stages": [
        {"id": "s", "op": "panel", "voters": 0, "threshold": 0, "agent": {"prompt": "p"}}]})
    assert spec.stages[0].voters == 1 and spec.stages[0].threshold == 1
