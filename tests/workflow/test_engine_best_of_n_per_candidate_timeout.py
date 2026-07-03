from __future__ import annotations

import asyncio
import time

import pytest

from argos.core.models import ModelTier
from argos.workflow.spec import parse_spec
from argos.workflow.engine import WorkflowEngine


class _HangOneFactory:
    def __init__(self, *, normal_delay_s: float = 0.02, hang_idx: int = 1):
        self._normal_delay_s = normal_delay_s
        self._hang_idx = hang_idx
        self._call_count = 0

    def __call__(self, profile=None):
        outer = self
        outer._call_count += 1
        this_idx = outer._call_count - 1
        hang_this_one = (this_idx == outer._hang_idx)

        class _M:
            tier = ModelTier(name="worker", model="m", base_url="memory://", max_tokens=64)
            async def stream(self, messages, *, system, system_dynamic=None):
                if hang_this_one:
                    await asyncio.sleep(60)
                else:
                    await asyncio.sleep(outer._normal_delay_s)
                    yield "ok"
        return _M()


async def _consume(engine: WorkflowEngine, spec, *, outer_timeout_s: float = 5.0):
    return await asyncio.wait_for(_drain(engine, spec), timeout=outer_timeout_s)


async def _drain(engine: WorkflowEngine, spec):
    async for _ev in engine.run(spec):
        pass


@pytest.mark.asyncio
async def test_per_candidate_timeout_kills_hang_candidate(tmp_path):
    factory = _HangOneFactory(normal_delay_s=0.02, hang_idx=1)
    spec = parse_spec({
        "name": "t", "description": "",
        "stages": [{
            "id": "b", "op": "best_of_n", "n": 3, "cap": 3,
            "stagger_s": 0,
            "per_candidate_timeout_s": 0.3,
            "agent": {"prompt": "x", "tool_scope": "read"},
        }],
    })
    engine = WorkflowEngine.for_test(workspace=tmp_path, model_factory=factory)
    t0 = time.monotonic()
    await _consume(engine, spec, outer_timeout_s=5.0)
    elapsed = time.monotonic() - t0

    assert elapsed < 4.0, (
        f"hang 候选应在 per_candidate_timeout_s(0.3s)内被取消,"
        f"整 stage 不应被它拖死;实际 {elapsed:.2f}s"
    )
    result = engine.last_result
    assert result is not None and result.stages, "engine 应返 last_result"
    stage = result.stages[0]
    assert len(stage.candidates) == 3, f"应 3 候选,实际 {len(stage.candidates)}"
    hang_cand = next(c for c in stage.candidates if c.agent_id.endswith("#c1"))
    assert hang_cand.ok is False, (
        f"hang 候选(c1)应 ok=False,实际 {hang_cand.ok}"
    )
    assert "timeout" in (hang_cand.error or "").lower(), (
        f"hang 候选 error 应含 'timeout',实际 {hang_cand.error!r}"
    )
    assert stage.results, "best_of_n 必须有 winner"
    winner = stage.results[0]
    assert not winner.agent_id.endswith("#c1"), (
        f"winner 不应是 hang 候选 c1(verdict='unverifiable' 是取消的,"
        f"不该被选);实际 winner={winner.agent_id} verdict={winner.verdict}"
    )


@pytest.mark.asyncio
async def test_per_candidate_timeout_field_is_optional_with_safe_default(tmp_path):
    class _NormalFactory:
        def __init__(self):
            self._n = 0
        def __call__(self, profile=None):
            self._n += 1
            class _M:
                tier = ModelTier(name="worker", model="m", base_url="memory://", max_tokens=64)
                async def stream(self, messages, *, system, system_dynamic=None):
                    await asyncio.sleep(0.01)
                    yield "ok"
            return _M()

    factory = _NormalFactory()
    spec = parse_spec({
        "name": "t", "description": "",
        "stages": [{
            "id": "b", "op": "best_of_n", "n": 2, "cap": 2,
            "stagger_s": 0,
            "agent": {"prompt": "x", "tool_scope": "read"},
        }],
    })
    assert spec.stages[0].per_candidate_timeout_s >= 600, (
        f"默认 timeout 应 ≥ 600s(docker verify 600s + 余量),"
        f"实际 {spec.stages[0].per_candidate_timeout_s}"
    )
    engine = WorkflowEngine.for_test(workspace=tmp_path, model_factory=factory)
    await _consume(engine, spec, outer_timeout_s=5.0)
    result = engine.last_result
    assert result is not None and result.stages
    assert len(result.stages[0].candidates) == 2
