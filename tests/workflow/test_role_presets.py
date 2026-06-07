"""role 字段 + 4 角色预设 spec 验收(任务:每个角色独立上下文/工具/提示词/上限)。"""
import pytest

from argos_agent.workflow.spec import (
    AgentTask, ROLE_PRESETS, Stage, WorkflowSpec, parse_spec, WorkflowSpecError,
)


# ── 1. 向后兼容:旧 spec 不填 role 行为不变 ──────────────────────────────
def test_legacy_task_default_role_is_none():
    """旧 AgentTask 构造路径(prompt=...)不填 role → role=None(不破既有实例化)。"""
    t = AgentTask(prompt="x")
    assert t.role is None
    # 旧字段(被这 PR 复用)保留
    assert t.tool_scope == "read"
    assert t.isolation == "none"
    assert t.verify is None
    assert t.model is None


def test_legacy_spec_without_role_parses_unchanged():
    """parse_spec({..., "agent": {"prompt": "p", "tool_scope": "read"}}) → role=None,旧字段全等。"""
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


# ── 2. 校验:非法 role 拒收 ────────────────────────────────────────────
def test_unknown_role_rejected():
    with pytest.raises(WorkflowSpecError, match="role"):
        parse_spec({"name": "x", "description": "", "stages": [
            {"id": "s", "op": "fan_out", "over": ["a"],
             "agent": {"prompt": "p", "role": "wizard"}}]})


# ── 3. 4 角色预设齐备 ────────────────────────────────────────────────
REQUIRED_ROLES = ("explorer", "planner", "coder", "reviewer")


def test_all_four_roles_have_presets():
    for r in REQUIRED_ROLES:
        assert r in ROLE_PRESETS, f"缺 role 预设:{r}"


def test_each_preset_has_required_fields():
    """每个 preset 必须有 tool_allowlist / system_prompt / max_steps / read_only / requires_verify。"""
    for name in REQUIRED_ROLES:
        p = ROLE_PRESETS[name]
        assert isinstance(p.tool_allowlist, frozenset), f"{name}.tool_allowlist 非 frozenset"
        assert len(p.tool_allowlist) > 0, f"{name}.tool_allowlist 为空"
        assert isinstance(p.system_prompt, str) and p.system_prompt.strip(), f"{name} 缺 system_prompt"
        assert isinstance(p.max_steps, int) and 0 < p.max_steps <= 100, f"{name}.max_steps 越界"
        assert isinstance(p.read_only, bool), f"{name}.read_only 非 bool"
        assert isinstance(p.requires_verify, bool), f"{name}.requires_verify 非 bool"


def test_role_tool_allowlist_semantics():
    """explorer/planner/reviewer 都不能写文件;coder 必须能写。"""
    mutating = {"write_file", "edit_file"}
    explorer = ROLE_PRESETS["explorer"]
    planner = ROLE_PRESETS["planner"]
    reviewer = ROLE_PRESETS["reviewer"]
    coder = ROLE_PRESETS["coder"]
    for r in (explorer, planner, reviewer):
        assert not (r.tool_allowlist & mutating), (
            f"{[n for n in REQUIRED_ROLES if ROLE_PRESETS[n] is r][0]} 不该含写工具:{r.tool_allowlist & mutating}"
        )
    # coder 必须含写工具
    assert "write_file" in coder.tool_allowlist and "edit_file" in coder.tool_allowlist


def test_role_read_only_flags():
    """explorer/planner/reviewer = read_only=True,coder = read_only=False。"""
    assert ROLE_PRESETS["explorer"].read_only is True
    assert ROLE_PRESETS["planner"].read_only is True
    assert ROLE_PRESETS["reviewer"].read_only is True
    assert ROLE_PRESETS["coder"].read_only is False


def test_coder_requires_verify_reviewer_requires_verify():
    """coder 与 reviewer 都强制 verify 门(防 coder 写完不测谎报、reviewer 跑检查没用退出码)。"""
    assert ROLE_PRESETS["coder"].requires_verify is True
    assert ROLE_PRESETS["reviewer"].requires_verify is True
    # explorer / planner 允许 no-test 收尾(只读/规划任务天然无机检)
    assert ROLE_PRESETS["explorer"].requires_verify is False
    assert ROLE_PRESETS["planner"].requires_verify is False


def test_role_max_steps_are_reasonable_caps():
    """每个角色 max_steps 既是上限又是安全网 —— 不许超 100(防跑飞)。"""
    for r in REQUIRED_ROLES:
        assert ROLE_PRESETS[r].max_steps <= 100


# ── 4. role 与 tool_scope 冲突:显式填 tool_scope="full" + role="explorer" 应拒收 ─
def test_role_conflicts_with_explicit_tool_scope_rejected():
    """role 派生的工具集合若与显式 tool_scope 矛盾(spec 校验阶段就拒)—— 防自我矛盾。"""
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
    """role=explorer(只读) + tool_scope=read → 一致,过校验。"""
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
