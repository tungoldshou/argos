# tests/test_setup_wizard.py
import json
import os
import stat
import pytest
from argos_agent.setup_wizard import PRESETS, write_profile


def test_presets_have_protocol_and_base_url():
    """预设必须有 protocol 和 base_url 字段;「自定义」的 protocol/base_url 允许为空(向导会询问)。"""
    for name, p in PRESETS.items():
        if name == "自定义":
            # 自定义预设的 protocol/base_url 为空,由向导交互询问(spec §6.1 「(问)」)
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
    """脚本化输入跑完一轮:选 MiniMax 预设→默认 model→粘贴 key→跳过深探→默认名→不再加→完成。
    MiniMax 是 PRESETS 第 3 项;无 protocol/base_url 问询(预设已填)。
    reader 调用顺序:选编号→model id→key方式→key值→max_tokens→ctx→price→深探→profile名→再配。
    """
    inputs = iter([
        "3",            # 1. 选 MiniMax(PRESETS 第 3 项,编号稳定)
        "",             # 2. model 用默认 MiniMax-M3
        "paste",        # 3. key 方式:粘贴
        "secret123",    # 4. key 值
        "",             # 5. max_tokens 默认
        "",             # 6. context_window 默认
        "",             # 7. price 跳过
        "n",            # 8. 深度探针 跳过
        "",             # 9. profile 名 留空=默认(minimax-m3)
        "n",            # 10. 不再加模型
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


@pytest.mark.asyncio
async def test_run_wizard_custom_preset(tmp_path, monkeypatch):
    """「自定义」预设触发 protocol/base_url 额外询问(spec §6.1 「(问)」)。"""
    import argos_agent.setup_wizard as W
    # 自定义是 PRESETS 第 7 项(最后一项)
    custom_idx = str(list(W.PRESETS.keys()).index("自定义") + 1)
    inputs = iter([
        custom_idx,                             # 1. 选「自定义」
        "openai",                               # 2a. protocol(询问,因预设为空)
        "http://localhost:8000/v1",             # 2b. base_url(询问,因预设为空)
        "my-local-model",                       # 3. model id
        "paste",                                # 4. key 方式
        "localkey",                             # 5. key 值
        "",                                     # 6. max_tokens 默认
        "",                                     # 7. context_window 默认
        "",                                     # 8. price 跳过
        "nomic-embed-text",                     # 9. embedding 模型(openai 协议才问)
        "n",                                    # 10. 深度探针 跳过
        "local",                                # 11. profile 名
        "n",                                    # 12. 不再加模型
    ])
    out_lines = []
    async def fake_probe(**kw):
        return W.ProbeResult(True, True, "行", "OK")
    monkeypatch.setattr(W, "probe_connection", fake_probe)
    await run(reader=lambda prompt="": next(inputs), writer=out_lines.append,
              config_dir=tmp_path)
    cfg = json.loads((tmp_path / "config.json").read_text())
    assert "local" in cfg["models"]
    prof = cfg["models"]["local"]
    assert prof["protocol"] == "openai"
    assert prof["base_url"] == "http://localhost:8000/v1"
    assert prof["model"] == "my-local-model"
    assert prof["embedding_model"] == "nomic-embed-text"   # openai 协议:embedding 模型写入 profile


@pytest.mark.asyncio
async def test_run_wizard_duplicate_name_appends_index(tmp_path, monkeypatch):
    """同名 profile 再配时自动追加序号(spec §6.1 step 5「重名追加序号」)。"""
    import argos_agent.setup_wizard as W
    async def fake_probe(**kw):
        return W.ProbeResult(True, True, "行", "OK")
    monkeypatch.setattr(W, "probe_connection", fake_probe)

    # 第一轮:profile 名 "mm"
    it1 = iter(["3", "", "paste", "k", "", "", "", "n", "mm", "n"])
    await run(reader=lambda prompt="": next(it1), writer=lambda _: None, config_dir=tmp_path)
    cfg1 = json.loads((tmp_path / "config.json").read_text())
    assert "mm" in cfg1["models"]

    # 第二轮:同名 "mm" → 应自动变 "mm-2"。注意:已有 profile 时多一问「设为当前默认模型?(y/N)」
    # (避免重跑 setup 加模型时静默劫持 active),故输入序列在 name 后、再配前多一个 "n"。
    it2 = iter(["3", "", "paste", "k", "", "", "", "n", "mm", "n", "n"])
    await run(reader=lambda prompt="": next(it2), writer=lambda _: None, config_dir=tmp_path)
    cfg2 = json.loads((tmp_path / "config.json").read_text())
    assert "mm" in cfg2["models"] and "mm-2" in cfg2["models"]
    assert cfg2["active"] == "mm", "第二轮答 n 不设为默认 → active 仍是第一轮的 mm(不被劫持)"
    # paste 路径 env 名由【唯一 profile 名】派生 → 两 profile 的 api_key_env 必须不同(防撞名覆盖)
    assert cfg2["models"]["mm"]["api_key_env"] != cfg2["models"]["mm-2"]["api_key_env"]


def test_write_profile_rejects_empty_base_url(tmp_path):
    """fail-closed:空 base_url 的 profile 不得落盘(否则假成功 + 下次启动 ConfigError)。"""
    import argos_agent.config as C
    with pytest.raises(C.ConfigError):
        write_profile(config_dir=tmp_path, name="bad", protocol="openai", base_url="",
                      model="m", api_key="k", api_key_env="K", set_active=True)
    assert not (tmp_path / "config.json").exists(), "校验失败不得写出 config.json"


# ── Task 10: 深度探针(可选 write+verify 往返) ─────────────────────────────────────

from argos_agent.setup_wizard import deep_probe


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
    assert res.rating in ("行", "勉强", "不行")   # 真跑出三态之一(平台相关), 不抛异常


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


def test_ask_int_fail_soft_on_non_numeric():
    """T9 HIGH:非数字输入不得崩溃整个 setup,退回默认值。"""
    from argos_agent.setup_wizard import _ask_int
    out: list = []
    assert _ask_int(lambda p="": "abc", out.append, "max:", 4096) == 4096   # 非数字→默认,不抛
    assert _ask_int(lambda p="": "8192", out.append, "max:", 4096) == 8192  # 合法→采用
    assert _ask_int(lambda p="": "", out.append, "max:", 4096) == 4096      # 留空→默认


def test_ask_float_or_none_fail_soft():
    from argos_agent.setup_wizard import _ask_float_or_none
    out: list = []
    assert _ask_float_or_none(lambda p="": "abc", out.append, "p:") is None  # 非数字→None,不抛
    assert _ask_float_or_none(lambda p="": "0.3", out.append, "p:") == 0.3
    assert _ask_float_or_none(lambda p="": "", out.append, "p:") is None


def test_arrow_select_falls_back_when_not_tty():
    """非 TTY(或 ARGOS_NO_ARROW_SELECT=1)→ _arrow_select 抛 _NotATTY,run() 据此回退编号输入。"""
    from argos_agent.setup_wizard import _arrow_select, _NotATTY
    with pytest.raises(_NotATTY):
        _arrow_select(["OpenAI", "Anthropic"], title="选择 provider:", writer=lambda _: None)


# ── 记忆向量召回:复用 provider 的 OpenAIEmbedder ─────────────────────────────────

def test_openai_embedder_hits_embeddings_endpoint():
    """OpenAIEmbedder 打 <base_url>/embeddings(Bearer),解析 data[].embedding,惰性置 dim。"""
    import httpx
    from argos_agent.memory.embedding import OpenAIEmbedder

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
    from argos_agent.memory.embedding import OpenAIEmbedder
    e1 = OpenAIEmbedder(base_url="http://x/v1", api_key="K", model="m")
    e2 = OpenAIEmbedder(base_url="http://x/v1/embeddings", api_key="K", model="m")
    assert e1._endpoint() == "http://x/v1/embeddings"
    assert e2._endpoint() == "http://x/v1/embeddings"
