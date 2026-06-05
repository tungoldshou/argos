# tests/test_loop_compaction.py
"""批3 Task 11:长上下文压缩——溢出触发 compact_messages + 重试;store 压缩保留最近 N。"""
import pytest

from argos_agent.core.loop import AgentLoop, LoopConfig
from argos_agent.core.verify_gate import Verdict
from argos_agent.sandbox.backend import ExecResult
from argos_agent.tui.events import EventBus
from argos_agent.memory.store import ArgosStore


class _OverflowThenOkModel:
    """第一次 stream 抛 context_length_exceeded,压缩后第二次正常。"""
    def __init__(self) -> None:
        self.calls = 0

    async def stream(self, messages, *, system):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("context_length_exceeded: too many tokens")
        for ch in "完成。":
            yield ch


class _FakeSandbox:
    def spawn(self, *, workspace, namespace, allow_workflow=True): pass
    def exec_code(self, code): return ExecResult(stdout="", value_repr="", exc="")
    def close(self): pass


class _NoCmdVerifier:
    def verify(self, verify_cmd, *, attempts=1):
        return Verdict.unverifiable(detail="(无)", tampered=[], attempts=attempts)


def test_compact_messages_keeps_recent(tmp_path):
    store = ArgosStore(db_path=str(tmp_path / "d.db"))
    store.ensure_session("s", title="t", model="worker", system_snapshot="")
    for i in range(10):
        store.append_message("s", role="user", content=f"msg{i}")
    store.compact_messages("s", keep_recent=3)
    msgs = store.get_messages("s")
    # 摘要(1) + 最近 3 = 4;顺序:摘要在最前,最近逐字在后
    assert len(msgs) == 4, f"压缩后应剩 摘要+3,实得 {len(msgs)}"
    assert "早期对话摘要" in msgs[0]["content"]
    assert msgs[-1]["content"] == "msg9"
    store.close()


def test_compact_noop_when_under_keep(tmp_path):
    store = ArgosStore(db_path=str(tmp_path / "e.db"))
    store.ensure_session("s", title="t", model="worker", system_snapshot="")
    store.append_message("s", role="user", content="only")
    store.compact_messages("s", keep_recent=5)
    assert store.get_messages("s") == [{"role": "user", "content": "only"}]
    store.close()


@pytest.mark.asyncio
async def test_context_overflow_triggers_compaction_and_retry(tmp_path):
    store = ArgosStore(db_path=str(tmp_path / "c.db"))
    store.ensure_session("s", title="t", model="worker", system_snapshot="")
    for i in range(8):
        store.append_message("s", role="user", content=f"历史消息 {i}")
        store.append_message("s", role="assistant", content=f"历史回答 {i}")
    model = _OverflowThenOkModel()
    loop = AgentLoop(store=store, bus=EventBus(), sandbox=_FakeSandbox(), broker=None,
                     model=model, verifier=_NoCmdVerifier(), config=LoopConfig(compaction=True))
    async for _ in loop.run("g", "s"):
        pass
    assert model.calls >= 2, "溢出后应压缩并重试(第二次成功)"
    msgs = store.get_messages("s")
    assert any("早期对话摘要" in m["content"] for m in msgs), "应有摘要行"
    store.close()
