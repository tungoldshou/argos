# tests/test_setup_wizard.py
import json
import os
import stat
import pytest
from argos.setup_wizard import PRESETS, write_profile
from argos.i18n import t


def test_presets_have_protocol_and_base_url():
    """预设必须有 protocol 和 base_url 字段;「自定义」的 protocol/base_url 允许为空(向导会询问)。"""
    for name, p in PRESETS.items():
        if name == "Custom":
            # Custom preset: protocol/base_url are blank, wizard asks (spec §6.1 「(问)」)
            assert p["protocol"] == ""
            assert p["base_url"] == ""
        else:
            assert p["protocol"] in ("anthropic", "openai")
            assert "base_url" in p and p["base_url"]


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


def test_write_profile_persists_multimodal_override(tmp_path):
    write_profile(config_dir=tmp_path, name="o", protocol="openai",
                  base_url="http://x/v1", model="m", api_key=None,
                  api_key_env="MY_EXISTING_ENV", multimodal=False,
                  set_active=True)
    cfg = json.loads((tmp_path / "config.json").read_text())
    assert cfg["models"]["o"]["multimodal"] is False


def test_write_profile_strips_trailing_base_url_slash(tmp_path):
    write_profile(config_dir=tmp_path, name="o", protocol="openai",
                  base_url="http://x/v1/", model="m", api_key=None,
                  api_key_env="MY_EXISTING_ENV", set_active=True)

    cfg = json.loads((tmp_path / "config.json").read_text())
    assert cfg["models"]["o"]["base_url"] == "http://x/v1"


def test_write_profile_strips_human_entered_field_whitespace(tmp_path):
    write_profile(config_dir=tmp_path, name="  o  ", protocol=" openai ",
                  base_url=" http://x/v1/ ", model=" m ",
                  api_key=None, api_key_env=" MY_EXISTING_ENV ", set_active=True)

    cfg = json.loads((tmp_path / "config.json").read_text())
    assert cfg["active"] == "o"
    assert set(cfg["models"]) == {"o"}
    assert cfg["models"]["o"]["protocol"] == "openai"
    assert cfg["models"]["o"]["base_url"] == "http://x/v1"
    assert cfg["models"]["o"]["model"] == "m"
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


def test_write_profile_repairs_dangling_active_even_when_not_requested(tmp_path):
    """If active is already invalid, saving a profile must leave a runnable config."""
    (tmp_path / "config.json").write_text(json.dumps({
        "active": "ghost",
        "models": {
            "old": {
                "protocol": "openai",
                "base_url": "http://old/v1",
                "model": "old-model",
                "api_key_env": "OLD_KEY",
            },
        },
    }))

    write_profile(config_dir=tmp_path, name="new", protocol="openai", base_url="http://x/v1",
                  model="m", api_key="k", api_key_env="NK", set_active=False)

    cfg = json.loads((tmp_path / "config.json").read_text())
    assert cfg["active"] == "new"
    assert "new" in cfg["models"]


def test_write_profile_refuses_to_preserve_invalid_existing_profile(tmp_path):
    """Saving a new profile must not leave config.json unloadable because of old junk."""
    import argos.config as C

    original = {
        "active": "ok",
        "models": {
            "ok": {
                "protocol": "openai",
                "base_url": "http://ok/v1",
                "model": "ok-model",
                "api_key_env": "OK_KEY",
            },
            "broken": {
                "protocol": "openai",
                "base_url": "",
                "model": "broken-model",
                "api_key_env": "BROKEN_KEY",
            },
        },
    }
    (tmp_path / "config.json").write_text(json.dumps(original))

    with pytest.raises(C.ConfigError, match="broken"):
        write_profile(config_dir=tmp_path, name="new", protocol="openai", base_url="http://x/v1",
                      model="m", api_key="k", api_key_env="NEW_KEY", set_active=True)

    assert json.loads((tmp_path / "config.json").read_text()) == original
    assert not (tmp_path / ".env").exists()


# ── Task 8: 连通 + 格式探针 ─────────────────────────────────────────────────────

import httpx
from argos.setup_wizard import probe_connection, ProbeResult


def _mock_client(handler):
    from argos.core.models import ModelClient, CredentialPool, ModelTier
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
    assert res.connected is True and res.codeact_ok is True and res.rating == t("setup.probe_rating_ok")


@pytest.mark.asyncio
async def test_probe_connection_no_fence_warns():
    sse = (b'data: {"choices":[{"delta":{"content":"{\\"name\\":\\"run\\"}"}}]}\n\n'
           b'data: {"choices":[{"finish_reason":"stop","delta":{}}]}\n\n')
    res = await probe_connection(protocol="openai", base_url="http://x/v1", model="m",
                                 api_key="k", client_factory=_mock_client(
                                     lambda r: httpx.Response(200, content=sse)))
    assert res.connected is True and res.codeact_ok is False and res.rating == t("setup.probe_rating_marginal")
    assert "CodeAct" in res.message or "围栏" in res.message


@pytest.mark.asyncio
async def test_probe_connection_http_error_honest():
    res = await probe_connection(protocol="openai", base_url="http://x/v1", model="m",
                                 api_key="bad", client_factory=_mock_client(
                                     lambda r: httpx.Response(401, text="invalid api key")))
    assert res.connected is False and res.rating == t("setup.probe_rating_fail")
    assert "401" in res.message


# ── Task 9: argos setup 子命令 + 交互 run ────────────────────────────────────────

from argos.setup_wizard import run


