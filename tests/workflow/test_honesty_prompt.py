from argos_agent.core.honesty import HONESTY_SYSTEM


def test_honesty_mentions_propose_workflow_and_ops():
    s = HONESTY_SYSTEM
    assert "propose_workflow" in s
    for op in ("fan_out", "pipeline", "panel", "loop_until", "synthesize"):
        assert op in s, f"提示应提到 op {op}"


def test_honesty_workflow_independence_and_depth():
    s = HONESTY_SYSTEM
    assert "独立" in s          # 何时用:互相独立的子任务
    # 深度恒 1 / 子 agent 不能再开工作流
    assert ("深度" in s) or ("子 agent" in s and "工作流" in s)
