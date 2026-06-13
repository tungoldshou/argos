"""stt_transcribe 能力声明云端 STT 出网 host,register_builtins 后进 egress 聚合。"""
from argos.capability.registry import CapabilityRegistry
from argos.capability.builtins import register_builtins


def test_stt_egress_hosts_registered():
    reg = CapabilityRegistry()
    register_builtins(reg)
    assert "stt_transcribe" in reg
    hosts = reg.egress_hosts()
    assert "api.openai.com" in hosts
    assert "api.deepgram.com" in hosts
