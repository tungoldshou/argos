"""可观测(契约 §1 CostUpdate;spec §3.3 L5):stream_diag TTFB/chunks/异常链 + per-step cost。"""
import pytest

from argos_agent.core.observability import (
    StreamDiag,
    stream_diag,
    PRICING,
    cost_of,
    StepCost,
)


@pytest.mark.asyncio
async def test_stream_diag_counts_chunks_and_ttfb():
    async def gen():
        for x in ["a", "b", "c"]:
            yield x

    diag = StreamDiag()
    out = [c async for c in stream_diag(gen(), diag)]
    assert out == ["a", "b", "c"]
    assert diag.chunks == 3
    assert diag.ttfb_s is not None and diag.ttfb_s >= 0.0
    assert diag.exception_chain == []


@pytest.mark.asyncio
async def test_stream_diag_captures_exception_chain():
    async def gen():
        yield "a"
        try:
            raise ValueError("底层真因")
        except ValueError as e:
            raise RuntimeError("流中断") from e

    diag = StreamDiag()
    with pytest.raises(RuntimeError):
        async for _ in stream_diag(gen(), diag):
            pass
    # 异常链拍平挖到底层真因(spec §3.3 L5)
    joined = " | ".join(diag.exception_chain)
    assert "底层真因" in joined
    assert "流中断" in joined
    assert diag.chunks == 1  # 中断前发了 1 个


def test_cost_of_known_model():
    # MiniMax-M2 在 PRICING 表里 → 按 (in*price_in + out*price_out)/1e6 算
    assert "MiniMax-M2" in PRICING
    sc = cost_of({"input_tokens": 1_000_000, "output_tokens": 1_000_000}, model="MiniMax-M2")
    assert isinstance(sc, StepCost)
    assert sc.tokens_in == 1_000_000
    assert sc.tokens_out == 1_000_000
    price = PRICING["MiniMax-M2"]
    assert sc.cost_usd == pytest.approx(price["in"] + price["out"])


def test_cost_of_unknown_model_zero_cost_honest():
    # 未知模型 → 不瞎编价格,成本算 0 但 tokens 仍如实计(诚实:不假装知道价)。
    sc = cost_of({"input_tokens": 100, "output_tokens": 50}, model="unknown-model-x")
    assert sc.tokens_in == 100
    assert sc.tokens_out == 50
    assert sc.cost_usd == 0.0


def test_cost_of_handles_missing_usage_keys():
    sc = cost_of({}, model="MiniMax-M2")
    assert sc.tokens_in == 0 and sc.tokens_out == 0 and sc.cost_usd == 0.0
