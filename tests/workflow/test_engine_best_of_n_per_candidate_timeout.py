"""best_of_n per_candidate_timeout_s:候选 hang 死时不让它拖垮整个 bench。

bug 复现:M3 / 严 QPS 模型偶尔 stream 不返(不是 429,不是 5xx,就是没响应)。
asyncio.gather 在 _run_best_of_n 里等永远 → 整个 bench 永远卡住。
修(本次):Stage 加 per_candidate_timeout_s 字段,_run_best_of_n 包
asyncio.wait_for(coro, timeout=per_candidate_timeout_s);超时 → 候选标
verdict='unverifiable' + error 含 'timeout',gather 不被它拖。

契约:
  - per_candidate_timeout_s 是 Stage 字段(spec.py),parse_spec 接受
  - hang 候选在 ~timeout 内被取消 → AgentResult.ok=False,verdict='unverifiable'
  - 其他候选照常完成 → best_of_n winner 仍能挑出
  - gather 总时长 < timeout + 小 overhead(防 hang 拖死)
"""
from __future__ import annotations

import asyncio
import time

import pytest

from argos_agent.core.models import ModelTier
from argos_agent.workflow.spec import parse_spec
from argos_agent.workflow.engine import WorkflowEngine


class _HangOneFactory:
    """第 hang_idx 次 call 的 stream 永不返,其他 call 正常 yield 'ok' 一次。

    call_count 是 model_factory 调用次数,每个候选触发 1 次。
    """
    def __init__(self, *, normal_delay_s: float = 0.02, hang_idx: int = 1):
        self._normal_delay_s = normal_delay_s
        self._hang_idx = hang_idx  # 0-based;默认 1(第 2 个候选)
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
                    # 真 hang 死:不 yield,睡眠足够久使 gather 一定被 timeout 救
                    await asyncio.sleep(60)
                else:
                    await asyncio.sleep(outer._normal_delay_s)
                    yield "ok"
        return _M()


async def _consume(engine: WorkflowEngine, spec, *, outer_timeout_s: float = 5.0):
    """驱动 engine.run() 直到返(外层 watchdog 防止 hang 候选拖死测试本身)。

    outer_timeout_s 是"engine.run() 应当在此时间内自然返回"的上限;若
    engine.run() 未在此时间内返(说明 hang 候选没被取消,整 stage 被拖死),
    抛 TimeoutError,测试主断言 fail。
    """
    return await asyncio.wait_for(_drain(engine, spec), timeout=outer_timeout_s)


async def _drain(engine: WorkflowEngine, spec):
    async for _ev in engine.run(spec):
        pass


@pytest.mark.asyncio
async def test_per_candidate_timeout_kills_hang_candidate(tmp_path):
    """1 个候选 hang 死(永不返 stream),其他候选正常;gather 在 timeout 内返。

    行为:
      - hang 候选在 ~timeout 内被取消,AgentResult.ok=False
      - hang 候选的 error 含 'timeout' 字样(可观测)
      - 其他候选照常返回
      - best_of_n winner 仍是 passed 候选(非 hang)
      - 总耗时 < timeout + 1s overhead
    """
    factory = _HangOneFactory(normal_delay_s=0.02, hang_idx=1)
    spec = parse_spec({
        "name": "t", "description": "",
        "stages": [{
            "id": "b", "op": "best_of_n", "n": 3, "cap": 3,
            "stagger_s": 0,  # 不错峰,3 候选同帧启动,加速测试
            "per_candidate_timeout_s": 0.3,  # 0.3s 超时,测试快
            "agent": {"prompt": "x", "tool_scope": "read"},
        }],
    })
    engine = WorkflowEngine.for_test(workspace=tmp_path, model_factory=factory)
    t0 = time.monotonic()
    await _consume(engine, spec, outer_timeout_s=5.0)
    elapsed = time.monotonic() - t0

    # 1) 主断言:整 stage 在 timeout + 合理 overhead 内返
    assert elapsed < 2.0, (
        f"hang 候选应在 per_candidate_timeout_s(0.3s)内被取消,"
        f"整 stage 不应被它拖死;实际 {elapsed:.2f}s"
    )
    # 2) hang 候选被标 ok=False,error 含 'timeout'(可观测,可排错)
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
    # 3) winner 不是 hang 候选(诚实:timeout 候选不冒充 winner)
    assert stage.results, "best_of_n 必须有 winner"
    winner = stage.results[0]
    assert not winner.agent_id.endswith("#c1"), (
        f"winner 不应是 hang 候选 c1(verdict='unverifiable' 是取消的,"
        f"不该被选);实际 winner={winner.agent_id} verdict={winner.verdict}"
    )


@pytest.mark.asyncio
async def test_per_candidate_timeout_field_is_optional_with_safe_default(tmp_path):
    """不传 per_candidate_timeout_s 时,Stage 应有合理默认(够大,不退步)。

    目的:旧 spec / demo script 不传这个字段时,行为不退化(只是没 timeout 保护)。
    默认值 = 一个明显比"模型合理响应时间"大很多的值(如 1800s),允许单候选
    慢响应 + 容器首次 apt 装包,但能在真 hang 30+ 分钟时把它干掉。
    """
    # 不带 hang 候选(避免外层 wait_for 被拖死):只验字段存在 + 默认值合理。
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
            # 故意不传 per_candidate_timeout_s
            "agent": {"prompt": "x", "tool_scope": "read"},
        }],
    })
    # 字段在 parse_spec 后已存在(spec 是 frozen dataclass,直接在 spec 上读)
    assert spec.stages[0].per_candidate_timeout_s >= 600, (
        f"默认 timeout 应 ≥ 600s(docker verify 600s + 余量),"
        f"实际 {spec.stages[0].per_candidate_timeout_s}"
    )
    # 跑一遍确认不退步(2 候选都正常返)
    engine = WorkflowEngine.for_test(workspace=tmp_path, model_factory=factory)
    await _consume(engine, spec, outer_timeout_s=5.0)
    result = engine.last_result
    assert result is not None and result.stages
    assert len(result.stages[0].candidates) == 2
