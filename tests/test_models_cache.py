# tests/test_models_cache.py
from argos_agent.core.models import ModelClient, _coalesce_consecutive_roles
from argos_agent.tui.events import CostUpdate


def test_capture_usage_reads_cache_tokens():
    from argos_agent.core.protocols import get_protocol
    mc = ModelClient.__new__(ModelClient)
    mc.last_usage = {"input_tokens": 0, "output_tokens": 0, "cache_read": 0, "cache_creation": 0}
    mc._proto = get_protocol("anthropic")
    mc._capture_usage({"type": "message_start", "message": {"usage": {
        "input_tokens": 0, "cache_read_input_tokens": 179, "cache_creation_input_tokens": 5}}})
    assert mc.last_usage["cache_read"] == 179
    assert mc.last_usage["cache_creation"] == 5
    mc._capture_usage({"type": "message_delta", "usage": {
        "input_tokens": 65, "output_tokens": 41, "cache_read_input_tokens": 114}})
    assert mc.last_usage["input_tokens"] == 65
    assert mc.last_usage["output_tokens"] == 41
    assert mc.last_usage["cache_read"] == 114


def test_costupdate_has_cache_read_field():
    cu = CostUpdate(tokens_in=1, tokens_out=2, cost_usd=0.0, elapsed_s=1.0, cache_read=179)
    assert cu.cache_read == 179
    # 默认值向后兼容
    cu2 = CostUpdate(tokens_in=1, tokens_out=2, cost_usd=0.0, elapsed_s=1.0)
    assert cu2.cache_read == 0


def test_coalesce_consecutive_roles_keeps_alternation():
    """I1 修复:多轮/压缩产生的连续同 role 必须被合并,保证 user/assistant 交替
    (否则真 Anthropic 兼容端 400 'roles must alternate')。"""
    # 连续 user(空 assistant 答复 → 只存了 goal;或压缩摘要 user + goal user)
    out = _coalesce_consecutive_roles([
        {"role": "user", "content": "第一轮目标"},
        {"role": "user", "content": "第二轮:继续"},
        {"role": "assistant", "content": "好"},
    ])
    assert [m["role"] for m in out] == ["user", "assistant"], "相邻同 role 必须合并"
    assert out[0]["content"] == "第一轮目标\n第二轮:继续"


def test_payload_normalizes_messages():
    """_payload 必须把消息归一化(交替),保护真请求不被端点拒。"""
    from argos_agent.core.protocols import get_protocol
    mc = ModelClient.__new__(ModelClient)
    from argos_agent.core.models import ModelTier
    mc.tier = ModelTier(name="worker", model="m", base_url="http://x", max_tokens=100, context_window=1000)
    mc._proto = get_protocol(mc.tier.protocol)
    payload = mc._payload(
        [{"role": "user", "content": "a"}, {"role": "user", "content": "b"}], system="s")
    roles = [m["role"] for m in payload["messages"]]
    assert roles == roles[:1] + [r for i, r in enumerate(roles[1:], 1) if r != roles[i - 1]], \
        "payload messages 不得有相邻同 role"
    assert len(payload["messages"]) == 1 and payload["messages"][0]["content"] == "a\nb"