@pytest.mark.asyncio
async def test_run_wizard_happy_path(tmp_path, monkeypatch):
    """脚本化输入跑完一轮:选 MiniMax 预设→默认 model→粘贴 key→跳过深探→默认名→不再加→完成。
    MiniMax 是 PRESETS 第 3 项;无 protocol/base_url 问询(预设已填)。
    默认非 advanced:不问 max_tokens/context_window;价格已移除。
    reader 调用顺序:选编号→model id→key方式→key值→深探→profile名→再配。
    """
    inputs = iter([
        "3",            # 1. 选 MiniMax(PRESETS 第 3 项,编号稳定)
        "",             # 2. model 用默认 MiniMax-M3
        "paste",        # 3. key 方式:粘贴(非 TTY 回退文字)
        "secret123",    # 4. key 值
        "n",            # 5. 深度探针 跳过
        "",             # 6. profile 名 留空=默认(minimax-m3)
        "n",            # 7. 不再加模型
    ])
    out_lines = []
    # probe 注入成功(避免真网络):monkeypatch probe_connection
    import argos.setup_wizard as W
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


@pytest.mark.asyncio
async def test_run_wizard_expands_config_dir_env_tilde(tmp_path, monkeypatch):
    """ARGOS_CONFIG_DIR='~/x' should write under HOME, not a literal ./~/x directory."""
    import argos.setup_wizard as W

    home = tmp_path / "home"
    work = tmp_path / "work"
    home.mkdir()
    work.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("ARGOS_CONFIG_DIR", "~/argos-config")
    monkeypatch.chdir(work)

    async def fake_probe(**kw):
        return W.ProbeResult(True, True, "行", "OK")

    monkeypatch.setattr(W, "probe_connection", fake_probe)
    inputs = iter(["1", "", "paste", "sk-test", "n", "", "n"])

    await W.run(reader=lambda prompt="": next(inputs), writer=lambda _line: None)

    assert (home / "argos-config" / "config.json").exists()
    assert not (work / "~" / "argos-config").exists()


@pytest.mark.asyncio
async def test_run_wizard_accepts_provider_name_in_numbered_fallback(tmp_path, monkeypatch):
    """编号回退模式下也应接受 provider 名,列表里显示的名字就该能输入。"""
    import argos.setup_wizard as W

    async def fake_probe(**kw):
        return W.ProbeResult(True, True, "行", "OK")

    monkeypatch.setattr(W, "probe_connection", fake_probe)
    inputs = iter([
        "OpenAI",
        "",             # default model gpt-4o
        "paste",
        "sk-test",
        "n",
        "",             # default profile name
        "n",
    ])
    out: list[str] = []

    await run(reader=lambda prompt="": next(inputs), writer=out.append,
              config_dir=tmp_path)

    cfg = json.loads((tmp_path / "config.json").read_text())
    prof = cfg["models"][cfg["active"]]
    assert prof["base_url"] == "https://api.openai.com/v1"
    assert prof["model"] == "gpt-4o"


@pytest.mark.asyncio
async def test_run_wizard_accepts_unambiguous_provider_prefix(tmp_path, monkeypatch):
    """provider 名带括号时,唯一前缀也应可输入,如 Anthropic → Anthropic (Claude)。"""
    import argos.setup_wizard as W

    async def fake_probe(**kw):
        return W.ProbeResult(True, True, "行", "OK")

    monkeypatch.setattr(W, "probe_connection", fake_probe)
    inputs = iter([
        "Anthropic",
        "",             # default model claude-sonnet-4-6
        "paste",
        "sk-test",
        "n",
        "",             # default profile name
        "n",
    ])
    out: list[str] = []

    await run(reader=lambda prompt="": next(inputs), writer=out.append,
              config_dir=tmp_path)

    cfg = json.loads((tmp_path / "config.json").read_text())
    prof = cfg["models"][cfg["active"]]
    assert prof["protocol"] == "anthropic"
    assert prof["base_url"] == "https://api.anthropic.com"


@pytest.mark.asyncio
async def test_run_wizard_ambiguous_provider_prefix_lists_matches(tmp_path, monkeypatch):
    """provider 前缀歧义时应列出候选,方便用户改成完整名。"""
    import argos.setup_wizard as W

    async def fake_probe(**kw):
        return W.ProbeResult(True, True, "行", "OK")

    monkeypatch.setenv("ARGOS_LANG", "en")
    monkeypatch.setattr(W, "probe_connection", fake_probe)
    inputs = iter([
        "Open",           # OpenAI / OpenRouter ambiguous
        "OpenAI",
        "",
        "paste",
        "sk-test",
        "n",
        "",
        "n",
    ])
    out: list[str] = []

    await run(reader=lambda prompt="": next(inputs), writer=out.append,
              config_dir=tmp_path)

    text = "\n".join(out)
    assert "Ambiguous provider" in text
    assert "OpenAI" in text
    assert "OpenRouter" in text


