import pytest

from argos.workflow.spec import (
    AgentTask, ROLE_PRESETS, Stage, WorkflowSpec, parse_spec, WorkflowSpecError,
)


def test_legacy_task_default_role_is_none():
    t = AgentTask(prompt="x")
    assert t.role is None
    assert t.tool_scope == "read"
    assert t.isolation == "none"
    assert t.verify is None
    assert t.model is None


def test_legacy_spec_without_role_parses_unchanged():
    raw = {
        "name": "x", "description": "",
        "stages": [{
            "id": "s", "op": "fan_out", "over": ["a"],
            "agent": {"prompt": "p", "tool_scope": "read"},
        }],
    }
    spec = parse_spec(raw)
    assert isinstance(spec, WorkflowSpec)
    agent = spec.stages[0].agent
    assert isinstance(agent, AgentTask)
    assert agent.role is None
    assert agent.tool_scope == "read"
    assert agent.prompt == "p"


def test_role_accepted_in_raw_spec():
    raw = {
        "name": "x", "description": "",
        "stages": [{
            "id": "s", "op": "fan_out", "over": ["a"],
            "agent": {"prompt": "p", "role": "coder", "verify": "pytest -q"},
        }],
    }
    spec = parse_spec(raw)
    assert spec.stages[0].agent.role == "coder"
    assert spec.stages[0].agent.verify == "pytest -q"


def test_unknown_role_rejected():
    with pytest.raises(WorkflowSpecError, match="role"):
        parse_spec({"name": "x", "description": "", "stages": [
            {"id": "s", "op": "fan_out", "over": ["a"],
             "agent": {"prompt": "p", "role": "wizard"}}]})


REQUIRED_ROLES = ("explorer", "planner", "coder", "reviewer")


def test_all_four_roles_have_presets():
    for r in REQUIRED_ROLES:
        assert r in ROLE_PRESETS, f"缺 role 预设:{r}"


def test_each_preset_has_required_fields():
    for name in REQUIRED_ROLES:
        p = ROLE_PRESETS[name]
        assert isinstance(p.tool_allowlist, frozenset), f"{name}.tool_allowlist 非 frozenset"
        assert len(p.tool_allowlist) > 0, f"{name}.tool_allowlist 为空"
        assert isinstance(p.system_prompt, str) and p.system_prompt.strip(), f"{name} 缺 system_prompt"
        assert isinstance(p.max_steps, int) and 0 < p.max_steps <= 100, f"{name}.max_steps 越界"
        assert isinstance(p.read_only, bool), f"{name}.read_only 非 bool"
        assert isinstance(p.requires_verify, bool), f"{name}.requires_verify 非 bool"


def test_role_tool_allowlist_semantics():
    mutating = {"write_file", "edit_file"}
    explorer = ROLE_PRESETS["explorer"]
    planner = ROLE_PRESETS["planner"]
    reviewer = ROLE_PRESETS["reviewer"]
    coder = ROLE_PRESETS["coder"]
    for r in (explorer, planner, reviewer):
        assert not (r.tool_allowlist & mutating), (
            f"{[n for n in REQUIRED_ROLES if ROLE_PRESETS[n] is r][0]} 不该含写工具:{r.tool_allowlist & mutating}"
        )
    assert "write_file" in coder.tool_allowlist and "edit_file" in coder.tool_allowlist


def test_role_read_only_flags():
    """explorer/planner/reviewer = read_only=True,coder = read_only=False。"""
    assert ROLE_PRESETS["explorer"].read_only is True
    assert ROLE_PRESETS["planner"].read_only is True
    assert ROLE_PRESETS["reviewer"].read_only is True
    assert ROLE_PRESETS["coder"].read_only is False


def test_coder_requires_verify_reviewer_requires_verify():
    assert ROLE_PRESETS["coder"].requires_verify is True
    assert ROLE_PRESETS["reviewer"].requires_verify is True
    assert ROLE_PRESETS["explorer"].requires_verify is False
    assert ROLE_PRESETS["planner"].requires_verify is False


def test_role_max_steps_are_reasonable_caps():
    for r in REQUIRED_ROLES:
        assert ROLE_PRESETS[r].max_steps <= 100


def test_role_conflicts_with_explicit_tool_scope_rejected():
    raw = {
        "name": "x", "description": "",
        "stages": [{
            "id": "s", "op": "fan_out", "over": ["a"],
            "agent": {"prompt": "p", "role": "explorer", "tool_scope": "full"},
        }],
    }
    with pytest.raises(WorkflowSpecError):
        parse_spec(raw)


def test_role_explicit_tool_scope_read_consistent_passes():
    raw = {
        "name": "x", "description": "",
        "stages": [{
            "id": "s", "op": "fan_out", "over": ["a"],
            "agent": {"prompt": "p", "role": "explorer", "tool_scope": "read"},
        }],
    }
    spec = parse_spec(raw)
    assert spec.stages[0].agent.role == "explorer"
    assert spec.stages[0].agent.tool_scope == "read"
