"""工作流提示段。

Batch5 autonomy flip:工作流默认 ON —— WORKFLOW_PROMPT 进系统提示无需 env var。
ARGOS_WORKFLOWS=0 可显式关闭。内容保留在 WORKFLOW_PROMPT;_build_system_pair 根据
env 决定是否注入。
"""
from argos.core.honesty import HONESTY_SYSTEM, WORKFLOW_PROMPT


def test_workflow_prompt_carries_propose_workflow_and_ops():
    s = WORKFLOW_PROMPT
    assert "propose_workflow" in s
    for op in ("fan_out", "pipeline", "panel", "loop_until", "synthesize", "best_of_n"):
        assert op in s, f"工作流段应提到 op {op}"


def test_workflow_prompt_independence_and_depth():
    s = WORKFLOW_PROMPT
    assert "independent" in s          # 何时用:互相独立的子任务(全英文化后断言英文)
    # 深度恒 1 / 子 agent 不能再开工作流
    assert ("depth is fixed at 1" in s) or ("sub-agents can't open workflows" in s)


def test_workflow_section_absent_from_default_honesty():
    # 工作流段独立于 HONESTY_SYSTEM,由 _build_system_pair 按需注入(默认 on)。
    assert "propose_workflow" not in HONESTY_SYSTEM
    assert "fan_out" not in HONESTY_SYSTEM


def test_build_system_pair_respects_argos_workflows_env():
    # _build_system_pair 读 ARGOS_WORKFLOWS env 决定注入(默认 on;=0 关闭)。
    # 源码应包含 ARGOS_WORKFLOWS 和 WORKFLOW_PROMPT 两个引用。
    import inspect
    from argos.core.loop import AgentLoop
    src = inspect.getsource(AgentLoop._build_system_pair)
    assert "ARGOS_WORKFLOWS" in src
    assert "WORKFLOW_PROMPT" in src


def test_build_system_pair_default_on(monkeypatch):
    """无 env var → WORKFLOW_PROMPT 应进系统提示(default-on)。"""
    import os
    monkeypatch.delenv("ARGOS_WORKFLOWS", raising=False)

    # 用 FakeModel 构造最小 loop 并拿 system pair
    from argos.core.loop import AgentLoop, LoopConfig
    from argos.core.verify_gate import Verifier
    from argos.tui.events import EventBus
    from tests.test_loop_codeact import FakeStore
    from tests.test_loop_verify_propose import _ProposeSandbox, _RecModel

    model = _RecModel(["完成。"])
    loop = AgentLoop(
        store=FakeStore(), bus=EventBus(),
        sandbox=_ProposeSandbox(lambda c: None),
        broker=None, model=model, verifier=Verifier(),
        config=LoopConfig(verify_cmd=None, max_steps=2),
    )
    stable, _ = loop._build_system_pair("test")
    assert "propose_workflow" in stable, \
        "默认(无 env var)应注入 WORKFLOW_PROMPT,使 propose_workflow 可达"


def test_build_system_pair_off_when_zero(monkeypatch):
    """ARGOS_WORKFLOWS=0 → WORKFLOW_PROMPT 不注入。"""
    monkeypatch.setenv("ARGOS_WORKFLOWS", "0")

    from argos.core.loop import AgentLoop, LoopConfig
    from argos.core.verify_gate import Verifier
    from argos.tui.events import EventBus
    from tests.test_loop_codeact import FakeStore
    from tests.test_loop_verify_propose import _ProposeSandbox, _RecModel

    model = _RecModel(["完成。"])
    loop = AgentLoop(
        store=FakeStore(), bus=EventBus(),
        sandbox=_ProposeSandbox(lambda c: None),
        broker=None, model=model, verifier=Verifier(),
        config=LoopConfig(verify_cmd=None, max_steps=2),
    )
    stable, _ = loop._build_system_pair("test")
    assert "propose_workflow" not in stable, \
        "ARGOS_WORKFLOWS=0 时不应注入 WORKFLOW_PROMPT"
