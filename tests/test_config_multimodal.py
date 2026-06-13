"""config.json 的 multimodal override 三态读取:未设→None;true→True;false→False。"""
import json
from pathlib import Path

from argos import config as C


def _write_config(tmp_path: Path, model_extra: dict) -> None:
    cfg = {
        "active": "m",
        "models": {"m": {
            "model": "agnes-2.0-flash", "base_url": "https://x/v1",
            "protocol": "openai", "max_tokens": 1024, **model_extra,
        }},
    }
    (tmp_path / "config.json").write_text(json.dumps(cfg))


def test_multimodal_unset_is_none(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(tmp_path))
    _write_config(tmp_path, {})
    cfg = C.load_config()
    assert cfg.tiers["m"].multimodal is None


def test_multimodal_true_override(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(tmp_path))
    _write_config(tmp_path, {"multimodal": True})
    cfg = C.load_config()
    assert cfg.tiers["m"].multimodal is True


def test_multimodal_false_override(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(tmp_path))
    _write_config(tmp_path, {"multimodal": False})
    cfg = C.load_config()
    assert cfg.tiers["m"].multimodal is False
