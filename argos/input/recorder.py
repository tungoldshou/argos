"""麦克风采集:sounddevice 开关式录音 → float32 16kHz 单声道数组(宿主进程,沙箱外)。

诚实:无音频后端 / 无麦克风 / 未在录音 / 没录到音 → RecorderError,绝不静默。
sd_module 可注入(测试)。生产:首次 start 懒 import sounddevice。
"""
from __future__ import annotations


class RecorderError(Exception):
    """录音失败:无后端 / 无设备 / 状态非法 / 空录音。"""


class Recorder:
    def __init__(self, samplerate: int = 16000, sd_module=None) -> None:
        self._sr = samplerate
        self._sd = sd_module
        self._stream = None
        self._frames: list = []

    def _import_sd(self):
        """懒 import sounddevice;ImportError(未装)/ OSError(PortAudio 缺失)→ RecorderError。"""
        if self._sd is not None:
            return self._sd
        try:
            import sounddevice as sd
        except Exception as e:  # noqa: BLE001 — ImportError 或 OSError(Linux 缺 libportaudio2)
            raise RecorderError(
                "无法加载音频后端(sounddevice/PortAudio)。"
                "Linux 需 `apt install libportaudio2`;其余平台 wheel 应自带。"
            ) from e
        return sd

    def start(self) -> None:
        sd = self._import_sd()
        self._frames = []

        def _cb(indata, frames, time_, status):  # noqa: ANN001 — sounddevice 回调签名
            self._frames.append(indata.copy())

        try:
            self._stream = sd.InputStream(
                samplerate=self._sr, channels=1, dtype="float32", callback=_cb,
            )
            self._stream.start()
        except Exception as e:  # noqa: BLE001 — 无麦克风等
            raise RecorderError(f"开始录音失败(可能无麦克风):{e}") from e

    def stop(self):
        """停止并返回 float32 单声道一维数组。未录音 / 空录音 → RecorderError。"""
        if self._stream is None:
            raise RecorderError("当前未在录音。")
        try:
            self._stream.stop()
            self._stream.close()
        finally:
            self._stream = None
        import numpy as np
        if not self._frames:
            raise RecorderError("没有录到音频(可能麦克风无输入)。")
        return np.concatenate(self._frames, axis=0).reshape(-1)
