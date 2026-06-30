"""工作流诚实:ARGOS_WORKFLOWS=0 显式关闭时 host 不 dispatch propose_workflow,但沙箱回执仍说
"待审批后执行"(沙箱子进程不知 host 开关)。loop 须诚实纠偏一次,告诉模型该提议不会执行、改
单线程完成 —— 否则模型空等一个不会跑的工作流。

默认(无 env var)工作流是 ON —— autonomy flip, batch5。
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


@pytest.mark.asyncio
async def test_workflow_proposal_when_off_gets_honest_nudge(monkeypatch):
    """ARGOS_WORKFLOWS=0 → host 拒绝 dispatch → 诚实纠偏。"""
    monkeypatch.setenv("ARGOS_WORKFLOWS", "0")
    model = _RecModel([
        "```python\npropose_workflow({'name': 'audit', 'stages': []})\n```",
        "完成。",
    ])
    loop = _make_loop(model)
    async for _ in loop.run("审计代码", "s"):
        pass
    flat = "\n".join(msg for call in model.seen for msg in call)
    assert "工作流已禁用" in flat or "disabled" in flat, \
        "工作流关闭时模型提议 propose_workflow → 应回灌诚实纠偏(别空等)"


@pytest.mark.asyncio
async def test_workflow_proposal_when_on_no_nudge(monkeypatch):
    """工作流默认 on(无 env var)→ dispatch 路径走,不出现纠偏。"""
    monkeypatch.delenv("ARGOS_WORKFLOWS", raising=False)
    model = _RecModel([
        "```python\npropose_workflow({'name': 'audit', 'stages': []})\n```",
        "完成。",
    ])
    loop = _make_loop(model)
    async for _ in loop.run("审计代码", "s"):
        pass
    flat = "\n".join(msg for call in model.seen for msg in call)
    assert "工作流已禁用" not in flat and "disabled" not in flat, \
        "工作流开启(默认)时不应出现'未启用'纠偏(走 dispatch 路径)"


@pytest.mark.asyncio
async def test_workflow_proposal_explicit_on_no_nudge(monkeypatch):
    """ARGOS_WORKFLOWS=1 显式开启 → dispatch 路径走,不出现纠偏。"""
    monkeypatch.setenv("ARGOS_WORKFLOWS", "1")
    model = _RecModel([
        "```python\npropose_workflow({'name': 'audit', 'stages': []})\n```",
        "完成。",
    ])
    loop = _make_loop(model)
    async for _ in loop.run("审计代码", "s"):
        pass
    flat = "\n".join(msg for call in model.seen for msg in call)
    assert "工作流已禁用" not in flat and "disabled" not in flat, \
        "工作流显式开启(ARGOS_WORKFLOWS=1)时不应出现纠偏"


@pytest.mark.asyncio
async def test_no_nudge_when_no_workflow_proposed(monkeypatch):
    """普通任务(没提议工作流)→ 不该出现任何工作流纠偏噪音。"""
    monkeypatch.setenv("ARGOS_WORKFLOWS", "0")
    model = _RecModel([
        "```python\nwrite_file('x.py', 'x=1')\n```",
        "完成。",
    ])
    loop = _make_loop(model)
    async for _ in loop.run("写个文件", "s"):
        pass
    flat = "\n".join(msg for call in model.seen for msg in call)
    assert "工作流已禁用" not in flat and "disabled" not in flat
