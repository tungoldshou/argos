"""best_of_n N 候选 thundering herd 防护(M3 限流真用户必踩)。

契约:
  - effective_cap = min(n, stage.cap) → N=3 cap=4(默认)应降到 2,不能 3 候选同帧打 API
  - 候选 i 在启动前 sleep(idx * stagger_s) → 错峰开打,不平摊在同一瞬

测试用 timing-recording factory 验:
  - 3 个候选的 start_time 间隔 ≥ stagger_s(错峰存在)
  - 同一时刻 in-flight 的候选数 ≤ effective_cap
"""
from __future__ import annotations

import asyncio
import time

import pytest

from argos_agent.core.models import ModelTier
from argos_agent.workflow.spec import parse_spec
from argos_agent.workflow.engine import WorkflowEngine


class _TimedFactory:
    """记录每个候选的**首次**stream 启动时间 + 实时并发(用来验 stagger 和 cap)。"""
    def __init__(self, *, stream_delay_s: float = 0.05):
        self._stream_delay_s = stream_delay_s
        self.candidate_start_times: list[float] = []  # 一个 candidate(一次 factory call)记一次
        self._active = 0
        self.peak_concurrency = 0
        self._lock = asyncio.Lock()

    def __call__(self, profile=None):
        outer = self
        class _M:
            # 每个 factory call 返回**新类**,_first 是该类(=该候选)的属性,仅首次置 True
            _first = False
            tier = ModelTier(name="worker", model="m", base_url="memory://", max_tokens=64)
            async def stream(self, messages, *, system, system_dynamic=None):
                if not _M._first:
                    _M._first = True
                    async with outer._lock:
                        outer.candidate_start_times.append(time.monotonic())
                async with outer._lock:
                    outer._active += 1
                    outer.peak_concurrency = max(outer.peak_concurrency, outer._active)
                try:
                    await asyncio.sleep(outer._stream_delay_s)
                    yield "ok"
                finally:
                    async with outer._lock:
                        outer._active -= 1
        return _M()


@pytest.mark.asyncio
async def test_best_of_n_staggers_candidate_starts(tmp_path):
    """N=3 候选不能同帧启动(c0 < c1 < c2,间隔 ≥ stagger_s)。
    真用户场景:agnes-flash 单 key 严 QPS,3 同帧打 → 全 429;错峰后每个候选
    能拿到完整 QPS 配额。"""
    factory = _TimedFactory(stream_delay_s=0.05)
    spec = parse_spec({
        "name": "t", "description": "",
        "stages": [{
            "id": "b", "op": "best_of_n", "n": 3, "cap": 2,
            "agent": {"prompt": "x", "tool_scope": "read"},
        }],
    })
    engine = WorkflowEngine.for_test(workspace=tmp_path, model_factory=factory)
    [ev async for ev in engine.run(spec)]

    assert len(factory.candidate_start_times) == 3, (
        f"应启动 3 个候选(每个候选记一次首次 stream),"
        f"实际 {len(factory.candidate_start_times)}"
    )
    s0, s1, s2 = factory.candidate_start_times
    # 错峰:c1 比 c0 晚 ≥ stagger_s(默认 0.5s),c2 比 c1 晚 ≥ stagger_s
    assert s1 - s0 >= 0.4, (
        f"c1 应比 c0 晚 ≥ 0.4s(stagger),实际差 {s1 - s0:.3f}s "
        f"(start_times={factory.candidate_start_times})"
    )
    assert s2 - s1 >= 0.4, (
        f"c2 应比 c1 晚 ≥ 0.4s(stagger),实际差 {s2 - s1:.3f}s "
        f"(start_times={factory.candidate_start_times})"
    )


@pytest.mark.asyncio
async def test_best_of_n_caps_concurrency_below_n(tmp_path):
    """effective_cap = min(n=3, stage.cap=2) = 2 → 同帧 in-flight 候选 ≤ 2。
    防止 N=3 cap=4(默认上限)时 3 候选并发同打撞 QPS。"""
    factory = _TimedFactory(stream_delay_s=0.10)  # 延迟稍长,让并发窗口清晰
    spec = parse_spec({
        "name": "t", "description": "",
        "stages": [{
            "id": "b", "op": "best_of_n", "n": 3, "cap": 2,
            "agent": {"prompt": "x", "tool_scope": "read"},
        }],
    })
    engine = WorkflowEngine.for_test(workspace=tmp_path, model_factory=factory)
    [ev async for ev in engine.run(spec)]

    assert factory.peak_concurrency <= 2, (
        f"peak in-flight 应 ≤ effective_cap(2),实际 {factory.peak_concurrency}。"
        f"start_times={factory.candidate_start_times}"
    )
    # 3 候选全启动(只是排队)
    assert len(factory.candidate_start_times) == 3
