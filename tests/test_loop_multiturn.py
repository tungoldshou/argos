# tests/test_loop_multiturn.py
import pytest
from argos_agent.core.loop import AgentLoop, LoopConfig
from argos_agent.core.verify_gate import Verdict
from argos_agent.sandbox.backend import ExecResult
from argos_agent.tui.events import EventBus
from argos_agent.memory.store import ArgosStore


class _EchoModel:
    """把它【看到的 messages】记录下来,便于断言历史是否带入。"""
    def __init__(self): self.seen = []
    async def stream(self, messages, *, system):
        self.seen.append([m["content"] for m in messages])
        for ch in "好的。": yield ch


class _FakeSandbox:
    def spawn(self, *, workspace, namespace): pass
    def exec_code(self, code): return ExecResult(stdout="", value_repr="", exc="")
    def close(self): pass


class _NoCmdVerifier:
    def verify(self, verify_cmd, *, attempts=1):
        return Verdict.unverifiable(detail="(无)", tampered=[], attempts=attempts)


@pytest.mark.asyncio
async def test_second_run_sees_first_turn_history(tmp_path):
    store = ArgosStore(db_path=str(tmp_path / "a.db"))
    model = _EchoModel()
    def mk():
        return AgentLoop(store=store, bus=EventBus(), sandbox=_FakeSandbox(), broker=None,
                         model=model, verifier=_NoCmdVerifier(), config=LoopConfig())
    async for _ in mk().run("第一轮:做个贪吃蛇", "sess-A"):
        pass
    async for _ in mk().run("好的", "sess-A"):
        pass
    # 第二轮模型看到的 messages 必须含第一轮的目标(跨轮上下文)
    last_seen = model.seen[-1]
    assert any("贪吃蛇" in c for c in last_seen), "第二轮应带入第一轮历史"
    store.close()
