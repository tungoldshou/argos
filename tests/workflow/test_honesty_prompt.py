"""Internal documentation."""
from argos.core.honesty import HONESTY_SYSTEM, WORKFLOW_PROMPT


def test_workflow_prompt_carries_propose_workflow_and_ops():
    s = WORKFLOW_PROMPT
    assert "propose_workflow" in s
    for op in ("fan_out", "pipeline", "panel", "loop_until", "synthesize", "best_of_n"):
        assert op in s, f"工作流段应提到 op {op}"


def test_workflow_prompt_independence_and_depth():
    s = WORKFLOW_PROMPT
    assert "independent" in s
    assert ("depth is fixed at 1" in s) or ("sub-agents can't open workflows" in s)


def test_workflow_section_absent_from_default_honesty():
    assert "propose_workflow" not in HONESTY_SYSTEM
    assert "fan_out" not in HONESTY_SYSTEM


def test_build_system_pair_respects_argos_workflows_env():
    import inspect
    from argos.core.loop import AgentLoop
    src = inspect.getsource(AgentLoop._build_system_pair)
    assert "ARGOS_WORKFLOWS" in src
    assert "WORKFLOW_PROMPT" in src


def test_build_system_pair_default_on(monkeypatch):
    """Internal documentation."""
    import os
    monkeypatch.delenv("ARGOS_WORKFLOWS", raising=False)

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
    assert "propose_workflow" in stable,\
        "默认(无 env var)应注入 WORKFLOW_PROMPT,使 propose_workflow 可达"


def test_build_system_pair_off_when_zero(monkeypatch):
    """Internal documentation."""
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
    assert "propose_workflow" not in stable,\
        "ARGOS_WORKFLOWS=0 时不应注入 WORKFLOW_PROMPT"
