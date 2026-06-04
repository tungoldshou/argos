# tests/test_setup_wizard.py
import json
import os
import stat
import pytest
from argos_agent.setup_wizard import PRESETS, write_profile


def test_presets_have_protocol_and_base_url():
    for name, p in PRESETS.items():
        assert p["protocol"] in ("anthropic", "openai")
        assert "base_url" in p


def test_write_profile_splits_secret_and_settings(tmp_path):
    write_profile(
        config_dir=tmp_path, name="mm", protocol="anthropic",
        base_url="https://x/anthropic", model="MiniMax-M3",
        api_key="secret123", api_key_env="MM_KEY",
        max_tokens=4096, context_window=192000, price_in=0.3, price_out=1.2,
        set_active=True,
    )
    cfg = json.loads((tmp_path / "config.json").read_text())
    assert cfg["active"] == "mm"
    prof = cfg["models"]["mm"]
    assert prof["model"] == "MiniMax-M3" and prof["api_key_env"] == "MM_KEY"
    assert "api_key" not in prof and "secret123" not in json.dumps(cfg)   # 密钥不进 config
    env = (tmp_path / ".env").read_text()
    assert "MM_KEY=secret123" in env                                       # 密钥进 .env
    mode = stat.S_IMODE(os.stat(tmp_path / ".env").st_mode)
    assert mode == 0o600                                                    # .env 权限 0600


def test_write_profile_env_reference_only_no_secret(tmp_path):
    """选'用已有环境变量'路径:只记 api_key_env,不写密钥进 .env。"""
    write_profile(config_dir=tmp_path, name="o", protocol="openai",
                  base_url="http://x/v1", model="m", api_key=None,
                  api_key_env="MY_EXISTING_ENV", set_active=True)
    assert not (tmp_path / ".env").exists() or "MY_EXISTING_ENV" not in (tmp_path / ".env").read_text()
    cfg = json.loads((tmp_path / "config.json").read_text())
    assert cfg["models"]["o"]["api_key_env"] == "MY_EXISTING_ENV"


def test_write_profile_appends_to_existing_config(tmp_path):
    write_profile(config_dir=tmp_path, name="a", protocol="openai", base_url="http://x/v1",
                  model="m1", api_key="k1", api_key_env="A_KEY", set_active=True)
    write_profile(config_dir=tmp_path, name="b", protocol="openai", base_url="http://y/v1",
                  model="m2", api_key="k2", api_key_env="B_KEY", set_active=False)
    cfg = json.loads((tmp_path / "config.json").read_text())
    assert set(cfg["models"]) == {"a", "b"} and cfg["active"] == "a"   # 第二个 set_active=False
    assert "A_KEY=k1" in (tmp_path / ".env").read_text()
    assert "B_KEY=k2" in (tmp_path / ".env").read_text()
