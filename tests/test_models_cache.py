# tests/test_models_cache.py
from argos_agent.core.models import ModelClient
from argos_agent.tui.events import CostUpdate


def test_capture_usage_reads_cache_tokens():
    mc = ModelClient.__new__(ModelClient)
    mc.last_usage = {"input_tokens": 0, "output_tokens": 0, "cache_read": 0, "cache_creation": 0}
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
