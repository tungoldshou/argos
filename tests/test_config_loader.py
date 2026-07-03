import json
import pytest
from argos import config as C


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


def test_dotenv_export_assignment_provides_active_key(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(tmp_path))
    _write(tmp_path, {
        "active": "mm",
        "models": {"mm": {"protocol": "openai", "base_url": "http://x/v1",
                          "model": "m", "api_key_env": "MM_KEY"}},
    }, env="export MM_KEY=secret123\n")

    assert C.active_key() == "secret123"


@pytest.mark.parametrize("quote", ['"', "'"])
def test_dotenv_quoted_assignment_provides_active_key(tmp_path, monkeypatch, quote):
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(tmp_path))
    _write(tmp_path, {
        "active": "mm",
        "models": {"mm": {"protocol": "openai", "base_url": "http://x/v1",
                          "model": "m", "api_key_env": "MM_KEY"}},
    }, env=f"MM_KEY={quote}secret123{quote}\n")

    assert C.active_key() == "secret123"


def test_os_environ_overrides_dotenv(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("MM_KEY", "from_os")
    _write(tmp_path, {"active": "mm", "models": {"mm": {"protocol": "openai",
           "base_url": "http://x/v1", "model": "m", "api_key_env": "MM_KEY"}}},
           env="MM_KEY=from_file\n")
    assert C.active_key() == "from_os"


def test_active_not_in_models_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(tmp_path))
    _write(tmp_path, {"active": "ghost", "models": {"mm": {"protocol": "openai",
           "base_url": "http://x/v1", "model": "m", "api_key_env": "K"}}})
    with pytest.raises(C.ConfigError):
        C.load_config()


def test_active_must_be_string(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(tmp_path))
    _write(tmp_path, {"active": ["mm"], "models": {"mm": {"protocol": "openai",
           "base_url": "http://x/v1", "model": "m", "api_key_env": "K"}}})
    with pytest.raises(C.ConfigError):
        C.load_config()


def test_missing_required_field_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(tmp_path))
    _write(tmp_path, {"active": "mm", "models": {"mm": {"protocol": "openai"}}})
    with pytest.raises(C.ConfigError):
        C.load_config()


@pytest.mark.parametrize("field", ["base_url", "model"])
def test_blank_required_string_raises(tmp_path, monkeypatch, field):
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(tmp_path))
    profile = {
        "protocol": "openai",
        "base_url": "http://x/v1",
        "model": "m",
        "api_key_env": "K",
    }
    profile[field] = "   "
    _write(tmp_path, {"active": "mm", "models": {"mm": profile}})
    with pytest.raises(C.ConfigError, match=field):
        C.load_config()


@pytest.mark.parametrize("field", ["base_url", "model"])
def test_non_string_required_field_raises(tmp_path, monkeypatch, field):
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(tmp_path))
    profile = {
        "protocol": "openai",
        "base_url": "http://x/v1",
        "model": "m",
        "api_key_env": "K",
    }
    profile[field] = 123
    _write(tmp_path, {"active": "mm", "models": {"mm": profile}})
    with pytest.raises(C.ConfigError, match=field):
        C.load_config()


@pytest.mark.parametrize("bad_base_url", ["localhost:11434/v1", "ftp://example.com/v1"])
def test_invalid_base_url_raises(tmp_path, monkeypatch, bad_base_url):
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(tmp_path))
    _write(tmp_path, {"active": "mm", "models": {"mm": {
        "protocol": "openai",
        "base_url": bad_base_url,
        "model": "m",
        "api_key_env": "K",
    }}})
    with pytest.raises(C.ConfigError, match="base_url"):
        C.load_config()


def test_empty_profile_name_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(tmp_path))
    _write(tmp_path, {"active": "", "models": {"": {
        "protocol": "openai", "base_url": "http://x/v1", "model": "m", "api_key_env": "K",
    }}})
    with pytest.raises(C.ConfigError):
        C.load_config()


def test_profile_name_with_newline_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(tmp_path))
    _write(tmp_path, {"active": "bad\nname", "models": {"bad\nname": {
        "protocol": "openai", "base_url": "http://x/v1", "model": "m", "api_key_env": "K",
    }}})
    with pytest.raises(C.ConfigError):
        C.load_config()


def test_missing_api_key_env_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(tmp_path))
    _write(tmp_path, {"active": "mm", "models": {"mm": {
        "protocol": "openai", "base_url": "http://x/v1", "model": "m",
    }}})
    with pytest.raises(C.ConfigError):
        C.load_config()


