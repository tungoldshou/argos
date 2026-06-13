"""context rot 三层防线测试(spec 2026-06-07):
(a) 不可丢核心在修剪/压缩后原样存活;
(b) 过期工具输出在整体压缩触发之前就被修剪;
(c) 整体压缩只在高水位触发,绝不在 30–40% 提前触发;
(d) 发生过压缩后,任务不经重新 verify 不会被标 passed;
(e) 修剪/压缩事件都正确发出(并能序列化往返)。
"""
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


# ────────────────────────── (a) 不可丢核心存活 ──────────────────────────


def _thread_with_stale_tools(n_pairs: int = 10) -> list[dict]:
    msgs: list[dict] = [{"role": "user", "content": "任务目标:实现 X"}]  # 核心:目标
    for i in range(n_pairs):
        msgs.append({"role": "assistant", "content": f"我来做第{i}步"})
        msgs.append({"role": "user", "content": f"[执行结果]\n" + "输出" * 200})  # 过期工具输出
    msgs.append({"role": "assistant", "content": "最近回答"})
    msgs.append({"role": "user", "content": "最近反馈"})
    return msgs


def test_core_keep_survives_prune():
    """目标(第0条)+ 最近N条 + 含 verify_cmd 的消息,修剪后原样保留。"""
    msgs = _thread_with_stale_tools()
    msgs.insert(5, {"role": "user", "content": "请确保 pytest -q 通过"})  # 含 verify_cmd
    res = prune_messages(msgs, core=CoreKeep(recent_turns=4, verify_cmd="pytest -q"),
                         aggressiveness=0.5)
    assert isinstance(res, PruneResult)
    # 目标原样
    assert res.messages[0]["content"] == "任务目标:实现 X"
    # 最近 4 条原样
    assert res.messages[-1]["content"] == "最近反馈"
    assert res.messages[-2]["content"] == "最近回答"
    # 含 verify_cmd 的消息原样(没被折叠)
    assert any(m["content"] == "请确保 pytest -q 通过" for m in res.messages)
    # 条数/顺序不变(折叠而非删除)
    assert len(res.messages) == len(msgs)


def test_core_keep_survives_compaction_via_anchor():
    """整体压缩可能把目标折进摘要;loop 的核心锚把它原样钉回。"""
    loop = _mk_loop(ArgosStore(db_path=":memory:"), _DoneModel(used=0), _NoCmdVerifier())
    loop._current_goal = "任务目标:实现 X"
    # 模拟压缩后 reload 的线程:目标已被折进摘要、不在场
    folded = [{"role": "user", "content": "(早期对话摘要)任务目标 / 第0步 / ..."},
              {"role": "assistant", "content": "最近回答"}]
    out = loop._anchor_core_messages(folded, loop._current_goal)
    assert out[0]["content"] == "任务目标:实现 X"   # 原样钉回最前
    # 目标已在场时不重复
    present = [{"role": "user", "content": "任务目标:实现 X"}]
    assert loop._anchor_core_messages(present, "任务目标:实现 X") == present


# ────────────────────────── (b) 过期工具输出先被修剪 ──────────────────────────


def test_stale_tool_output_pruned():
    msgs = _thread_with_stale_tools()
    res = prune_messages(msgs, core=CoreKeep(recent_turns=4), aggressiveness=0.5)
    folded = [m for m in res.messages if m["content"] == "[已修剪:过期工具输出]"]
    assert res.removed >= 1
    assert folded, "过期工具输出应被折叠成短桩"
    assert res.removed_tokens > 0   # 真回收了 token


def test_prune_disabled_when_aggressiveness_zero():
    msgs = _thread_with_stale_tools()
    res = prune_messages(msgs, core=CoreKeep(recent_turns=4), aggressiveness=0.0)
    assert res.removed == 0
    assert res.messages == msgs


@pytest.mark.asyncio
async def test_prune_happens_before_compaction_in_loop():
    """低占用(不到整体压缩阈值)下,修剪照样发生、整体压缩不发生 —— 优先修剪。"""
    store = ArgosStore(db_path=":memory:")
    store.ensure_session("s", title="t", model="worker", system_snapshot="")
    # 预置一串带过期工具输出的历史(>recent_turns,中段可折叠)
    for i in range(8):
        store.append_message("s", role="assistant", content=f"做第{i}步")
        store.append_message("s", role="user", content="[执行结果]\n" + "x" * 400)
    model = _DoneModel(used=10_000)   # window 100k → 10% 占用,远低于整体压缩阈值
    loop = _mk_loop(store, model, _NoCmdVerifier(),
                    max_steps=2, compact_threshold=0.8, prune_aggressiveness=0.5)
    events = [ev async for ev in loop.run("目标X", "s")]
    assert any(isinstance(e, PrunedEvent) for e in events), "应发出修剪事件"
    assert not any(isinstance(e, CompactedEvent) for e in events), "低占用不应整体压缩"


