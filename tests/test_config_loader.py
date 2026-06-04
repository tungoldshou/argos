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


def test_malformed_json_raises_configerror(tmp_path, monkeypatch):
    """fail-closed:config.json 畸形 → ConfigError(不漏 JSONDecodeError 击穿调用方)。"""
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(tmp_path))
    (tmp_path / "config.json").write_text("{ not valid json ,, }")
    with pytest.raises(C.ConfigError):
        C.load_config()


def test_invalid_protocol_raises(tmp_path, monkeypatch):
    """fail-closed:protocol 拼错(非 anthropic/openai)→ ConfigError,不静默退化成 Anthropic。"""
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(tmp_path))
    _write(tmp_path, {"active": "mm", "models": {"mm": {"protocol": "anthropc",  # 拼错
           "base_url": "http://x/v1", "model": "m", "api_key_env": "K"}}})
    with pytest.raises(C.ConfigError):
        C.load_config()


def test_non_numeric_max_tokens_raises_configerror(tmp_path, monkeypatch):
    """fail-closed:max_tokens 非数字 → ConfigError(不漏 ValueError;调用方只接 ConfigError)。"""
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(tmp_path))
    _write(tmp_path, {"active": "mm", "models": {"mm": {"protocol": "openai",
           "base_url": "http://x/v1", "model": "m", "api_key_env": "K", "max_tokens": "abc"}}})
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


def test_legacy_env_fallback_when_no_config(tmp_path, monkeypatch):
    """无 config.json 时,旧 ARGOS_LLM_*/VITE_* 合成 default profile(现存用户零改动)。"""
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(tmp_path))   # 空目录,无 config.json
    monkeypatch.setenv("ARGOS_LLM_KEY", "legacykey")
    monkeypatch.setenv("ARGOS_LLM_MODEL", "MiniMax-M3")
    import importlib
    from argos_agent import config as C2
    importlib.reload(C2)   # 重读模块级 _WORKER_* (它们在 import 时算)
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(tmp_path))
    tier = C2.active_tier()
    assert tier.model == "MiniMax-M3" and tier.protocol == "anthropic"
    assert C2.active_key() == "legacykey"
