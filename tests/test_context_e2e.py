"""#12 Context 可视化:T5 core/loop.py 主动压缩集成(契约 §12;spec §9)。

5 测试覆盖阈值触发 / 跳过 / 幂等 / override 一次性 / 既有 error 路径不破。"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import pytest

from argos.context.threshold import LastCompactedAt
from argos.core.loop import AgentLoop, LoopConfig
from argos.tui.events import CompactedEvent


@dataclass
class _FakeTier:
    context_window: int = 100_000


@dataclass
class _FakeModel:
    tier: _FakeTier
    last_usage: dict = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.last_usage is None:
            self.last_usage = {"input_tokens": 0, "output_tokens": 0,
                                "cache_read": 0, "cache_creation": 0}


class _FakeStore:
    def __init__(self, n_msgs: int = 0) -> None:
        self.msgs: list[dict] = [
            {"role": "user" if i % 2 == 0 else "assistant",
             "content": f"msg {i} " + "x" * 100}
            for i in range(n_msgs)
        ]
        self.compact_count = 0
        self.get_messages_calls = 0

    def get_messages(self, _sid: str) -> list[dict]:
        self.get_messages_calls += 1
        return list(self.msgs)

    def compact_messages(self, _sid: str, *, keep_recent: int = 5) -> None:
        self.compact_count += 1
        # 模拟 store:keep_recent 条不变,其它的折叠成 1 条 summary
        recent = self.msgs[-keep_recent:] if self.msgs else []
        summary = {"role": "user",
                    "content": "(早期对话摘要)" + " / ".join(
                        (m.get("content") or "")[:60] for m in self.msgs[:-keep_recent])}
        self.msgs = ([summary] if summary["content"] else []) + recent


def _loop(*, used: int = 0, window: int = 100_000, threshold: float = 0.8,
          compaction: bool = True, fail_count: int = 0) -> tuple[AgentLoop, _FakeStore]:
    cfg = LoopConfig(max_steps=2, compaction=compaction, compact_threshold=threshold)
    model = _FakeModel(_FakeTier(context_window=window),
                        last_usage={"input_tokens": used, "output_tokens": 0,
                                    "cache_read": 0, "cache_creation": 0})
    store = _FakeStore(n_msgs=20)
    loop = AgentLoop(
        store=store, bus=None, sandbox=None, broker=None,  # type: ignore[arg-type]
        model=model, verifier=None, config=cfg,
    )
    loop._fail_count = fail_count
    return loop, store


@pytest.mark.asyncio
async def test_proactive_compact_triggers_above_threshold():
    """85% 占用 → 触发 yield CompactedEvent(triggered_by=proactive, before=85k, after<85k)。"""
    loop, store = _loop(used=85_000, window=100_000, threshold=0.8)
    events = [ev async for ev in loop._maybe_proactive_compact("s", 0)]
    compacted = [e for e in events if isinstance(e, CompactedEvent)]
    assert len(compacted) == 1
    assert compacted[0].triggered_by == "proactive"
    assert compacted[0].before == 85_000
    assert compacted[0].after < 85_000
    assert compacted[0].reduction_pct > 0
    # store.compact_messages 真调了
    assert store.compact_count == 1


@pytest.mark.asyncio
async def test_proactive_compact_skips_when_compaction_disabled():
    """compaction=False → 不触发(spec D17 等价 compact_threshold=0)。"""
    loop, store = _loop(used=85_000, window=100_000, threshold=0.8, compaction=False)
    events = [ev async for ev in loop._maybe_proactive_compact("s", 0)]
    assert events == []
    assert store.compact_count == 0


@pytest.mark.asyncio
async def test_proactive_compact_skips_when_recent_verify_failed():
    """fail_count=1 → 不触发(spec §8.1 跳过条件 5,等 verify 收敛)。"""
    loop, store = _loop(used=85_000, window=100_000, threshold=0.8, fail_count=1)
    events = [ev async for ev in loop._maybe_proactive_compact("s", 0)]
    assert events == []
    assert store.compact_count == 0


@pytest.mark.asyncio
async def test_proactive_compact_idempotent_5pct_buffer():
    """5% buffer 幂等(spec D9):第二次 used 在 buffer 内不触发。"""
    loop, store = _loop(used=85_000, window=100_000, threshold=0.8)
    # 第一次压触发
    ev1 = [e async for e in loop._maybe_proactive_compact("s", 0)]
    assert len([e for e in ev1 if isinstance(e, CompactedEvent)]) == 1
    # 第二次 used=85_001(window 100k, 5% buffer=5k;85_001 <= 85_000+5_000=90_000)→ 不触发
    # 但 model.last_usage 已被 store 改动?不,last_usage 是 model 的属性,store 改的是 msgs
    # 模拟 used 涨到 86_000 仍在 buffer 内
    loop._model.last_usage["input_tokens"] = 86_000
    ev2 = [e async for e in loop._maybe_proactive_compact("s", 1)]
    assert ev2 == []   # 5% buffer 内不重压
    assert store.compact_count == 1


@pytest.mark.asyncio
async def test_proactive_compact_messages_override_consumed():
    """压后 _messages_override 一次性;下次取清空(spec D16)。"""
    loop, store = _loop(used=85_000, window=100_000, threshold=0.8)
    ev1 = [e async for e in loop._maybe_proactive_compact("s", 0)]
    assert len([e for e in ev1 if isinstance(e, CompactedEvent)]) == 1
    # 压后 override 已设置
    assert loop._messages_override is not None
    assert len(loop._messages_override) < 20  # 压后变少
    # 模拟 while 顶部消费一次
    if loop._messages_override is not None:
        consumed = loop._messages_override
        loop._messages_override = None
    assert consumed is not None
    assert loop._messages_override is None  # 清空


@pytest.mark.asyncio
async def test_proactive_compact_old_loopconfig_no_threshold_attr():
    """老 LoopConfig 没 compact_threshold 字段 → getattr 兜底 0.8,不破。"""
    cfg = LoopConfig(max_steps=2)  # 无 compact_threshold
    model = _FakeModel(_FakeTier(context_window=100_000),
                        last_usage={"input_tokens": 90_000, "output_tokens": 0,
                                    "cache_read": 0, "cache_creation": 0})
    store = _FakeStore(n_msgs=20)
    loop = AgentLoop(
        store=store, bus=None, sandbox=None, broker=None,  # type: ignore[arg-type]
        model=model, verifier=None, config=cfg,
    )
    # 既有 cfg.compact_threshold 走 default 0.8,getattr 兜底同值
    events = [ev async for ev in loop._maybe_proactive_compact("s", 0)]
    compacted = [e for e in events if isinstance(e, CompactedEvent)]
    assert len(compacted) == 1   # 90% > 80% 触发
    assert compacted[0].triggered_by == "proactive"
