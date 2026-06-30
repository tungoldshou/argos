"""工作流默认 on(batch5 autonomy flip)。

验证:
1. 无 env var → propose_workflow 注入系统提示 + dispatch 路径走(不出纠偏)。
2. ARGOS_WORKFLOWS=0 → 注入关闭 + dispatch 关闭(出纠偏)。
"""
from __future__ import annotations

import pytest

from argos.core.loop import AgentLoop, LoopConfig
from argos.core.verify_gate import Verifier
from argos.tui.events import EventBus
from tests.test_loop_codeact import FakeStore
from tests.test_loop_verify_propose import _ProposeSandbox, _RecModel


def _make_loop(model):
    return AgentLoop(
        store=FakeStore(), bus=EventBus(), sandbox=_ProposeSandbox(lambda c: None),
        broker=None, model=model, verifier=Verifier(),
        config=LoopConfig(verify_cmd=None, max_steps=8),
    )


# ── system prompt injection ────────────────────────────────────────────────────

def test_workflow_prompt_injected_by_default(monkeypatch):
    """无 env var → WORKFLOW_PROMPT 进系统提示。"""
    monkeypatch.delenv("ARGOS_WORKFLOWS", raising=False)
    model = _RecModel(["完成。"])
    loop = _make_loop(model)
    stable, dynamic = loop._build_system_pair("test")
    assert "propose_workflow" in stable, "默认应注入 WORKFLOW_PROMPT"


def test_workflow_prompt_suppressed_when_zero(monkeypatch):
    """ARGOS_WORKFLOWS=0 → WORKFLOW_PROMPT 不进系统提示。"""
    monkeypatch.setenv("ARGOS_WORKFLOWS", "0")
    model = _RecModel(["完成。"])
    loop = _make_loop(model)
    stable, dynamic = loop._build_system_pair("test")
    assert "propose_workflow" not in stable, "ARGOS_WORKFLOWS=0 不应注入 WORKFLOW_PROMPT"


def test_workflow_prompt_injected_when_explicit_one(monkeypatch):
    """ARGOS_WORKFLOWS=1 显式开启 → 注入。"""
    monkeypatch.setenv("ARGOS_WORKFLOWS", "1")
    model = _RecModel(["完成。"])
    loop = _make_loop(model)
    stable, dynamic = loop._build_system_pair("test")
    assert "propose_workflow" in stable


# ── dispatch behaviour ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_propose_workflow_dispatched_by_default(monkeypatch):
    """无 env var → propose_workflow → dispatch(不出纠偏文字)。"""
    monkeypatch.delenv("ARGOS_WORKFLOWS", raising=False)
    model = _RecModel([
        "```python\npropose_workflow({'name': 'x', 'stages': []})\n```",
        "完成。",
    ])
    loop = _make_loop(model)
    async for _ in loop.run("任务", "s"):
        pass
    flat = "\n".join(msg for call in model.seen for msg in call)
    assert "工作流已禁用" not in flat and "disabled" not in flat, \
        "默认开启时不应出现工作流纠偏"


@pytest.mark.asyncio
async def test_propose_workflow_swallowed_when_zero(monkeypatch):
    """ARGOS_WORKFLOWS=0 → propose_workflow → 纠偏回灌。"""
    monkeypatch.setenv("ARGOS_WORKFLOWS", "0")
    model = _RecModel([
        "```python\npropose_workflow({'name': 'x', 'stages': []})\n```",
        "完成。",
    ])
    loop = _make_loop(model)
    async for _ in loop.run("任务", "s"):
        pass
    flat = "\n".join(msg for call in model.seen for msg in call)
    assert "工作流已禁用" in flat or "disabled" in flat, \
        "ARGOS_WORKFLOWS=0 时应出现诚实纠偏"