def test_invalid_api_key_env_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(tmp_path))
    _write(tmp_path, {"active": "mm", "models": {"mm": {
        "protocol": "openai", "base_url": "http://x/v1", "model": "m",
        "api_key_env": "BAD-NAME",
    }}})
    with pytest.raises(C.ConfigError):
        C.load_config()


def test_bool_api_key_env_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(tmp_path))
    _write(tmp_path, {"active": "mm", "models": {"mm": {
        "protocol": "openai", "base_url": "http://x/v1", "model": "m",
        "api_key_env": True,
    }}})
    with pytest.raises(C.ConfigError, match="api_key_env"):
        C.load_config()


def test_model_with_newline_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(tmp_path))
    _write(tmp_path, {"active": "mm", "models": {"mm": {
        "protocol": "openai", "base_url": "http://x/v1", "model": "m\nbad", "api_key_env": "K",
    }}})
    with pytest.raises(C.ConfigError):
        C.load_config()


def test_malformed_json_raises_configerror(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(tmp_path))
    (tmp_path / "config.json").write_text("{ not valid json ,, }")
    with pytest.raises(C.ConfigError):
        C.load_config()


def test_invalid_utf8_config_raises_configerror(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(tmp_path))
    (tmp_path / "config.json").write_bytes(b"\xff\xfe{")
    with pytest.raises(C.ConfigError):
        C.load_config()


def test_non_object_config_raises_configerror(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(tmp_path))
    (tmp_path / "config.json").write_text("[]")
    with pytest.raises(C.ConfigError):
        C.load_config()


def test_models_must_be_object(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(tmp_path))
    _write(tmp_path, {"active": "mm", "models": ["mm"]})
    with pytest.raises(C.ConfigError):
        C.load_config()


def test_profile_must_be_object(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(tmp_path))
    _write(tmp_path, {"active": "mm", "models": {"mm": []}})
    with pytest.raises(C.ConfigError):
        C.load_config()


def test_invalid_utf8_dotenv_raises_configerror(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(tmp_path))
    _write(tmp_path, {"active": "mm", "models": {"mm": {
        "protocol": "openai", "base_url": "http://x/v1", "model": "m", "api_key_env": "K",
    }}})
    (tmp_path / ".env").write_bytes(b"\xff\xfeK=secret")

    with pytest.raises(C.ConfigError):
        C.load_config()


def test_invalid_protocol_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(tmp_path))
    _write(tmp_path, {"active": "mm", "models": {"mm": {"protocol": "anthropc",
           "base_url": "http://x/v1", "model": "m", "api_key_env": "K"}}})
    with pytest.raises(C.ConfigError):
        C.load_config()


def test_non_numeric_max_tokens_raises_configerror(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(tmp_path))
    _write(tmp_path, {"active": "mm", "models": {"mm": {"protocol": "openai",
           "base_url": "http://x/v1", "model": "m", "api_key_env": "K", "max_tokens": "abc"}}})
    with pytest.raises(C.ConfigError):
        C.load_config()


@pytest.mark.parametrize("field", ["max_tokens", "context_window"])
def test_bool_token_field_raises_configerror(tmp_path, monkeypatch, field):
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(tmp_path))
    profile = {
        "protocol": "openai",
        "base_url": "http://x/v1",
        "model": "m",
        "api_key_env": "K",
    }
    profile[field] = True
    _write(tmp_path, {"active": "mm", "models": {"mm": profile}})
    with pytest.raises(C.ConfigError):
        C.load_config()


@pytest.mark.parametrize("field", ["max_tokens", "context_window"])
def test_fractional_token_field_raises_configerror(tmp_path, monkeypatch, field):
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(tmp_path))
    profile = {
        "protocol": "openai",
        "base_url": "http://x/v1",
        "model": "m",
        "api_key_env": "K",
    }
    profile[field] = 3.5
    _write(tmp_path, {"active": "mm", "models": {"mm": profile}})
    with pytest.raises(C.ConfigError):
        C.load_config()


def test_non_positive_max_tokens_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(tmp_path))
    _write(tmp_path, {"active": "mm", "models": {"mm": {"protocol": "openai",
           "base_url": "http://x/v1", "model": "m", "api_key_env": "K", "context_window": 0}}})
    with pytest.raises(C.ConfigError):
        C.load_config()


def test_non_bool_multimodal_raises_configerror(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(tmp_path))
    _write(tmp_path, {"active": "mm", "models": {"mm": {"protocol": "openai",
           "base_url": "http://x/v1", "model": "m", "api_key_env": "K",
           "multimodal": "yes"}}})
    with pytest.raises(C.ConfigError, match="multimodal"):
        C.load_config()


