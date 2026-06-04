import json
import pytest
from argos_agent import config as C


def _write(tmp_path, cfg: dict, env: str = ""):
    (tmp_path / "config.json").write_text(json.dumps(cfg))
    if env:
        (tmp_path / ".env").write_text(env)


def test_load_config_builds_profiles(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(tmp_path))
    _write(tmp_path, {
        "active": "mm",
        "models": {"mm": {"protocol": "anthropic", "base_url": "https://x/anthropic",
                          "model": "MiniMax-M3", "api_key_env": "MM_KEY",
                          "max_tokens": 4096, "context_window": 192000,
                          "price_in": 0.3, "price_out": 1.2}},
    }, env="MM_KEY=secret123\n")
    cfg = C.load_config()
    assert cfg.active == "mm"
    tier = C.active_tier()
    assert tier.model == "MiniMax-M3" and tier.protocol == "anthropic" and tier.context_window == 192000
    assert C.active_key() == "secret123"


def test_os_environ_overrides_dotenv(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("MM_KEY", "from_os")
    _write(tmp_path, {"active": "mm", "models": {"mm": {"protocol": "openai",
           "base_url": "http://x/v1", "model": "m", "api_key_env": "MM_KEY"}}},
           env="MM_KEY=from_file\n")
    assert C.active_key() == "from_os"   # 进程 env > .env 文件


def test_active_not_in_models_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(tmp_path))
    _write(tmp_path, {"active": "ghost", "models": {"mm": {"protocol": "openai",
           "base_url": "http://x/v1", "model": "m", "api_key_env": "K"}}})
    with pytest.raises(C.ConfigError):
        C.load_config()


def test_missing_required_field_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(tmp_path))
    _write(tmp_path, {"active": "mm", "models": {"mm": {"protocol": "openai"}}})  # 缺 base_url/model
    with pytest.raises(C.ConfigError):
        C.load_config()


def test_price_registered_into_pricing(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(tmp_path))
    _write(tmp_path, {"active": "mm", "models": {"mm": {"protocol": "anthropic",
           "base_url": "https://x", "model": "PricedModel", "api_key_env": "K",
           "price_in": 0.5, "price_out": 2.0}}}, env="K=k\n")
    C.load_config()
    from argos_agent.core.observability import PRICING
    assert PRICING.get("PricedModel") == {"in": 0.5, "out": 2.0}
