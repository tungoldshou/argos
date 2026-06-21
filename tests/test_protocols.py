import json
from argos.core.protocols import (
    get_protocol, AnthropicProtocol, OpenAIProtocol, _coalesce_consecutive_roles,
)
from argos.core.models import ModelTier


def _tier(protocol="anthropic", base="https://api.x.com"):
    return ModelTier(name="t", model="m", base_url=base, max_tokens=99,
                     context_window=1000, protocol=protocol)


def test_get_protocol_returns_right_adapter():
    assert isinstance(get_protocol("anthropic"), AnthropicProtocol)
    assert isinstance(get_protocol("openai"), OpenAIProtocol)


def test_anthropic_payload_system_toplevel_and_coalesced():
    p = AnthropicProtocol()
    pl = p.payload([{"role": "user", "content": "a"}, {"role": "user", "content": "b"}],
                   system="sys", tier=_tier())
    assert pl["system"][-1]["text"] == "sys"   # system 以内容块承载(见 caching 测试),原文保留
    assert pl["model"] == "m" and pl["max_tokens"] == 99 and pl["stream"] is True
    assert len(pl["messages"]) == 1 and pl["messages"][0]["content"] == "a\nb"  # coalesced


def test_anthropic_payload_marks_system_for_prompt_caching():
    """Anthropic 缓存是显式 opt-in:system 必须作带 cache_control 的内容块,否则永远 0 命中。
    缓存最大、最稳、每个 CodeAct 步都原样重发的系统提示 → 同一 run 内第二步起全命中。
    (OpenAI 协议靠服务端自动缓存、不认此字段 —— 见 test_openai_payload_*,system 仍是纯消息。)"""
    p = AnthropicProtocol()
    pl = p.payload([{"role": "user", "content": "a"}], system="sys", tier=_tier())
    assert isinstance(pl["system"], list), "system 应为内容块列表(才能挂 cache_control)"
    block = pl["system"][-1]
    assert block["type"] == "text" and block["text"] == "sys"   # 原文保留
    assert block["cache_control"] == {"type": "ephemeral"}        # 缓存断点已打


def test_anthropic_endpoint_and_headers():
    p = AnthropicProtocol()
    assert p.endpoint("https://api.x.com/anthropic/") == "https://api.x.com/anthropic/v1/messages"
    h = p.headers("KEY")
    assert h["x-api-key"] == "KEY" and h["anthropic-version"] == "2023-06-01"


def test_anthropic_text_delta_and_usage():
    p = AnthropicProtocol()
    assert p.text_delta({"type": "content_block_delta",
                         "delta": {"type": "text_delta", "text": "hi"}}) == "hi"
    u = {"input_tokens": 0, "output_tokens": 0, "cache_read": 0, "cache_creation": 0}
    p.capture_usage({"type": "message_start", "message": {"usage": {
        "input_tokens": 0, "cache_read_input_tokens": 179, "cache_creation_input_tokens": 5}}}, u)
    assert u["cache_read"] == 179 and u["cache_creation"] == 5
    p.capture_usage({"type": "message_delta", "usage": {"input_tokens": 65, "output_tokens": 41}}, u)
    assert u["input_tokens"] == 65 and u["output_tokens"] == 41


def test_anthropic_captures_output_tokens_from_message_start():
    """保真修复:output_tokens 也从 message_start 捕获(Anthropic 规范该帧含此字段)。

    此前只在 message_delta 抓 output —— 第三方 Anthropic 兼容端点若那帧形态不标准/缺字段,
    该轮 output 静默记 0,累计被低估(真机 agnes-2.0-flash:输入 37.9k 但输出仅 174)。
    从两帧都抓 = 最大化诚实提取;标准端点 message_delta 的累积值仍覆盖 message_start 初值。
    """
    p = AnthropicProtocol()
    u = {"input_tokens": 0, "output_tokens": 0, "cache_read": 0, "cache_creation": 0}
    p.capture_usage({"type": "message_start", "message": {"usage": {
        "input_tokens": 100, "output_tokens": 7}}}, u)
    assert u["output_tokens"] == 7   # 不再只在 message_delta 抓
    # message_delta 的累积值仍覆盖 message_start 初值(标准流:最终 output 在 message_delta)
    p.capture_usage({"type": "message_delta", "usage": {"output_tokens": 523}}, u)
    assert u["output_tokens"] == 523


def test_modelclient_selects_protocol_by_tier():
    from argos.core.models import ModelClient
    mc = ModelClient.__new__(ModelClient)
    mc.tier = _tier(protocol="openai")
    mc._proto = get_protocol(mc.tier.protocol)
    assert mc._proto.name == "openai"


def test_coalesce_still_importable_from_models():
    # 向后兼容:旧测试/代码 from argos.core.models import _coalesce_consecutive_roles
    from argos.core.models import _coalesce_consecutive_roles as c
    assert c([{"role": "user", "content": "a"}, {"role": "user", "content": "b"}])[0]["content"] == "a\nb"


