"""Internal documentation."""
import importlib
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture
def reload_config(monkeypatch):
    """Internal documentation."""
    def _reload():
        import argos.config as cfg
        with patch.object(Path, "exists", return_value=False):
            return importlib.reload(cfg)
    return _reload


def test_argos_key_takes_priority(monkeypatch, reload_config):
    monkeypatch.setenv("ARGOS_LLM_KEY", "argos-key")
    monkeypatch.setenv("VITE_LLM_KEY", "vite-key")
    monkeypatch.setenv("VITE_MINIMAX_KEY", "minimax-key")
    cfg = reload_config()
    assert cfg.WORKER_KEYS[0] == "argos-key"


def test_fallback_to_vite_llm_then_minimax(monkeypatch, reload_config):
    monkeypatch.delenv("ARGOS_LLM_KEY", raising=False)
    monkeypatch.delenv("VITE_LLM_KEY", raising=False)
    monkeypatch.setenv("VITE_MINIMAX_KEY", "minimax-key")
    cfg = reload_config()
    assert cfg.WORKER_KEYS == ["minimax-key"]


def test_worker_keys_comma_split(monkeypatch, reload_config):
    monkeypatch.setenv("ARGOS_LLM_KEY", "k1, k2 ,k3")
    cfg = reload_config()
    assert cfg.WORKER_KEYS == ["k1", "k2", "k3"]


def test_default_tier_defaults(monkeypatch, reload_config):
    monkeypatch.delenv("ARGOS_LLM_MODEL", raising=False)
    monkeypatch.delenv("VITE_LLM_MODEL", raising=False)
    monkeypatch.delenv("VITE_MINIMAX_MODEL", raising=False)
    monkeypatch.delenv("ARGOS_LLM_BASE", raising=False)
    monkeypatch.delenv("VITE_LLM_BASE", raising=False)
    monkeypatch.delenv("VITE_MINIMAX_URL", raising=False)
    monkeypatch.delenv("ARGOS_LLM_MAX_TOKENS", raising=False)
    cfg = reload_config()
    assert cfg.DEFAULT_TIER.name == "default"
    assert cfg.DEFAULT_TIER.model == "MiniMax-M2"
    assert cfg.DEFAULT_TIER.base_url == "https://api.minimaxi.com/anthropic"
    assert cfg.DEFAULT_TIER.max_tokens == 4096
    assert not hasattr(cfg, "PREMIUM_TIER")


def test_max_tokens_configurable(monkeypatch, reload_config):
    monkeypatch.setenv("ARGOS_LLM_MAX_TOKENS", "16000")
    cfg = reload_config()
    assert cfg.DEFAULT_TIER.max_tokens == 16000
