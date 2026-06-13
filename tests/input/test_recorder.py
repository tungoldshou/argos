"""Recorder:sounddevice 开关录音(注入 fake sd 测,不碰真麦克风)。"""
import numpy as np
import pytest
from argos_agent.input.recorder import Recorder, RecorderError


class _FakeStream:
    def __init__(self, **kw):
        self.kw = kw
        self.started = False
        self.closed = False
    def start(self):
        self.started = True
    def stop(self):
        self.started = False
    def close(self):
        self.closed = True


class _FakeSd:
    def __init__(self):
        self.last = None
    def InputStream(self, **kw):
        self.last = _FakeStream(**kw)
        return self.last


def test_record_cycle_returns_concatenated_audio():
    sd = _FakeSd()
    rec = Recorder(samplerate=16000, sd_module=sd)
    rec.start()
    assert sd.last.started
    # 模拟回调灌入两块音频
    cb = sd.last.kw["callback"]
    cb(np.ones((100, 1), dtype="float32"), 100, None, None)
    cb(np.ones((50, 1), dtype="float32"), 50, None, None)
    audio = rec.stop()
    assert audio.shape == (150,)
    assert sd.last.closed

def test_stop_without_start_is_honest():
    rec = Recorder(sd_module=_FakeSd())
    with pytest.raises(RecorderError):
        rec.stop()

def test_no_audio_backend_is_honest():
    rec = Recorder(sd_module=None)
    # 强制 import 失败路径:注入一个会抛的 importer
    rec._import_sd = lambda: (_ for _ in ()).throw(RecorderError("无音频后端"))
    with pytest.raises(RecorderError):
        rec.start()

def test_empty_recording_is_honest():
    sd = _FakeSd()
    rec = Recorder(sd_module=sd)
    rec.start()
    with pytest.raises(RecorderError):  # 没灌任何帧
        rec.stop()