def test_openai_payload_system_as_message_and_stream_options():
    p = OpenAIProtocol()
    pl = p.payload([{"role": "user", "content": "a"}, {"role": "user", "content": "b"}],
                   system="sys", tier=_tier(protocol="openai", base="http://localhost:11434/v1"))
    assert pl["messages"][0] == {"role": "system", "content": "sys"}   # system 作首条消息
    assert pl["messages"][1]["content"] == "a\nb"                       # 其余 coalesced
    assert pl["model"] == "m" and pl["max_tokens"] == 99
    assert pl["stream"] is True and pl["stream_options"] == {"include_usage": True}


def test_openai_endpoint_and_headers():
    p = OpenAIProtocol()
    assert p.endpoint("http://localhost:11434/v1") == "http://localhost:11434/v1/chat/completions"
    assert p.headers("KEY")["Authorization"] == "Bearer KEY"


def test_openai_text_delta_and_done():
    p = OpenAIProtocol()
    assert p.text_delta({"choices": [{"delta": {"content": "hi"}}]}) == "hi"
    assert p.text_delta({"choices": [{"delta": {"role": "assistant"}}]}) == ""   # role-only 首块
    assert p.is_done({"choices": [{"finish_reason": "stop", "delta": {}}]}) is True
    assert p.is_done({"choices": [{"finish_reason": None, "delta": {"content": "x"}}]}) is False


def test_openai_capture_usage_maps_prompt_completion_cached():
    p = OpenAIProtocol()
    u = {"input_tokens": 0, "output_tokens": 0, "cache_read": 0, "cache_creation": 0}
    p.capture_usage({"usage": {"prompt_tokens": 120, "completion_tokens": 45,
                               "prompt_tokens_details": {"cached_tokens": 30}}}, u)
    assert u["input_tokens"] == 120 and u["output_tokens"] == 45 and u["cache_read"] == 30


import httpx, pytest
from argos.core.models import ModelClient, CredentialPool


@pytest.mark.asyncio
async def test_openai_stream_end_to_end_mock():
    # 真实 OpenAI include_usage 形态:usage 在 finish_reason 之后的【单独一帧】(choices:[]),
    # 不在完成帧里。stream 必须读到该尾帧才抓得到 usage(回归:此前一 is_done 即 break → usage 恒 0)。
    sse = (b'data: {"choices":[{"delta":{"role":"assistant"}}]}\n\n'
           b'data: {"choices":[{"delta":{"content":"he"}}]}\n\n'
           b'data: {"choices":[{"delta":{"content":"llo"}}]}\n\n'
           b'data: {"choices":[{"finish_reason":"stop","delta":{}}]}\n\n'
           b'data: {"choices":[],"usage":{"prompt_tokens":10,"completion_tokens":2,'
           b'"prompt_tokens_details":{"cached_tokens":4}}}\n\n'
           b'data: [DONE]\n\n')

    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path.endswith("/chat/completions")
        assert req.headers["authorization"] == "Bearer K"
        return httpx.Response(200, content=sse)

    mc = ModelClient(tier=_tier(protocol="openai", base="http://x/v1"),
                     pool=CredentialPool(["K"]), transport=httpx.MockTransport(handler))
    out = "".join([c async for c in mc.stream([{"role": "user", "content": "hi"}], system="s")])
    assert out == "hello"
    # usage 来自完成帧【之后】的单独 usage-only 帧,必须被抓到(否则 OpenAI 成本恒 0)
    assert mc.last_usage["input_tokens"] == 10 and mc.last_usage["output_tokens"] == 2
    assert mc.last_usage["cache_read"] == 4


def test_anthropic_context_total_is_input_plus_cache():
    """D1:Anthropic 口径 input_tokens 不含缓存 → context_total = input + cache_read + cache_creation。"""
    p = AnthropicProtocol()
    u: dict = {}
    p.capture_usage({"type": "message_start", "message": {"usage": {
        "input_tokens": 600, "cache_read_input_tokens": 400, "cache_creation_input_tokens": 0,
    }}}, u)
    assert u["context_total"] == 1000


def test_openai_context_total_does_not_double_count_cache():
    """D1(2026-06-22:OpenAI 路径上下文 % 高估):prompt_tokens 已含 cached_tokens,
    context_total 必须 == prompt_tokens,不能再加 cache_read,否则缓存部分被重复计。"""
    p = OpenAIProtocol()
    u: dict = {}
    p.capture_usage({"usage": {"prompt_tokens": 1000, "completion_tokens": 45,
                               "prompt_tokens_details": {"cached_tokens": 400}}}, u)
    assert u["context_total"] == 1000, "不得 == 1400(重复计 cached)"
    assert u["cache_read"] == 400      # cache_read 仍如实记录(供缓存命中显示)