def test_price_registered_into_pricing(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(tmp_path))
    _write(tmp_path, {"active": "mm", "models": {"mm": {"protocol": "anthropic",
           "base_url": "https://x", "model": "PricedModel", "api_key_env": "K",
           "price_in": 0.5, "price_out": 2.0}}}, env="K=k\n")
    C.load_config()
    from argos.core.observability import PRICING
    assert PRICING.get("PricedModel") == {"in": 0.5, "out": 2.0}


def test_negative_price_raises_configerror(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(tmp_path))
    _write(tmp_path, {"active": "mm", "models": {"mm": {"protocol": "openai",
           "base_url": "http://x/v1", "model": "m", "api_key_env": "K",
           "price_in": -1, "price_out": 2.0}}})
    with pytest.raises(C.ConfigError, match="price"):
        C.load_config()


def test_partial_price_raises_configerror(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(tmp_path))
    _write(tmp_path, {"active": "mm", "models": {"mm": {"protocol": "openai",
           "base_url": "http://x/v1", "model": "m", "api_key_env": "K",
           "price_in": 3.0}}})
    with pytest.raises(C.ConfigError, match="price"):
        C.load_config()


@pytest.mark.parametrize("bad_price", ["nan", "inf"])
def test_non_finite_price_raises_configerror(tmp_path, monkeypatch, bad_price):
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(tmp_path))
    _write(tmp_path, {"active": "mm", "models": {"mm": {"protocol": "openai",
           "base_url": "http://x/v1", "model": "m", "api_key_env": "K",
           "price_in": bad_price, "price_out": 2.0}}})
    with pytest.raises(C.ConfigError, match="price"):
        C.load_config()


@pytest.mark.parametrize("field", ["price_in", "price_out"])
def test_bool_price_raises_configerror(tmp_path, monkeypatch, field):
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(tmp_path))
    profile = {
        "protocol": "openai",
        "base_url": "http://x/v1",
        "model": "m",
        "api_key_env": "K",
        "price_in": 3.0,
        "price_out": 15.0,
    }
    profile[field] = True
    _write(tmp_path, {"active": "mm", "models": {"mm": profile}})
    with pytest.raises(C.ConfigError, match="price"):
        C.load_config()


def test_legacy_env_fallback_when_no_config(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("ARGOS_LLM_KEY", "legacykey")
    monkeypatch.setenv("ARGOS_LLM_MODEL", "MiniMax-M3")
    import importlib
    from argos import config as C2
    importlib.reload(C2)
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(tmp_path))
    tier = C2.active_tier()
    assert tier.model == "MiniMax-M3" and tier.protocol == "anthropic"
    assert C2.active_key() == "legacykey"


def test_set_active_persists(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(tmp_path))
    import json
    (tmp_path / "config.json").write_text(json.dumps({"active": "a", "models": {
        "a": {"protocol": "openai", "base_url": "http://x/v1", "model": "m1", "api_key_env": "AK"},
        "b": {"protocol": "openai", "base_url": "http://y/v1", "model": "m2", "api_key_env": "BK"}}}))
    assert set(C.list_profiles()) == {"a", "b"}
    C.set_active("b")
    assert json.loads((tmp_path / "config.json").read_text())["active"] == "b"
    with pytest.raises(C.ConfigError):
        C.set_active("ghost")


def test_set_active_name_must_be_string(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(tmp_path))
    import json
    (tmp_path / "config.json").write_text(json.dumps({"active": "a", "models": {
        "a": {"protocol": "openai", "base_url": "http://x/v1", "model": "m1", "api_key_env": "AK"},
    }}))

    with pytest.raises(C.ConfigError):
        C.set_active(["a"])  # type: ignore[arg-type]


def test_key_for_unknown_profile_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(tmp_path))
    _write(tmp_path, {"active": "a", "models": {
        "a": {"protocol": "openai", "base_url": "http://x/v1", "model": "m1", "api_key_env": "AK"},
    }})

    with pytest.raises(C.ConfigError, match="ghost"):
        C.key_for("ghost")


@pytest.mark.parametrize("lookup", [C.tier_for, C.key_for])
def test_profile_lookup_name_must_be_string(tmp_path, monkeypatch, lookup):
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(tmp_path))
    _write(tmp_path, {"active": "a", "models": {
        "a": {"protocol": "openai", "base_url": "http://x/v1", "model": "m1", "api_key_env": "AK"},
    }})

    with pytest.raises(C.ConfigError):
        lookup(["a"])