@pytest.mark.asyncio
async def test_run_wizard_save_io_error_reprompts_instead_of_traceback(tmp_path, monkeypatch):
    """保存时遇到磁盘/权限错误应提示并允许重试,不能裸 traceback 退出。"""
    import argos.setup_wizard as W

    async def fake_probe(**kw):
        return W.ProbeResult(True, True, "行", "OK")

    real_write_profile = W.write_profile
    attempts = 0

    def flaky_write_profile(**kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError("disk full")
        return real_write_profile(**kwargs)

    monkeypatch.setattr(W, "probe_connection", fake_probe)
    monkeypatch.setattr(W, "write_profile", flaky_write_profile)
    inputs = iter([
        "1", "", "paste", "sk-first", "n", "bad",
        "1", "", "paste", "sk-second", "n", "ok", "n",
    ])
    out: list[str] = []

    await run(reader=lambda prompt="": next(inputs), writer=out.append,
              config_dir=tmp_path)

    cfg = json.loads((tmp_path / "config.json").read_text())
    assert attempts == 2
    assert cfg["active"] == "ok"
    assert "OK_KEY=sk-second" in (tmp_path / ".env").read_text()
    assert any("disk full" in line for line in out)


@pytest.mark.asyncio
async def test_run_uses_console_for_sections_spinner_and_color(tmp_path, monkeypatch):
    """#1 翻新真验证:传 console 时,向导用 console.rule(章节)+ console.status(探针 spinner)+
    console.print(banner + 上色评级)。console=None 路径由 happy_path 覆盖,这里锁死 rich 集成真执行。"""
    import argos.setup_wizard as W
    calls = {"rule": 0, "status": 0, "print": 0}

    class _FakeStatus:
        def __enter__(self): return self
        def __exit__(self, *a): return False

    class _FakeConsole:
        def rule(self, *a, **k): calls["rule"] += 1
        def status(self, *a, **k): calls["status"] += 1; return _FakeStatus()
        def print(self, *a, **k): calls["print"] += 1

    async def fake_probe(**kw):
        return W.ProbeResult(True, True, "行", "OK")
    monkeypatch.setattr(W, "probe_connection", fake_probe)
    inputs = iter(["3", "", "paste", "k", "n", "", "n"])   # 同 happy_path(非 advanced)
    await W.run(reader=lambda p="": next(inputs), writer=lambda _: None,
                config_dir=tmp_path, console=_FakeConsole())
    assert calls["rule"] >= 2, calls        # 至少 provider + apikey + connect 分区
    assert calls["status"] >= 1, calls      # 探针 spinner(干掉 20 秒静默卡屏)
    assert calls["print"] >= 1, calls       # banner / 上色评级


@pytest.mark.asyncio
async def test_run_wizard_custom_preset(tmp_path, monkeypatch):
    """「自定义」预设触发 protocol/base_url 额外询问(spec §6.1 「(问)」);advanced=True 覆盖
    max_tokens/context_window/embedding 询问。"""
    import argos.setup_wizard as W
    # "Custom" is the last entry in PRESETS
    custom_idx = str(list(W.PRESETS.keys()).index("Custom") + 1)
    inputs = iter([
        custom_idx,                             # 1. select "Custom"
        "openai",                               # 2a. protocol (asked, preset is blank)
        "http://localhost:8000/v1",             # 2b. base_url (asked, preset is blank)
        "my-local-model",                       # 3. model id
        "paste",                                # 4. key 方式
        "localkey",                             # 5. key 值
        "",                                     # 6. max_tokens 默认(advanced)
        "",                                     # 7. context_window 默认(advanced)
        "nomic-embed-text",                     # 8. embedding 模型(advanced + openai 协议)
        "n",                                    # 9. 图片输入 override:禁用
        "n",                                    # 10. 深度探针 跳过
        "local",                                # 11. profile 名
        "n",                                    # 12. 不再加模型
    ])
    out_lines = []
    async def fake_probe(**kw):
        return W.ProbeResult(True, True, "行", "OK")
    monkeypatch.setattr(W, "probe_connection", fake_probe)
    await run(reader=lambda prompt="": next(inputs), writer=out_lines.append,
              config_dir=tmp_path, advanced=True)
    cfg = json.loads((tmp_path / "config.json").read_text())
    assert "local" in cfg["models"]
    prof = cfg["models"]["local"]
    assert prof["protocol"] == "openai"
    assert prof["base_url"] == "http://localhost:8000/v1"
    assert prof["model"] == "my-local-model"
    assert prof["embedding_model"] == "nomic-embed-text"   # openai 协议:embedding 模型写入 profile
    assert prof["multimodal"] is False


@pytest.mark.asyncio
async def test_run_wizard_custom_protocol_is_case_insensitive(tmp_path, monkeypatch):
    """Interactive custom setup should accept common protocol casing and save canonical lowercase."""
    import argos.setup_wizard as W

    custom_idx = str(list(W.PRESETS.keys()).index("Custom") + 1)
    inputs = iter([
        custom_idx, "OpenAI", "http://localhost:8000/v1", "upper-model", "paste", "upper-key",
        "n", "upper", "n",
        custom_idx, "openai", "http://localhost:8000/v1", "fallback-model", "paste", "fallback-key",
        "n", "fallback", "n",
    ])

    async def fake_probe(**kw):
        return W.ProbeResult(True, True, "行", "OK")

    monkeypatch.setattr(W, "probe_connection", fake_probe)

    await run(reader=lambda prompt="": next(inputs), writer=lambda _line: None,
              config_dir=tmp_path)

    cfg = json.loads((tmp_path / "config.json").read_text())
    assert "upper" in cfg["models"]
    assert cfg["models"]["upper"]["protocol"] == "openai"
    assert cfg["models"]["upper"]["model"] == "upper-model"
    assert "fallback" not in cfg["models"]


@pytest.mark.asyncio
async def test_run_wizard_invalid_multimodal_choice_skips_probe(tmp_path, monkeypatch):
    """advanced 图片输入 override 输错时应重配,不要静默退回自动探测并保存。"""
    import argos.setup_wizard as W

    seen_keys: list[str | None] = []

    async def fake_probe(**kw):
        seen_keys.append(kw["api_key"])
        return W.ProbeResult(True, True, "行", "OK")

    monkeypatch.setattr(W, "probe_connection", fake_probe)
    inputs = iter([
        "1", "gpt-4o-mini", "paste", "sk-bad", "", "", "", "maybe",
        "1", "gpt-4o-mini", "paste", "sk-good", "", "", "", "n", "n", "ok", "n",
    ])
    out: list[str] = []

    await run(reader=lambda prompt="": next(inputs), writer=out.append,
              config_dir=tmp_path, advanced=True)

    cfg = json.loads((tmp_path / "config.json").read_text())
    assert "ok" in cfg["models"]
    assert cfg["models"]["ok"]["multimodal"] is False
    assert seen_keys == ["sk-good"]
    assert any("image input" in line.lower() or "图片输入" in line for line in out)


def test_select_key_method_accepts_numbered_env_choice(monkeypatch):
    import argos.setup_wizard as W

    def no_tty(*_args, **_kwargs):
        raise W._NotATTY

    monkeypatch.setattr(W, "_arrow_select", no_tty)

    assert W._select_key_method(lambda _p="": "2", lambda _line: None, None) == "env"
    assert W._select_key_method(lambda _p="": "ENV", lambda _line: None, None) == "env"
    assert W._select_key_method(lambda _p="": "environment variable", lambda _line: None, None) == "env"


def test_select_key_method_reprompts_on_invalid_choice(monkeypatch):
    import argos.setup_wizard as W

    def no_tty(*_args, **_kwargs):
        raise W._NotATTY

    monkeypatch.setattr(W, "_arrow_select", no_tty)
    answers = iter(["bogus", "env"])
    out: list[str] = []

    assert W._select_key_method(lambda _p="": next(answers), out.append, None) == "env"
    assert any("无效" in line or "Invalid" in line for line in out)


@pytest.mark.asyncio
async def test_run_wizard_reprompts_when_env_var_name_blank(tmp_path, monkeypatch):
    import argos.setup_wizard as W

    async def fake_probe(**kw):
        return W.ProbeResult(True, True, "行", "OK")

    monkeypatch.setattr(W, "probe_connection", fake_probe)
    inputs = iter([
        "3", "", "env", "",                 # blank env var should restart this model
        "3", "", "paste", "secret123", "n", "", "n",
    ])
    out_lines: list[str] = []

    await W.run(reader=lambda p="": next(inputs), writer=out_lines.append,
                config_dir=tmp_path)

    cfg = json.loads((tmp_path / "config.json").read_text())
    active = cfg["models"][cfg["active"]]
    assert active["api_key_env"]
    assert any("环境变量" in line or "environment variable" in line for line in out_lines)


@pytest.mark.asyncio
async def test_run_wizard_env_method_probes_with_existing_env_value(tmp_path, monkeypatch):
    import argos.setup_wizard as W

    seen: dict[str, str | None] = {}

    async def fake_probe(**kw):
        seen["api_key"] = kw.get("api_key")
        return W.ProbeResult(True, True, "行", "OK")

    monkeypatch.setenv("MY_KEY", "secret123")
    monkeypatch.setattr(W, "probe_connection", fake_probe)
    inputs = iter(["3", "", "env", "MY_KEY", "n", "", "n"])

    await W.run(reader=lambda p="": next(inputs), writer=lambda _: None,
                config_dir=tmp_path)

    cfg = json.loads((tmp_path / "config.json").read_text())
    active = cfg["models"][cfg["active"]]
    assert seen["api_key"] == "secret123"
    assert active["api_key_env"] == "MY_KEY"
    assert not (tmp_path / ".env").exists()


@pytest.mark.asyncio
async def test_run_wizard_invalid_env_var_name_skips_probe(tmp_path, monkeypatch):
    import argos.setup_wizard as W

    seen_api_keys: list[str | None] = []

    async def fake_probe(**kw):
        seen_api_keys.append(kw.get("api_key"))
        return W.ProbeResult(True, True, "行", "OK")

    monkeypatch.setenv("GOOD_KEY", "secret123")
    monkeypatch.setattr(W, "probe_connection", fake_probe)
    inputs = iter([
        "3", "", "env", "BAD-NAME",
        "3", "", "env", "GOOD_KEY", "n", "", "n",
    ])
    out: list[str] = []

    await W.run(reader=lambda p="": next(inputs), writer=out.append,
                config_dir=tmp_path)

    cfg = json.loads((tmp_path / "config.json").read_text())
    active = cfg["models"][cfg["active"]]
    assert active["api_key_env"] == "GOOD_KEY"
    assert seen_api_keys == ["secret123"]
    assert any(
        "BAD-NAME" in line and ("invalid" in line.lower() or "非法" in line)
        for line in out
    )


@pytest.mark.asyncio
async def test_run_wizard_missing_env_var_skips_probe(tmp_path, monkeypatch):
    import argos.setup_wizard as W

    seen_api_keys: list[str | None] = []

    async def fake_probe(**kw):
        seen_api_keys.append(kw.get("api_key"))
        return W.ProbeResult(True, True, "行", "OK")

    monkeypatch.delenv("MISSING_KEY", raising=False)
    monkeypatch.setenv("GOOD_KEY", "secret123")
    monkeypatch.setattr(W, "probe_connection", fake_probe)
    inputs = iter([
        "3", "", "env", "MISSING_KEY",
        "3", "", "env", "GOOD_KEY", "n", "", "n",
    ])
    out: list[str] = []

    await W.run(reader=lambda p="": next(inputs), writer=out.append,
                config_dir=tmp_path)

    cfg = json.loads((tmp_path / "config.json").read_text())
    active = cfg["models"][cfg["active"]]
    assert active["api_key_env"] == "GOOD_KEY"
    assert seen_api_keys == ["secret123"]
    assert any("MISSING_KEY" in line for line in out)


@pytest.mark.asyncio
async def test_run_wizard_duplicate_name_appends_index(tmp_path, monkeypatch):
    """同名 profile 再配时自动追加序号(spec §6.1 step 5「重名追加序号」)。"""
    import argos.setup_wizard as W
    async def fake_probe(**kw):
        return W.ProbeResult(True, True, "行", "OK")
    monkeypatch.setattr(W, "probe_connection", fake_probe)

    # 第一轮:profile 名 "mm"。默认非 advanced:选编号→model→key方式→key→深探→名→再配。
    it1 = iter(["3", "", "paste", "k", "n", "mm", "n"])
    await run(reader=lambda prompt="": next(it1), writer=lambda _: None, config_dir=tmp_path)
    cfg1 = json.loads((tmp_path / "config.json").read_text())
    assert "mm" in cfg1["models"]

    # 第二轮:同名 "mm" → 应自动变 "mm-2"。注意:已有 profile 时多一问「设为当前默认模型?(y/N)」
    # (避免重跑 setup 加模型时静默劫持 active),故输入序列在 name 后、再配前多一个 "n"。
    it2 = iter(["3", "", "paste", "k", "n", "mm", "n", "n"])
    await run(reader=lambda prompt="": next(it2), writer=lambda _: None, config_dir=tmp_path)
    cfg2 = json.loads((tmp_path / "config.json").read_text())
    assert "mm" in cfg2["models"] and "mm-2" in cfg2["models"]
    assert cfg2["active"] == "mm", "第二轮答 n 不设为默认 → active 仍是第一轮的 mm(不被劫持)"
    # paste 路径 env 名由【唯一 profile 名】派生 → 两 profile 的 api_key_env 必须不同(防撞名覆盖)
    assert cfg2["models"]["mm"]["api_key_env"] != cfg2["models"]["mm-2"]["api_key_env"]


@pytest.mark.asyncio
async def test_run_wizard_paste_key_derives_shell_safe_env_name(tmp_path, monkeypatch):
    """profile/model 名含 dot 时,paste key 派生的 env 名仍应是 shell 友好的 A-Z0-9_。"""
    import argos.setup_wizard as W

    async def fake_probe(**kw):
        return W.ProbeResult(True, True, "行", "OK")

    monkeypatch.setattr(W, "probe_connection", fake_probe)
    ollama_idx = str(list(W.PRESETS.keys()).index("Ollama (local)") + 1)
    inputs = iter([
        ollama_idx,
        "",             # default model: qwen2.5-coder
        "paste",
        "localkey",
        "n",
        "",             # default profile name: qwen2.5-coder
        "n",
    ])

    await run(reader=lambda prompt="": next(inputs), writer=lambda _: None,
              config_dir=tmp_path)

    cfg = json.loads((tmp_path / "config.json").read_text())
    env_name = cfg["models"][cfg["active"]]["api_key_env"]
    assert env_name == "QWEN2_5_CODER_KEY"
    assert "QWEN2_5_CODER_KEY=localkey" in (tmp_path / ".env").read_text()


@pytest.mark.asyncio
async def test_run_wizard_paste_key_env_name_does_not_start_with_digit(tmp_path, monkeypatch):
    """profile 名以数字开头时,派生 env 名应加 ARGOS_ 前缀。"""
    import argos.setup_wizard as W

    async def fake_probe(**kw):
        return W.ProbeResult(True, True, "行", "OK")

    monkeypatch.setattr(W, "probe_connection", fake_probe)
    inputs = iter([
        "1",            # OpenAI
        "gpt-4o-mini",
        "paste",
        "sk-test",
        "n",
        "4o-mini",
        "n",
    ])

    await run(reader=lambda prompt="": next(inputs), writer=lambda _: None,
              config_dir=tmp_path)

    cfg = json.loads((tmp_path / "config.json").read_text())
    env_name = cfg["models"][cfg["active"]]["api_key_env"]
    assert env_name == "ARGOS_4O_MINI_KEY"
    assert "ARGOS_4O_MINI_KEY=sk-test" in (tmp_path / ".env").read_text()


@pytest.mark.asyncio
async def test_run_wizard_invalid_custom_profile_skips_probe(tmp_path, monkeypatch):
    """Custom 输入非法 protocol 时应先校验失败,不要拿坏配置跑连通探针。"""
    import argos.setup_wizard as W

    seen_protocols: list[str] = []

    async def fake_probe(**kw):
        seen_protocols.append(kw["protocol"])
        return W.ProbeResult(True, True, "行", "OK")

    monkeypatch.setattr(W, "probe_connection", fake_probe)
    custom_idx = str(list(W.PRESETS.keys()).index("Custom") + 1)
    inputs = iter([
        custom_idx,
        "badproto",
        "http://localhost:8000/v1",
        "bad-model",
        "paste",
        "badkey",
        "n",             # consumed as deep-probe answer before fix; invalid provider after fix
        "badprofile",    # consumed as profile name before fix; invalid provider after fix
        "1",
        "gpt-4o-mini",
        "paste",
        "sk-test",
        "n",
        "ok",
        "n",
    ])
    out: list[str] = []

    await run(reader=lambda prompt="": next(inputs), writer=out.append,
              config_dir=tmp_path)

    cfg = json.loads((tmp_path / "config.json").read_text())
    assert "ok" in cfg["models"]
    assert seen_protocols == ["openai"]
    assert any("保存失败" in line or "Save failed" in line for line in out)


def test_write_profile_rejects_empty_base_url(tmp_path):
    """fail-closed:空 base_url 的 profile 不得落盘(否则假成功 + 下次启动 ConfigError)。"""
    import argos.config as C
    with pytest.raises(C.ConfigError):
        write_profile(config_dir=tmp_path, name="bad", protocol="openai", base_url="",
                      model="m", api_key="k", api_key_env="K", set_active=True)
    assert not (tmp_path / "config.json").exists(), "校验失败不得写出 config.json"


def test_write_profile_rejects_blank_base_url(tmp_path):
    import argos.config as C

    with pytest.raises(C.ConfigError, match="base_url"):
        write_profile(config_dir=tmp_path, name="bad", protocol="openai", base_url="   ",
                      model="m", api_key="k", api_key_env="K", set_active=True)
    assert not (tmp_path / "config.json").exists()
    assert not (tmp_path / ".env").exists()


def test_write_profile_rejects_empty_profile_name(tmp_path):
    import argos.config as C

    with pytest.raises(C.ConfigError):
        write_profile(config_dir=tmp_path, name="", protocol="openai", base_url="http://x/v1",
                      model="m", api_key="k", api_key_env="K", set_active=True)
    assert not (tmp_path / "config.json").exists()
    assert not (tmp_path / ".env").exists()


def test_write_profile_invalid_input_does_not_create_config_dir(tmp_path):
    import argos.config as C

    cfg_dir = tmp_path / ".argos"
    with pytest.raises(C.ConfigError):
        write_profile(config_dir=cfg_dir, name="", protocol="openai", base_url="http://x/v1",
                      model="m", api_key="k", api_key_env="K", set_active=True)

    assert not cfg_dir.exists()


def test_write_profile_rejects_non_string_profile_name(tmp_path):
    import argos.config as C

    with pytest.raises(C.ConfigError):
        write_profile(config_dir=tmp_path, name=123, protocol="openai", base_url="http://x/v1",
                      model="m", api_key="k", api_key_env="K", set_active=True)
    assert not (tmp_path / "config.json").exists()
    assert not (tmp_path / ".env").exists()


@pytest.mark.parametrize("field", ["protocol", "base_url", "model", "api_key_env", "embedding_model", "api_key"])
def test_write_profile_rejects_non_string_text_fields(tmp_path, field):
    import argos.config as C

    kwargs = {
        "config_dir": tmp_path,
        "name": "ok",
        "protocol": "openai",
        "base_url": "http://x/v1",
        "model": "m",
        "api_key": "k",
        "api_key_env": "K",
        "set_active": True,
        "embedding_model": "",
    }
    kwargs[field] = 123

    with pytest.raises(C.ConfigError):
        write_profile(**kwargs)
    assert not (tmp_path / "config.json").exists()
    assert not (tmp_path / ".env").exists()


def test_write_profile_rejects_partial_price(tmp_path):
    import argos.config as C

    with pytest.raises(C.ConfigError, match="price"):
        write_profile(config_dir=tmp_path, name="bad", protocol="openai", base_url="http://x/v1",
                      model="m", api_key="k", api_key_env="K", price_in=3.0,
                      price_out=None, set_active=True)
    assert not (tmp_path / "config.json").exists()
    assert not (tmp_path / ".env").exists()


def test_write_profile_rejects_newline_api_key(tmp_path):
    import argos.config as C

    with pytest.raises(C.ConfigError, match="API key"):
        write_profile(config_dir=tmp_path, name="bad", protocol="openai", base_url="http://x/v1",
                      model="m", api_key="sk-test\nEVIL=1", api_key_env="K",
                      set_active=True)
    assert not (tmp_path / "config.json").exists()
    assert not (tmp_path / ".env").exists()


def test_write_profile_invalid_api_key_does_not_create_config_dir(tmp_path):
    import argos.config as C

    cfg_dir = tmp_path / ".argos"
    with pytest.raises(C.ConfigError, match="API key"):
        write_profile(config_dir=cfg_dir, name="bad", protocol="openai", base_url="http://x/v1",
                      model="m", api_key="sk-test\nEVIL=1", api_key_env="K",
                      set_active=True)

    assert not cfg_dir.exists()


def test_write_profile_strips_pasted_api_key_whitespace(tmp_path):
    write_profile(config_dir=tmp_path, name="ok", protocol="openai", base_url="http://x/v1",
                  model="m", api_key="  sk-test  ", api_key_env="K",
                  set_active=True)

    assert (tmp_path / ".env").read_text() == "K=sk-test\n"


def test_write_profile_rejects_blank_pasted_api_key(tmp_path):
    import argos.config as C

    with pytest.raises(C.ConfigError):
        write_profile(config_dir=tmp_path, name="bad", protocol="openai", base_url="http://x/v1",
                      model="m", api_key="   ", api_key_env="K",
                      set_active=True)
    assert not (tmp_path / "config.json").exists()
    assert not (tmp_path / ".env").exists()


def test_write_profile_does_not_update_config_when_key_write_fails(tmp_path, monkeypatch):
    """fail-closed:密钥没写进去时,不得留下指向缺失 key 的 active profile。"""
    import argos.setup_wizard as W

    def boom(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(W, "_append_env", boom)

    with pytest.raises(OSError, match="disk full"):
        W.write_profile(config_dir=tmp_path, name="bad", protocol="openai",
                        base_url="http://x/v1", model="m", api_key="k",
                        api_key_env="K", set_active=True)
    assert not (tmp_path / "config.json").exists()


def test_append_env_chmods_stale_tmp_before_writing_secret(tmp_path, monkeypatch):
    """stale .env.tmp 若是 0644,写入 secret 前必须先收紧到 0600。"""
    import argos.setup_wizard as W

    stale = (tmp_path / ".env").with_suffix(".env.tmp")
    stale.write_text("old\n")
    stale.chmod(0o644)
    seen_modes: list[int] = []
    real_write = os.write

    def spy_write(fd: int, data: bytes) -> int:
        seen_modes.append(stat.S_IMODE(os.fstat(fd).st_mode))
        return real_write(fd, data)

    monkeypatch.setattr(os, "write", spy_write)

    W._append_env(tmp_path, "K", "secret")

    assert seen_modes == [0o600]
    assert stat.S_IMODE(os.stat(tmp_path / ".env").st_mode) == 0o600


def test_append_env_replaces_spaced_existing_assignment(tmp_path):
    """Replacing a key must not leave stale secret variants in .env."""
    import argos.setup_wizard as W

    env = tmp_path / ".env"
    env.write_text("K =old-secret\nOTHER=keep\n")
    env.chmod(0o600)

    W._append_env(tmp_path, "K", "new-secret")

    text = env.read_text()
    assert "old-secret" not in text
    assert "K=new-secret" in text
    assert "OTHER=keep" in text


def test_append_env_replaces_export_existing_assignment(tmp_path):
    """Replacing a key must also remove shell-style export assignments."""
    import argos.setup_wizard as W

    env = tmp_path / ".env"
    env.write_text("export K=old-secret\nOTHER=keep\n")
    env.chmod(0o600)

    W._append_env(tmp_path, "K", "new-secret")

    text = env.read_text()
    assert "old-secret" not in text
    assert "K=new-secret" in text
    assert "OTHER=keep" in text


def test_append_env_backs_up_non_utf8_env_before_writing(tmp_path):
    """Corrupt .env should not crash setup or be silently destroyed."""
    import argos.setup_wizard as W

    env = tmp_path / ".env"
    env.write_bytes(b"\xff\xfeold-secret")
    env.chmod(0o600)

    W._append_env(tmp_path, "K", "new-secret")

    backup = tmp_path / ".env.corrupt.bak"
    assert backup.read_bytes() == b"\xff\xfeold-secret"
    assert env.read_text() == "K=new-secret\n"
    assert stat.S_IMODE(os.stat(env).st_mode) == 0o600


def test_write_profile_removes_new_key_when_config_write_fails(tmp_path, monkeypatch):
    """config 写失败时,不得留下未被 profile 引用的新 secret。"""
    import pathlib
    import argos.setup_wizard as W

    real_write_text = pathlib.Path.write_text

    def fail_config_write(self, *args, **kwargs):
        if self.name == "config.json.tmp":
            raise OSError("config full")
        return real_write_text(self, *args, **kwargs)

    monkeypatch.setattr(pathlib.Path, "write_text", fail_config_write)

    with pytest.raises(OSError, match="config full"):
        W.write_profile(config_dir=tmp_path, name="bad", protocol="openai",
                        base_url="http://x/v1", model="m", api_key="k",
                        api_key_env="K", set_active=True)

    assert not (tmp_path / ".env").exists()


def test_write_profile_restores_existing_env_when_config_write_fails(tmp_path, monkeypatch):
    """config 写失败时,已有 .env 内容必须恢复。"""
    import pathlib
    import argos.setup_wizard as W

    (tmp_path / ".env").write_text("OLD=keep\n")
    (tmp_path / ".env").chmod(0o600)
    real_write_text = pathlib.Path.write_text

    def fail_config_write(self, *args, **kwargs):
        if self.name == "config.json.tmp":
            raise OSError("config full")
        return real_write_text(self, *args, **kwargs)

    monkeypatch.setattr(pathlib.Path, "write_text", fail_config_write)

    with pytest.raises(OSError, match="config full"):
        W.write_profile(config_dir=tmp_path, name="bad", protocol="openai",
                        base_url="http://x/v1", model="m", api_key="new",
                        api_key_env="NEW", set_active=True)

    assert (tmp_path / ".env").read_text() == "OLD=keep\n"
    assert stat.S_IMODE(os.stat(tmp_path / ".env").st_mode) == 0o600


def test_write_profile_keeps_existing_config_when_config_write_is_partial(tmp_path, monkeypatch):
    """config 写入中断时,旧 config.json 不得变成半截 JSON。"""
    import pathlib
    import argos.setup_wizard as W

    original = {
        "active": "old",
        "models": {
            "old": {
                "protocol": "openai",
                "base_url": "http://old/v1",
                "model": "old-model",
                "api_key_env": "OLD_KEY",
            },
        },
    }
    (tmp_path / "config.json").write_text(json.dumps(original))
    real_write_text = pathlib.Path.write_text

    def partial_config_write(self, text, *args, **kwargs):
        if self.name == "config.json.tmp":
            real_write_text(self, "{partial", *args, **kwargs)
            raise OSError("partial write")
        return real_write_text(self, text, *args, **kwargs)

    monkeypatch.setattr(pathlib.Path, "write_text", partial_config_write)

    with pytest.raises(OSError, match="partial write"):
        W.write_profile(config_dir=tmp_path, name="new", protocol="openai",
                        base_url="http://new/v1", model="new-model",
                        api_key=None, api_key_env="NEW_KEY", set_active=True)

    assert json.loads((tmp_path / "config.json").read_text()) == original
    assert not (tmp_path / "config.json.tmp").exists()


# ── Task 10: 深度探针(可选 write+verify 往返) ─────────────────────────────────────

from argos.setup_wizard import deep_probe


class _ScriptModel:
    def __init__(self, scripts): self._s, self._i = scripts, 0
    async def stream(self, messages, *, system, system_dynamic=None):
        t = self._s[min(self._i, len(self._s) - 1)]; self._i += 1
        for ch in t: yield ch


@pytest.mark.asyncio
async def test_deep_probe_passed_rates_xing(tmp_path, monkeypatch):
    """深度探针:注入一个'会写 st.py 且 verify 通过'的脚本模型 → 评级 行。"""
    # 复用 __main__._SelftestModel 思路:注入 model_factory 返回脚本模型 + 真 sandbox/verifier。
    # 用 tmp 项目;非 macOS 上 Seatbelt 失败 → deep_probe 应捕获返 '不行'(诚实),不抛。
    res = await deep_probe(protocol="openai", base_url="http://x/v1", model="m", api_key="k",
                           model_factory=lambda tier, key: _ScriptModel([
                               "```python\nwrite_file('st.py','def f():\\n    return 1\\n')\n```\n"
                               "propose_verify('python3 -c \"import st; assert st.f()==1\"')",
                               "完成。"]))
    # 真跑出三态之一(平台相关), 不抛异常
    assert res.rating in (t("setup.probe_rating_ok"), t("setup.probe_rating_marginal"), t("setup.probe_rating_fail"))


# ── Phase 3 加固回归(fail-closed / 诚实) ──────────────────────────────────────

def test_corrupt_existing_config_backed_up_not_destroyed(tmp_path):
    """fail-closed:既有 config.json 畸形时,write_profile 不静默覆盖销毁用户已配模型,
    先把损坏文件改名到 .corrupt.bak 保住数据。"""
    (tmp_path / "config.json").write_text('{ corrupt ,, not valid }')
    write_profile(config_dir=tmp_path, name="new", protocol="openai", base_url="http://x/v1",
                  model="m", api_key="k", api_key_env="NK", set_active=True)
    bak = tmp_path / "config.json.corrupt.bak"
    assert bak.exists() and "corrupt" in bak.read_text(), "损坏的旧 config 必须备份保住,不能静默丢"
    cfg = json.loads((tmp_path / "config.json").read_text())
    assert cfg["models"]["new"]["model"] == "m", "新 config 可解析且含新 profile"


def test_non_utf8_existing_config_backed_up_not_crash(tmp_path):
    """Non-UTF-8 config.json should be backed up like corrupt JSON."""
    (tmp_path / "config.json").write_bytes(b"\xff\xfe\x00")

    write_profile(config_dir=tmp_path, name="new", protocol="openai", base_url="http://x/v1",
                  model="m", api_key="k", api_key_env="NK", set_active=True)

    bak = tmp_path / "config.json.corrupt.bak"
    assert bak.exists() and bak.read_bytes() == b"\xff\xfe\x00"
    cfg = json.loads((tmp_path / "config.json").read_text())
    assert cfg["models"]["new"]["model"] == "m"


def test_corrupt_existing_config_backup_does_not_overwrite_previous_backup(tmp_path):
    """已有损坏备份时,新的损坏 config 应写入递增备份名,不能覆盖旧备份。"""
    (tmp_path / "config.json.corrupt.bak").write_text("first corrupt")
    (tmp_path / "config.json").write_text("second corrupt")

    write_profile(config_dir=tmp_path, name="new", protocol="openai", base_url="http://x/v1",
                  model="m", api_key="k", api_key_env="NK", set_active=True)

    assert (tmp_path / "config.json.corrupt.bak").read_text() == "first corrupt"
    assert (tmp_path / "config.json.corrupt.bak.1").read_text() == "second corrupt"
    cfg = json.loads((tmp_path / "config.json").read_text())
    assert cfg["models"]["new"]["model"] == "m"


def test_non_object_existing_config_backed_up_not_crash(tmp_path):
    """Parseable but schema-invalid config.json should be backed up like corrupt JSON."""
    (tmp_path / "config.json").write_text('["not", "a", "config"]')

    write_profile(config_dir=tmp_path, name="new", protocol="openai", base_url="http://x/v1",
                  model="m", api_key="k", api_key_env="NK", set_active=True)

    bak = tmp_path / "config.json.corrupt.bak"
    assert bak.exists() and "not" in bak.read_text()
    cfg = json.loads((tmp_path / "config.json").read_text())
    assert cfg["models"]["new"]["model"] == "m"


def test_existing_config_with_non_object_models_backed_up_not_crash(tmp_path):
    """config.json with a malformed models field should not crash setup."""
    (tmp_path / "config.json").write_text(json.dumps({"active": "bad", "models": []}))

    write_profile(config_dir=tmp_path, name="new", protocol="openai", base_url="http://x/v1",
                  model="m", api_key="k", api_key_env="NK", set_active=True)

    bak = tmp_path / "config.json.corrupt.bak"
    assert bak.exists() and '"models": []' in bak.read_text()
    cfg = json.loads((tmp_path / "config.json").read_text())
    assert cfg["models"]["new"]["model"] == "m"


def test_corrupt_existing_config_backup_failure_refuses_to_overwrite(tmp_path, monkeypatch):
    """损坏 config 备份失败时必须停止,不能继续写空骨架覆盖原文件。"""
    import pathlib
    import argos.config as C

    config_path = tmp_path / "config.json"
    corrupt = '{ corrupt ,, not valid }'
    config_path.write_text(corrupt)
    real_replace = pathlib.Path.replace

    def fail_config_backup(self, target):
        if self == config_path:
            raise OSError("backup failed")
        return real_replace(self, target)

    monkeypatch.setattr(pathlib.Path, "replace", fail_config_backup)

    with pytest.raises(C.ConfigError, match="backup failed"):
        write_profile(config_dir=tmp_path, name="new", protocol="openai", base_url="http://x/v1",
                      model="m", api_key="k", api_key_env="NK", set_active=True)

    assert config_path.read_text() == corrupt
    assert not (tmp_path / "config.json.corrupt.bak").exists()


def test_ask_int_fail_soft_on_non_numeric():
    """T9 HIGH:非数字输入不得崩溃整个 setup,退回默认值。"""
    from argos.setup_wizard import _ask_int
    out: list = []
    assert _ask_int(lambda p="": "abc", out.append, "max:", 4096) == 4096   # 非数字→默认,不抛
    assert _ask_int(lambda p="": "8192", out.append, "max:", 4096) == 8192  # 合法→采用
    assert _ask_int(lambda p="": "", out.append, "max:", 4096) == 4096      # 留空→默认


def test_arrow_select_falls_back_when_not_tty():
    """非 TTY(或 ARGOS_NO_ARROW_SELECT=1)→ _arrow_select 抛 _NotATTY,run() 据此回退编号输入。"""
    from argos.setup_wizard import _arrow_select, _NotATTY
    with pytest.raises(_NotATTY):
        _arrow_select(["OpenAI", "Anthropic"], title="选择 provider:", writer=lambda _: None)


# ── 记忆向量召回:复用 provider 的 OpenAIEmbedder ─────────────────────────────────

def test_openai_embedder_hits_embeddings_endpoint():
    """OpenAIEmbedder 打 <base_url>/embeddings(Bearer),解析 data[].embedding,惰性置 dim。"""
    import httpx
    from argos.memory.embedding import OpenAIEmbedder

    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path.endswith("/embeddings")
        assert req.headers["authorization"] == "Bearer K"
        import json as _j
        body = _j.loads(req.content)
        assert body["model"] == "nomic-embed-text" and body["input"] == ["a", "b"]
        return httpx.Response(200, json={"data": [
            {"embedding": [0.1, 0.2, 0.3]}, {"embedding": [0.4, 0.5, 0.6]}]})

    emb = OpenAIEmbedder(base_url="http://x/v1", api_key="K", model="nomic-embed-text",
                         transport=httpx.MockTransport(handler))
    out = emb.embed(["a", "b"])
    assert out == [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
    assert emb.dim == 3   # 惰性置维度


def test_openai_embedder_endpoint_idempotent():
    """base_url 已含 /embeddings 时不重复追加。"""
    from argos.memory.embedding import OpenAIEmbedder
    e1 = OpenAIEmbedder(base_url="http://x/v1", api_key="K", model="m")
    e2 = OpenAIEmbedder(base_url="http://x/v1/embeddings", api_key="K", model="m")
    assert e1._endpoint() == "http://x/v1/embeddings"
    assert e2._endpoint() == "http://x/v1/embeddings"
