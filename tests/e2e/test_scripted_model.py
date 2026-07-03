"""Internal documentation."""
import pytest

from tests.e2e.scripted_model import ScriptedModelClient


@pytest.mark.asyncio
async def test_stream_yields_scripted_text_in_order():
    m = ScriptedModelClient(scripts=["第一轮文本", "第二轮文本"])
    out1 = "".join([c async for c in m.stream([{"role": "user", "content": "g"}], system="S")])
    assert out1 == "第一轮文本"
    out2 = "".join([c async for c in m.stream([{"role": "user", "content": "g"}], system="S")])
    assert out2 == "第二轮文本"


@pytest.mark.asyncio
async def test_stream_repeats_last_script_when_exhausted():
    m = ScriptedModelClient(scripts=["唯一一轮"])
    _ = "".join([c async for c in m.stream([], system="S")])
    out2 = "".join([c async for c in m.stream([], system="S")])
    assert out2 == "唯一一轮"


@pytest.mark.asyncio
async def test_complete_returns_full_script():
    m = ScriptedModelClient(scripts=["完整一轮"])
    assert await m.complete([], system="S") == "完整一轮"


def test_has_tier_attribute_for_loop_compat():
    m = ScriptedModelClient(scripts=["x"])
    assert m.tier.name in ("worker", "premium")