def test_key_for_unknown_profile_without_config_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(C, "DEFAULT_KEYS", ["legacy"])

    with pytest.raises(C.ConfigError, match="ghost"):
        C.key_for("ghost")


def test_set_active_rejects_malformed_target(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(tmp_path))
    import json
    (tmp_path / "config.json").write_text(json.dumps({"active": "good", "models": {
        "good": {"protocol": "openai", "base_url": "http://x/v1", "model": "m", "api_key_env": "K"},
        "bad": {"protocol": "bogus", "base_url": "http://y/v1", "model": "m2", "api_key_env": "K2"}}}))
    with pytest.raises(C.ConfigError):
        C.set_active("bad")
    assert json.loads((tmp_path / "config.json").read_text())["active"] == "good"


def test_set_active_keeps_existing_config_when_write_is_partial(tmp_path, monkeypatch):
    import pathlib

    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(tmp_path))
    original = {"active": "a", "models": {
        "a": {"protocol": "openai", "base_url": "http://x/v1", "model": "m1", "api_key_env": "AK"},
        "b": {"protocol": "openai", "base_url": "http://y/v1", "model": "m2", "api_key_env": "BK"},
    }}
    (tmp_path / "config.json").write_text(json.dumps(original))
    real_write_text = pathlib.Path.write_text

    def partial_config_write(self, text, *args, **kwargs):
        if self.name == "config.json.tmp":
            real_write_text(self, "{partial", *args, **kwargs)
            raise OSError("partial write")
        return real_write_text(self, text, *args, **kwargs)

    monkeypatch.setattr(pathlib.Path, "write_text", partial_config_write)

    with pytest.raises(OSError, match="partial write"):
        C.set_active("b")

    assert json.loads((tmp_path / "config.json").read_text()) == original
    assert not (tmp_path / "config.json.tmp").exists()


def test_set_active_corrupt_config_raises_config_error(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(tmp_path))
    (tmp_path / "config.json").write_text("{ not json")

    with pytest.raises(C.ConfigError):
        C.set_active("anything")


def test_set_active_non_object_config_raises_config_error(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(tmp_path))
    (tmp_path / "config.json").write_text("[]")

    with pytest.raises(C.ConfigError):
        C.set_active("anything")


def test_set_active_models_must_be_object(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(tmp_path))
    _write(tmp_path, {"active": "mm", "models": ["mm"]})

    with pytest.raises(C.ConfigError):
        C.set_active("mm")


def test_active_embedder_openai_with_embedding_model(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(tmp_path))
    _write(tmp_path, {"active": "o", "models": {"o": {"protocol": "openai",
           "base_url": "http://localhost:11434/v1", "model": "qwen", "api_key_env": "OK",
           "embedding_model": "nomic-embed-text"}}}, env="OK=k\n")
    emb = C.active_embedder()
    from argos.memory.embedding import OpenAIEmbedder
    assert isinstance(emb, OpenAIEmbedder)
    assert emb._model == "nomic-embed-text" and emb._base == "http://localhost:11434/v1"


@pytest.mark.parametrize("embedding_model", [123, "embed\nbad", "   "])
def test_invalid_embedding_model_raises_configerror(tmp_path, monkeypatch, embedding_model):
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(tmp_path))
    _write(tmp_path, {"active": "o", "models": {"o": {"protocol": "openai",
           "base_url": "http://localhost:11434/v1", "model": "qwen", "api_key_env": "OK",
           "embedding_model": embedding_model}}}, env="OK=k\n")

    with pytest.raises(C.ConfigError, match="embedding_model"):
        C.load_config()


def test_active_embedder_none_without_embedding_model(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(tmp_path))
    _write(tmp_path, {"active": "o", "models": {"o": {"protocol": "openai",
           "base_url": "http://x/v1", "model": "m", "api_key_env": "OK"}}}, env="OK=k\n")
    assert C.active_embedder() is None


def test_active_embedder_none_for_anthropic(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(tmp_path))
    _write(tmp_path, {"active": "a", "models": {"a": {"protocol": "anthropic",
           "base_url": "https://api.anthropic.com", "model": "claude-sonnet-4-6",
           "api_key_env": "AK", "embedding_model": "whatever"}}}, env="AK=k\n")
    assert C.active_embedder() is None


def test_active_embedder_none_without_config(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(tmp_path / "empty"))
    assert C.active_embedder() is None
