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


@pytest.mark.parametrize("trivial_verify", ["echo done", "true", "cat", "ls", "pwd", ":"])
def test_trivial_stage_verify_rejected(trivial_verify):
    # P0 纵深:stage 的 verify 由模型在 propose_workflow 里自著(过去零校验)。模型填 trivial
    # verify(echo/cat/...)= 自助开绿灯。canonical Verifier 最终会判 unverifiable(P0#2 统一门),
    # 但解析层 fail-fast 立即拒,与 role/tool_scope 校验同风格,给模型即时反馈。
    with pytest.raises(WorkflowSpecError, match="verify"):
        parse_spec({"name": "x", "description": "", "stages": [
            {"id": "s", "op": "fan_out", "over": ["a"],
             "agent": {"prompt": "p", "verify": trivial_verify}}]})


def test_real_stage_verify_accepted():
    # 真验证命令(pytest)不受反琐碎门影响,正常解析。
    spec = parse_spec({"name": "x", "description": "", "stages": [
        {"id": "s", "op": "fan_out", "over": ["a"],
         "agent": {"prompt": "p", "verify": "pytest -q test_x.py"}}]})
    assert spec.stages[0].agent.verify == "pytest -q test_x.py"
