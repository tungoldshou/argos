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


# ── Task 8: 连通 + 格式探针 ─────────────────────────────────────────────────────

import httpx
from argos_agent.setup_wizard import probe_connection, ProbeResult


def _mock_client(handler):
    from argos_agent.core.models import ModelClient, CredentialPool, ModelTier
    def make(tier, key):
        return ModelClient(tier=tier, pool=CredentialPool([key or "x"]),
                           transport=httpx.MockTransport(handler))
    return make


@pytest.mark.asyncio
async def test_probe_connection_fenced_python_ok():
    sse = (b'data: {"choices":[{"delta":{"content":"```python\\nprint(\'ok\')\\n```"}}]}\n\n'
           b'data: {"choices":[{"finish_reason":"stop","delta":{}}]}\n\n')
    res = await probe_connection(protocol="openai", base_url="http://x/v1", model="m",
                                 api_key="k", client_factory=_mock_client(
                                     lambda r: httpx.Response(200, content=sse)))
    assert res.connected is True and res.codeact_ok is True and res.rating == "行"


@pytest.mark.asyncio
async def test_probe_connection_no_fence_warns():
    sse = (b'data: {"choices":[{"delta":{"content":"{\\"name\\":\\"run\\"}"}}]}\n\n'
           b'data: {"choices":[{"finish_reason":"stop","delta":{}}]}\n\n')
    res = await probe_connection(protocol="openai", base_url="http://x/v1", model="m",
                                 api_key="k", client_factory=_mock_client(
                                     lambda r: httpx.Response(200, content=sse)))
    assert res.connected is True and res.codeact_ok is False and res.rating == "勉强"
    assert "CodeAct" in res.message or "围栏" in res.message


@pytest.mark.asyncio
async def test_probe_connection_http_error_honest():
    res = await probe_connection(protocol="openai", base_url="http://x/v1", model="m",
                                 api_key="bad", client_factory=_mock_client(
                                     lambda r: httpx.Response(401, text="invalid api key")))
    assert res.connected is False and res.rating == "不行"
    assert "401" in res.message


# ── Task 9: argos setup 子命令 + 交互 run ────────────────────────────────────────

from argos_agent.setup_wizard import run


@pytest.mark.asyncio
async def test_run_wizard_happy_path(tmp_path, monkeypatch):
    """脚本化输入跑完一轮:选 MiniMax 预设→默认 model→粘贴 key→跳过深探→不再加→完成。"""
    inputs = iter([
        "3",            # 选 MiniMax(PRESETS 第 3 项,实现里编号要稳定)
        "",             # model 用默认 MiniMax-M3
        "paste",        # key 方式:粘贴
        "secret123",    # key 值
        "",             # max_tokens 默认
        "",             # context_window 默认
        "",             # price 跳过
        "n",            # 深度探针 跳过
        "n",            # 不再加模型
    ])
    out_lines = []
    # probe 注入成功(避免真网络):monkeypatch probe_connection
    import argos_agent.setup_wizard as W
    async def fake_probe(**kw):
        return W.ProbeResult(True, True, "行", "OK")
    monkeypatch.setattr(W, "probe_connection", fake_probe)
    await run(reader=lambda prompt="": next(inputs), writer=out_lines.append,
              config_dir=tmp_path)
    import json
    cfg = json.loads((tmp_path / "config.json").read_text())
    assert cfg["active"] in cfg["models"]
    assert any(m["model"] == "MiniMax-M3" for m in cfg["models"].values())
    assert "secret123" in (tmp_path / ".env").read_text()
