from __future__ import annotations

import asyncio
import time

import pytest

from argos.core.models import ModelTier
from argos.workflow.spec import parse_spec
from argos.workflow.engine import WorkflowEngine


class _TimedFactory:
    def __init__(self, *, stream_delay_s: float = 0.05):
        self._stream_delay_s = stream_delay_s
        self.candidate_start_times: list[float] = []
        self._active = 0
        self.peak_concurrency = 0
        self._lock = asyncio.Lock()

    def __call__(self, profile=None):
        outer = self
        class _M:
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
    factory = _TimedFactory(stream_delay_s=0.10)
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
    assert len(factory.candidate_start_times) == 3
