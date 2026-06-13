"""语音依赖默认随基础安装;mlx 条件依赖;云端 STT 作可选 extra。"""
import tomllib
from pathlib import Path

_PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


def _data():
    return tomllib.loads(_PYPROJECT.read_text())


def test_base_deps_include_voice():
    deps = _data()["project"]["dependencies"]
    joined = " ".join(deps)
    assert "sounddevice" in joined
    assert "faster-whisper" in joined

def test_mlx_whisper_is_conditional():
    deps = " ".join(_data()["project"]["dependencies"])
    assert "mlx-whisper" in deps
    assert "platform_machine == 'arm64'" in deps  # Apple Silicon 条件 marker

def test_cloud_stt_optional_extra():
    extras = _data()["project"].get("optional-dependencies", {})
    assert "cloud-stt" in extras
    assert any("openai" in d for d in extras["cloud-stt"])
