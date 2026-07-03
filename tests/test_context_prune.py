from __future__ import annotations

from dataclasses import dataclass

import pytest

from argos.context.prune import CoreKeep, PruneResult, prune_messages
from argos.context.threshold import PRECOMPACT_FLOOR, safe_compact_threshold
from argos.core.honesty import trust_passed_after_compaction
from argos.core.loop import AgentLoop, LoopConfig
from argos.core.verify_gate import Verdict
from argos.memory.store import ArgosStore
from argos.sandbox.backend import ExecResult
from argos.tui.events import (
    CompactedEvent, EventBus, PrunedEvent, VerifyVerdict,
    deserialize_event, serialize_event,
)




def _thread_with_stale_tools(n_pairs: int = 10) -> list[dict]:
    msgs: list[dict] = [{"role": "user", "content": "任务目标:实现 X"}]
    for i in range(n_pairs):
        msgs.append({"role": "assistant", "content": f"我来做第{i}步"})
        msgs.append({"role": "user", "content": f"[执行结果]\n" + "输出" * 200})
    msgs.append({"role": "assistant", "content": "最近回答"})
    msgs.append({"role": "user", "content": "最近反馈"})
    return msgs


def test_core_keep_survives_prune():
    msgs = _thread_with_stale_tools()
    msgs.insert(5, {"role": "user", "content": "请确保 pytest -q 通过"})
    res = prune_messages(msgs, core=CoreKeep(recent_turns=4, verify_cmd="pytest -q"),
                         aggressiveness=0.5)
    assert isinstance(res, PruneResult)
    assert res.messages[0]["content"] == "任务目标:实现 X"
    assert res.messages[-1]["content"] == "最近反馈"
    assert res.messages[-2]["content"] == "最近回答"
    assert any(m["content"] == "请确保 pytest -q 通过" for m in res.messages)
    assert len(res.messages) == len(msgs)


def test_core_keep_survives_compaction_via_anchor():
    loop = _mk_loop(ArgosStore(db_path=":memory:"), _DoneModel(used=0), _NoCmdVerifier())
    loop._current_goal = "任务目标:实现 X"
    folded = [{"role": "user", "content": "(早期对话摘要)任务目标 / 第0步 / ..."},
              {"role": "assistant", "content": "最近回答"}]
    out = loop._anchor_core_messages(folded, loop._current_goal)
    assert out[0]["content"] == "任务目标:实现 X"
    present = [{"role": "user", "content": "任务目标:实现 X"}]
    assert loop._anchor_core_messages(present, "任务目标:实现 X") == present




def test_stale_tool_output_pruned():
    msgs = _thread_with_stale_tools()
    res = prune_messages(msgs, core=CoreKeep(recent_turns=4), aggressiveness=0.5)
    folded = [m for m in res.messages if m["content"] == "[已修剪:过期工具输出]"]
    assert res.removed >= 1
    assert folded, "过期工具输出应被折叠成短桩"
    assert res.removed_tokens > 0


def test_prune_disabled_when_aggressiveness_zero():
    msgs = _thread_with_stale_tools()
    res = prune_messages(msgs, core=CoreKeep(recent_turns=4), aggressiveness=0.0)
    assert res.removed == 0
    assert res.messages == msgs


@pytest.mark.asyncio
async def test_prune_happens_before_compaction_in_loop():
    store = ArgosStore(db_path=":memory:")
    store.ensure_session("s", title="t", model="worker", system_snapshot="")
    for i in range(8):
        store.append_message("s", role="assistant", content=f"做第{i}步")
        store.append_message("s", role="user", content="[执行结果]\n" + "x" * 400)
    model = _DoneModel(used=10_000)
    loop = _mk_loop(store, model, _NoCmdVerifier(),
                    max_steps=2, compact_threshold=0.8, prune_aggressiveness=0.5)
    events = [ev async for ev in loop.run("目标X", "s")]
    assert any(isinstance(e, PrunedEvent) for e in events), "应发出修剪事件"
    assert not any(isinstance(e, CompactedEvent) for e in events), "低占用不应整体压缩"




def test_safe_compact_threshold_floor():
    assert safe_compact_threshold(0.3) == PRECOMPACT_FLOOR == 0.5
    assert safe_compact_threshold(0.4) == 0.5
    assert safe_compact_threshold(0.0) == 0.0
    assert safe_compact_threshold(-1.0) == 0.0
    assert safe_compact_threshold(0.8) == 0.8


