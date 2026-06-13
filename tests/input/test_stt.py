"""STT:LocalWhisper(注入 backend 测,不加载真模型)+ 平台检测。"""
import numpy as np
import pytest
from argos_agent.input.stt import LocalWhisper, SttError, is_apple_silicon


def test_local_whisper_uses_injected_backend():
    lw = LocalWhisper(model_name="base", backend=lambda audio, sr: "  hello world  ")
    out = lw.transcribe(np.zeros(1600, dtype="float32"))
    assert out == "hello world"  # strip 过

def test_local_whisper_wraps_backend_error():
    def boom(audio, sr):
        raise RuntimeError("model exploded")
    lw = LocalWhisper(model_name="base", backend=boom)
    with pytest.raises(SttError) as e:
        lw.transcribe(np.zeros(10, dtype="float32"))
    assert "model exploded" in str(e.value)

def test_is_apple_silicon_uses_platform(monkeypatch):
    import argos_agent.input.stt as stt
    monkeypatch.setattr(stt.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(stt.platform, "machine", lambda: "arm64")
    assert is_apple_silicon() is True
    monkeypatch.setattr(stt.platform, "machine", lambda: "x86_64")
    assert is_apple_silicon() is False
    monkeypatch.setattr(stt.platform, "system", lambda: "Linux")
    monkeypatch.setattr(stt.platform, "machine", lambda: "aarch64")
    assert is_apple_silicon() is False  # Linux ARM 不是 Apple Silicon(关键:不靠 ImportError)


from argos_agent.input.stt import CloudWhisper, make_transcriber, _pcm16_wav_bytes
from argos_agent.input.stt_config import SttConfig


def test_pcm16_wav_bytes_is_valid_wav():
    import io, wave
    audio = np.zeros(1600, dtype="float32")
    data = _pcm16_wav_bytes(audio, 16000)
    with wave.open(io.BytesIO(data), "rb") as w:
        assert w.getframerate() == 16000
        assert w.getnchannels() == 1
        assert w.getsampwidth() == 2

def test_cloud_whisper_uses_injected_client():
    class _Resp:
        text = "  transcribed cloud  "

    class _FakeClient:
        class audio:
            class transcriptions:
                @staticmethod
                def create(model, file):
                    assert model == "whisper-1"
                    return _Resp()

    cw = CloudWhisper(api_key="k", base_url=None, model="whisper-1", client=_FakeClient())
    assert cw.transcribe(np.zeros(1600, dtype="float32")) == "transcribed cloud"

def test_make_transcriber_local():
    t = make_transcriber(SttConfig(provider="local", model="base"))
    assert isinstance(t, LocalWhisper)

def test_make_transcriber_cloud():
    t = make_transcriber(SttConfig(provider="cloud", model="whisper-1", api_key="k"))
    assert isinstance(t, CloudWhisper)
