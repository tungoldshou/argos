"""工作流提示段。

Phase 5.3(2026-06-20):工作流段默认【不进】系统提示 —— 重型编排,普通编码任务用不上。
内容保留在 WORKFLOW_PROMPT(供 ARGOS_WORKFLOWS=1 时 loop._build_system_pair 条件注入),
不在基础 HONESTY_SYSTEM 里。
"""
from argos.core.honesty import HONESTY_SYSTEM, WORKFLOW_PROMPT


def test_workflow_prompt_carries_propose_workflow_and_ops():
    s = WORKFLOW_PROMPT
    assert "propose_workflow" in s
    for op in ("fan_out", "pipeline", "panel", "loop_until", "synthesize"):
        assert op in s, f"工作流段应提到 op {op}"


def test_workflow_prompt_independence_and_depth():
    s = WORKFLOW_PROMPT
    assert "independent" in s          # 何时用:互相独立的子任务(全英文化后断言英文)
    # 深度恒 1 / 子 agent 不能再开工作流
    assert ("depth is fixed at 1" in s) or ("sub-agents can't open workflows" in s)


def test_workflow_section_absent_from_default_honesty():
    # 默认系统提示不再提工作流(默认 agent 不被重型编排复杂度拖累)。
    assert "propose_workflow" not in HONESTY_SYSTEM
    assert "fan_out" not in HONESTY_SYSTEM


def test_build_system_pair_injects_workflow_prompt_under_flag():
    # _build_system_pair 在 ARGOS_WORKFLOWS 开启时注入 WORKFLOW_PROMPT(镜像 COMPUTER_USE_PROMPT 模式)。
    import inspect
    from argos.core.loop import AgentLoop
    src = inspect.getsource(AgentLoop._build_system_pair)
    assert "ARGOS_WORKFLOWS" in src
    assert "WORKFLOW_PROMPT" in src