@pytest.mark.asyncio
async def test_no_precompact_at_30_40_pct():
    store = ArgosStore(db_path=":memory:")
    store.ensure_session("s", title="t", model="worker", system_snapshot="")
    for i in range(12):
        store.append_message("s", role="user", content=f"历史{i}")
    model = _DoneModel(used=35_000)   # 35% of 100k
    loop = _mk_loop(store, model, _NoCmdVerifier(), compact_threshold=0.35)
    events = [ev async for ev in loop._maybe_proactive_compact("s", 0)]
    assert events == [], "35% < 钳后的 50% 下限 → 绝不提前整体压"


@pytest.mark.asyncio
async def test_compaction_triggers_at_high_watermark():
    store = ArgosStore(db_path=":memory:")
    store.ensure_session("s", title="t", model="worker", system_snapshot="")
    for i in range(12):
        store.append_message("s", role="user", content=f"历史{i}")
    model = _DoneModel(used=85_000)
    loop = _mk_loop(store, model, _NoCmdVerifier(), compact_threshold=0.8)
    events = [ev async for ev in loop._maybe_proactive_compact("s", 0)]
    assert any(isinstance(e, CompactedEvent) for e in events)
    assert loop._compacted is True
    assert loop._reverified_since_compact is False




def test_trust_passed_after_compaction_helper():
    assert trust_passed_after_compaction(compacted=False, reverified=False) is True
    assert trust_passed_after_compaction(compacted=False, reverified=True) is True
    assert trust_passed_after_compaction(compacted=True, reverified=True) is True
    assert trust_passed_after_compaction(compacted=True, reverified=False) is False


@pytest.mark.asyncio
async def test_no_passed_without_reverify_after_compaction():
    store = ArgosStore(db_path=":memory:")
    store.ensure_session("s", title="t", model="worker", system_snapshot="")
    for i in range(12):
        store.append_message("s", role="user", content=f"历史{i} " + "y" * 50)
    model = _ImplementingDoneModel(used=90_000)
    loop = _mk_loop(store, model, _NoCmdVerifier(), max_steps=3, compact_threshold=0.8)
    events = [ev async for ev in loop.run("目标X", "s")]
    assert loop._compacted is True, "应发生过压缩"
    assert any(isinstance(e, CompactedEvent) for e in events)
    verdicts = [e.verdict for e in events if isinstance(e, VerifyVerdict)]
    assert verdicts, "完成时应真重跑过 verify"
    assert all(v.status != "passed" for v in verdicts), "无机检命令绝不标 passed"
    assert loop._reverified_since_compact is True, "压缩后确实重跑了 verify"




def test_pruned_event_roundtrip():
    ev = PrunedEvent(before=100, after=40, removed=3, reduction_pct=0.6,
                     aggressiveness=0.5, session_id="s1")
    back = deserialize_event(serialize_event(ev))
    assert back == ev


def test_compacted_event_roundtrip():
    ev = CompactedEvent(before=100, after=30, reduction_pct=0.7,
                        triggered_by="proactive", session_id="s1")
    back = deserialize_event(serialize_event(ev))
    assert back == ev




@dataclass
class _Tier:
    context_window: int = 100_000
    name: str = "default"
    model: str = "fake-model"


class _DoneModel:
    def __init__(self, used: int) -> None:
        self.tier = _Tier()
        self.last_usage = {"input_tokens": used, "output_tokens": 0,
                           "cache_read": 0, "cache_creation": 0}

    async def stream(self, messages, *, system, system_dynamic=None):
        for ch in "完成。":
            yield ch


class _ImplementingDoneModel(_DoneModel):
    def __init__(self, used: int) -> None:
        super().__init__(used)
        self._i = 0

    async def stream(self, messages, *, system, system_dynamic=None):
        scripts = ["```python\nwrite_file('a.txt', 'x')\n```", "完成。"]
        t = scripts[min(self._i, len(scripts) - 1)]
        self._i += 1
        for ch in t:
            yield ch


class _FakeSandbox:
    def spawn(self, *, workspace, namespace, allow_workflow=True, read_only=False): ...
    def exec_code(self, code): return ExecResult(stdout="", value_repr="", exc="")
    def close(self): ...


class _NoCmdVerifier:
    def verify(self, verify_cmd, *, attempts=1):
        return Verdict.unverifiable(detail="(无)", tampered=[], attempts=attempts)


def _mk_loop(store, model, verifier, *, max_steps: int = 2,
             compact_threshold: float = 0.8, prune_aggressiveness: float = 0.5) -> AgentLoop:
    cfg = LoopConfig(max_steps=max_steps, compaction=True,
                     compact_threshold=compact_threshold,
                     prune_aggressiveness=prune_aggressiveness)
    return AgentLoop(store=store, bus=EventBus(), sandbox=_FakeSandbox(), broker=None,
                     model=model, verifier=verifier, config=cfg)
