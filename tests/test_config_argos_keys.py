"""config ARGOS_* 优先 + 回退链(契约 §8)。用 monkeypatch 改 os.environ 验证优先级。"""
import importlib
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture
def reload_config(monkeypatch):
    """重新加载 config 模块,并隔离 .env.local 文件(测试环境不依赖本地文件)。"""
    def _reload():
        import argos_agent.config as cfg
        # patch Path.exists 让 .env.local 被视为不存在,使测试不受本地文件影响。
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


def test_worker_tier_defaults(monkeypatch, reload_config):
    monkeypatch.delenv("ARGOS_LLM_MODEL", raising=False)
    monkeypatch.delenv("VITE_LLM_MODEL", raising=False)
    monkeypatch.delenv("VITE_MINIMAX_MODEL", raising=False)
    monkeypatch.delenv("ARGOS_LLM_BASE", raising=False)
    monkeypatch.delenv("VITE_LLM_BASE", raising=False)
    monkeypatch.delenv("VITE_MINIMAX_URL", raising=False)
    monkeypatch.delenv("ARGOS_LLM_MAX_TOKENS", raising=False)
    cfg = reload_config()
    assert cfg.WORKER_TIER.name == "worker"
    assert cfg.WORKER_TIER.model == "MiniMax-M2"
    assert cfg.WORKER_TIER.base_url == "https://api.minimaxi.com/anthropic"
    assert cfg.WORKER_TIER.max_tokens == 4096  # 替换硬编码 2048


def test_premium_tier_defaults(monkeypatch, reload_config):
    monkeypatch.delenv("ARGOS_PREMIUM_MODEL", raising=False)
    monkeypatch.delenv("ARGOS_PREMIUM_BASE", raising=False)
    monkeypatch.delenv("ARGOS_PREMIUM_MAX_TOKENS", raising=False)
    cfg = reload_config()
    assert cfg.PREMIUM_TIER.name == "premium"
    assert cfg.PREMIUM_TIER.model == "claude-sonnet-4-6"
    assert cfg.PREMIUM_TIER.base_url == "https://api.anthropic.com"
    assert cfg.PREMIUM_TIER.max_tokens == 8192


def test_max_tokens_configurable(monkeypatch, reload_config):
    monkeypatch.setenv("ARGOS_LLM_MAX_TOKENS", "16000")
    cfg = reload_config()
    assert cfg.WORKER_TIER.max_tokens == 16000
