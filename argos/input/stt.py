"""语音转文字(STT):provider-agnostic。本地默认(faster-whisper,Apple Silicon 走 mlx),
云端可选(OpenAI)。宿主进程跑(沙箱外)。诚实:任何失败 → SttError,不伪造转写。
"""
from __future__ import annotations

import platform
from typing import Protocol, runtime_checkable

from argos.i18n import t


class SttError(Exception):
    """转写失败:模型缺失 / 后端异常 / 云端报错。"""


@runtime_checkable
class Transcriber(Protocol):
    def transcribe(self, audio, samplerate: int = 16000) -> str: ...


def is_apple_silicon() -> bool:
    """显式平台检测(不靠 ImportError:Linux 也有 mlx 轮子会静默跑 CPU)。"""
    return platform.system() == "Darwin" and platform.machine() == "arm64"


class LocalWhisper:
    """本地 whisper。Apple Silicon → mlx-whisper(失败回退 faster-whisper);否则 faster-whisper。
    权重首次使用懒下载到 ~/.cache/huggingface。backend 可注入(测试用)。"""

    def __init__(self, model_name: str = "base", backend=None) -> None:
        self._model_name = model_name
        self._backend = backend  # callable(audio, samplerate) -> str;None = 首用构造真后端

    def _build_backend(self):
        if is_apple_silicon():
            try:
                import mlx_whisper  # noqa: F401
                repo = f"mlx-community/whisper-{self._model_name}-mlx"

                def _mlx(audio, sr):
                    return mlx_whisper.transcribe(audio, path_or_hf_repo=repo).get("text", "")
                return _mlx
            except Exception:  # noqa: BLE001 — mlx 缺失 → 回退 faster-whisper(仍本地)
                pass
        try:
            from faster_whisper import WhisperModel
        except Exception as e:  # noqa: BLE001
            raise SttError(t("core2.stt.local_unavailable")) from e
        model = WhisperModel(self._model_name, device="cpu", compute_type="int8")

        def _fw(audio, sr):
            segments, _info = model.transcribe(audio)
            return "".join(seg.text for seg in segments)
        return _fw

    def transcribe(self, audio, samplerate: int = 16000) -> str:
        if self._backend is None:
            self._backend = self._build_backend()
        try:
            return (self._backend(audio, samplerate) or "").strip()
        except SttError:
            raise
        except Exception as e:  # noqa: BLE001
            raise SttError(t("core2.stt.local_failed", error=e)) from e


def _pcm16_wav_bytes(audio, samplerate: int) -> bytes:
    """float32 单声道数组 → 16-bit PCM WAV 字节(stdlib wave,无需 soundfile/ffmpeg)。"""
    import io
    import wave
    import numpy as np
    arr = np.asarray(audio, dtype="float32").reshape(-1)
    pcm = (np.clip(arr, -1.0, 1.0) * 32767.0).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(samplerate)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


class CloudWhisper:
    """云端 STT(OpenAI 兼容 /audio/transcriptions)。client 可注入(测试用)。"""

    def __init__(self, *, api_key: str | None, base_url: str | None = None,
                 model: str = "whisper-1", client=None) -> None:
        self._api_key = api_key
        self._base_url = base_url
        self._model = model
        self._client = client

    def _get_client(self):
        if self._client is None:
            try:
                from openai import OpenAI
            except Exception as e:  # noqa: BLE001
                raise SttError(t("core2.stt.cloud_sdk_missing")) from e
            self._client = OpenAI(api_key=self._api_key, base_url=self._base_url)
        return self._client

    def transcribe(self, audio, samplerate: int = 16000) -> str:
        import io
        wav = _pcm16_wav_bytes(audio, samplerate)
        client = self._get_client()
        try:
            # 显式 timeout:OpenAI SDK 默认 read=600s,卡住的上传/连接会让"转写中…"转近 10 分钟。
            # 60s 够正常转写,超时则经下方 except 转成诚实 SttError(2026-06-18 排查 #8)。
            resp = client.audio.transcriptions.create(
                model=self._model, file=("audio.wav", io.BytesIO(wav)), timeout=60,
            )
        except Exception as e:  # noqa: BLE001
            raise SttError(t("core2.stt.cloud_failed", error=e)) from e
        return (getattr(resp, "text", None) or "").strip()


def make_transcriber(cfg) -> Transcriber:
    """按 SttConfig 选 provider:cloud → CloudWhisper;否则本地 LocalWhisper。"""
    if cfg.provider == "cloud":
        return CloudWhisper(api_key=cfg.api_key, base_url=cfg.base_url,
                            model=cfg.model or "whisper-1")
    return LocalWhisper(model_name=cfg.model or "base")