# ────────────────────────── (c) 整体压缩只在高水位 ──────────────────────────


def test_safe_compact_threshold_floor():
    assert safe_compact_threshold(0.3) == PRECOMPACT_FLOOR == 0.5   # 30% 被抬到下限
    assert safe_compact_threshold(0.4) == 0.5                       # 40% 被抬到下限
    assert safe_compact_threshold(0.0) == 0.0                       # 0 = 关闭,保留
    assert safe_compact_threshold(-1.0) == 0.0
    assert safe_compact_threshold(0.8) == 0.8                       # 高位原样


@pytest.mark.asyncio
async def test_no_precompact_at_30_40_pct():
    """配置成 35% 也不会在 35% 提前整体压(被钳到 50% 下限)。"""
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
    """85% 占用 → 整体压缩照常触发(高水位安全网仍在)。"""
    store = ArgosStore(db_path=":memory:")
    store.ensure_session("s", title="t", model="worker", system_snapshot="")
    for i in range(12):
        store.append_message("s", role="user", content=f"历史{i}")
    model = _DoneModel(used=85_000)
    loop = _mk_loop(store, model, _NoCmdVerifier(), compact_threshold=0.8)
    events = [ev async for ev in loop._maybe_proactive_compact("s", 0)]
    assert any(isinstance(e, CompactedEvent) for e in events)
    assert loop._compacted is True
    assert loop._reverified_since_compact is False   # 压缩后尚未重验


# ────────────────────────── (d) 压缩后不经重验不标 passed ──────────────────────────


def test_trust_passed_after_compaction_helper():
    assert trust_passed_after_compaction(compacted=False, reverified=False) is True
    assert trust_passed_after_compaction(compacted=False, reverified=True) is True
    assert trust_passed_after_compaction(compacted=True, reverified=True) is True
    assert trust_passed_after_compaction(compacted=True, reverified=False) is False


@pytest.mark.asyncio
async def test_no_passed_without_reverify_after_compaction():
    """压缩发生后,无机检命令的任务完成只能是 unverifiable(绝不假装 passed),
    且 verify 在压缩之后真重跑过(_reverified_since_compact 置回 True)。"""
    store = ArgosStore(db_path=":memory:")
    store.ensure_session("s", title="t", model="worker", system_snapshot="")
    for i in range(12):
        store.append_message("s", role="user", content=f"历史{i} " + "y" * 50)
    model = _DoneModel(used=90_000)   # 触发整体压缩
    loop = _mk_loop(store, model, _NoCmdVerifier(), max_steps=3, compact_threshold=0.8)
    events = [ev async for ev in loop.run("目标X", "s")]
    assert loop._compacted is True, "应发生过压缩"
    assert any(isinstance(e, CompactedEvent) for e in events)
    verdicts = [e.verdict for e in events if isinstance(e, VerifyVerdict)]
    assert verdicts, "完成时应真重跑过 verify"
    assert all(v.status != "passed" for v in verdicts), "无机检命令绝不标 passed"
    assert loop._reverified_since_compact is True, "压缩后确实重跑了 verify"


# ────────────────────────── (e) 事件序列化往返 ──────────────────────────


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


# ────────────────────────── 测试用 fakes ──────────────────────────


@dataclass
class _Tier:
    context_window: int = 100_000
    name: str = "default"
    model: str = "fake-model"


class _DoneModel:
    """高占用以触发整体压缩;stream 吐一句完成、无代码块 → loop 进 verify 收尾。"""
    def __init__(self, used: int) -> None:
        self.tier = _Tier()
        self.last_usage = {"input_tokens": used, "output_tokens": 0,
                           "cache_read": 0, "cache_creation": 0}

    async def stream(self, messages, *, system, system_dynamic=None):
        for ch in "完成。":
            yield ch


class _FakeSandbox:
    def spawn(self, *, workspace, namespace, allow_workflow=True, read_only=False): ...
    def exec_code(self, code): return ExecResult(stdout="", value_repr="", exc="")
    def close(self): ...


class _NoCmdVerifier:
    """无 verify_cmd → 三态 unverifiable(无测任务的诚实非阻塞完成由 harness 据 None 判定)。"""
    def verify(self, verify_cmd, *, attempts=1):
        return Verdict.unverifiable(detail="(无)", tampered=[], attempts=attempts)


def _mk_loop(store, model, verifier, *, max_steps: int = 2,
             compact_threshold: float = 0.8, prune_aggressiveness: float = 0.5) -> AgentLoop:
    cfg = LoopConfig(max_steps=max_steps, compaction=True,
                     compact_threshold=compact_threshold,
                     prune_aggressiveness=prune_aggressiveness)
    return AgentLoop(store=store, bus=EventBus(), sandbox=_FakeSandbox(), broker=None,
                     model=model, verifier=verifier, config=cfg)
