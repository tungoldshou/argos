"""argos setup 向导(spec §6)。I/O 解耦:纯逻辑(预设/写配置/探针)可单测,
CLI 交互(run)注入 reader/writer/client 工厂。密钥进 .env(0600),设置进 config.json。"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from argos.i18n import t


class _NotATTY(Exception):
    """stdin/stdout 不是真终端(测试/管道)→ 方向键选择不可用,调用方回退编号输入。"""


def _arrow_select(options: list[str], *, title: str, writer) -> int:
    """真终端下用 ↑↓ 选、回车确认,返回选中下标。
    非 TTY(测试/管道/headless)抛 _NotATTY,让调用方回退编号输入(保持可测、不阻塞自动化)。
    全程 raw 模式直接读 sys.stdin 转义序列;finally 必复原终端设置(异常/Ctrl-C 也不留坏状态)。"""
    # 测试/自动化可设 ARGOS_NO_ARROW_SELECT=1 强制回退编号,杜绝 pytest -s(stdin 是真 tty)下卡住等键。
    if os.environ.get("ARGOS_NO_ARROW_SELECT") == "1":
        raise _NotATTY
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        raise _NotATTY
    import termios
    import tty
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    out = sys.stdout
    n = len(options)
    idx = 0
    out.write(title + "\r\n" + t("setup.arrow_hint"))

    def draw() -> None:
        for i, opt in enumerate(options):
            mark = "❯" if i == idx else " "
            body = f" {mark} {opt}"
            if i == idx:
                body = f"\x1b[7m{body}\x1b[0m"   # 反显高亮当前项
            out.write(f"\r\x1b[K{body}\r\n")
        out.flush()

    draw()
    try:
        tty.setraw(fd)
        while True:
            ch = sys.stdin.read(1)
            if ch == "\x1b":                       # 转义序列(方向键)
                seq = sys.stdin.read(2)
                if seq == "[A":
                    idx = (idx - 1) % n
                elif seq == "[B":
                    idx = (idx + 1) % n
                else:
                    continue
            elif ch in ("\r", "\n"):               # 回车确认
                break
            elif ch == "\x03":                     # Ctrl-C
                raise KeyboardInterrupt
            else:
                continue
            out.write(f"\x1b[{n}A")                 # 光标上移 N 行重绘
            draw()
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
    out.write("\r\n")
    out.flush()
    return idx

# provider 预设:预填 protocol + base_url + 常见默认 model(spec §6.1)。
PRESETS: dict[str, dict] = {
    "OpenAI": {"protocol": "openai", "base_url": "https://api.openai.com/v1", "model": "gpt-4o"},
    "Anthropic (Claude)": {"protocol": "anthropic", "base_url": "https://api.anthropic.com",
                           "model": "claude-sonnet-4-6"},
    "MiniMax": {"protocol": "anthropic", "base_url": "https://api.minimaxi.com/anthropic",
                "model": "MiniMax-M3"},
    "DeepSeek": {"protocol": "openai", "base_url": "https://api.deepseek.com/v1",
                 "model": "deepseek-chat"},
    "Ollama (local)": {"protocol": "openai", "base_url": "http://localhost:11434/v1",
                      "model": "qwen2.5-coder"},
    "OpenRouter": {"protocol": "openai", "base_url": "https://openrouter.ai/api/v1",
                   "model": "anthropic/claude-sonnet-4-6"},
    "Custom": {"protocol": "", "base_url": "", "model": ""},
}


def _read_config(config_dir: Path) -> dict:
    """读现有 config.json。畸形(JSON 损坏)时绝不静默当作'空配置'返回——否则随后的
    write_profile 会用仅含新 profile 的内容覆盖写回,静默销毁用户已配的全部模型(违 fail-closed)。
    改为先把损坏文件改名到 .corrupt.bak 保住数据,再以空骨架继续(数据没丢,在 .bak,可恢复)。"""
    f = config_dir / "config.json"
    if not f.exists():
        return {"models": {}}
    try:
        return json.loads(f.read_text())
    except json.JSONDecodeError:
        try:
            f.replace(config_dir / "config.json.corrupt.bak")
        except OSError:
            pass
        return {"models": {}}


def _ask_int(reader, writer, prompt: str, default: int) -> int:
    """读整数输入。非数字时不崩溃(此前 int() 抛 ValueError 会击穿整个 setup、丢光本轮已填输入)
    —— fail-soft:告知并退回默认值。"""
    raw = (reader(prompt) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        writer(t("setup.not_integer", val=raw, default=default))
        return default


def _append_env(config_dir: Path, name: str, value: str) -> None:
    """把 NAME=value 写进 ~/.argos/.env(已存在同名则替换),权限 0600。
    以 0600 创建临时文件再原子替换 → 明文密钥从落盘第一刻就 0600,无 0644 暴露窗口(TOCTOU)。"""
    f = config_dir / ".env"
    lines = f.read_text().splitlines() if f.exists() else []
    lines = [ln for ln in lines if not ln.strip().startswith(f"{name}=")]
    lines.append(f"{name}={value}")
    content = "\n".join(lines) + "\n"
    tmp = f.with_suffix(".env.tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, content.encode())
    finally:
        os.close(fd)
    os.replace(tmp, f)   # 原子替换:目标继承 tmp 的 0600,密钥从不以 0644 存在过
    os.chmod(f, 0o600)   # 替换后再确保一次(防原已存在文件残留宽权限)


def write_profile(*, config_dir: Path, name: str, protocol: str, base_url: str, model: str,
                  api_key: str | None, api_key_env: str, set_active: bool,
                  max_tokens: int = 4096, context_window: int = 200_000,
                  price_in: float | None = None, price_out: float | None = None,
                  embedding_model: str = "") -> None:
    """写一个 profile:设置进 config.json,密钥(若给)进 .env(0600);密钥绝不进 config.json。
    embedding_model 非空 → 记忆向量召回复用本 provider 的 /embeddings;空 → 记忆走 FTS5。"""
    config_dir.mkdir(parents=True, exist_ok=True)
    prof = {"protocol": protocol, "base_url": base_url, "model": model,
            "api_key_env": api_key_env, "max_tokens": max_tokens,
            "context_window": context_window}
    if price_in is not None and price_out is not None:
        prof["price_in"] = price_in
        prof["price_out"] = price_out
    if embedding_model:
        prof["embedding_model"] = embedding_model
    # fail-closed:落盘前校验本 profile 合法(空 base_url/model、非法 protocol、非正整数都拒)——
    # 否则会写出"假成功"的坏 config 并顶掉原可用 active(下次启动才 ConfigError 落 demo 态)。
    from argos import config as _config
    _config._validate_profile(name, prof)
    cfg = _read_config(config_dir)
    cfg.setdefault("models", {})
    cfg["models"][name] = prof
    if set_active or "active" not in cfg:
        cfg["active"] = name
    (config_dir / "config.json").write_text(json.dumps(cfg, indent=2, ensure_ascii=False))
    if api_key:   # 仅"粘贴 key"路径写 .env;"用已有环境变量"路径 api_key=None 不写
        _append_env(config_dir, api_key_env, api_key)


# ── 连通 + 格式探针(spec §6.2) ────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class ProbeResult:
    connected: bool
    codeact_ok: bool
    rating: str       # "行" | "勉强" | "不行"
    message: str      # 给用户的诚实一句话


def _probe_prompt() -> str:
    return t("setup.probe_prompt")
# 连通测试硬超时:ModelClient 自身 timeout=300s 且 stream() 还重试 3 次 → 填错 base_url
# (端口开着但不回流:misrouted proxy / Ollama 模型没加载)会让向导卡"正在连通测试…"近 900s。
# 20s 够冷启动首 token,又把 typo/卡死端点的等待收敛到可接受范围(2026-06-18 排查 #7)。
_PROBE_TIMEOUT_S = 20.0


async def probe_connection(*, protocol: str, base_url: str, model: str, api_key: str | None,
                           client_factory=None) -> ProbeResult:
    """真发一次流式小调用(spec §6.2):连通?吐 ```python 围栏?诚实评级,绝不假定。
    client_factory(tier, key)->ModelClient(可注入 MockTransport);默认走真网络。"""
    from argos.core.models import ModelClient, CredentialPool, ModelTier
    tier = ModelTier(name="probe", model=model, base_url=base_url, max_tokens=256,
                     context_window=8192, protocol=protocol)
    if client_factory is None:
        def client_factory(t, k):
            return ModelClient(tier=t, pool=CredentialPool([k or "x"]))
    client = client_factory(tier, api_key)
    # 口径对齐真实 loop:用同一套 HONESTY_SYSTEM 契约提示 + 同一个 extract_code_block 抽取,
    # 让"行/勉强"判定 == loop 真实行为(否则极简提示 + 朴素 '```python' in out 会产生假阴/假阳)。
    from argos.core.honesty import HONESTY_SYSTEM, compose_system, format_untrusted
    from argos.core.loop import extract_code_block
    system = compose_system(HONESTY_SYSTEM, untrusted=format_untrusted(skill_bodies=[], memory_lines=[]))
    async def _collect() -> str:
        return "".join([c async for c in client.stream(
            [{"role": "user", "content": _probe_prompt()}], system=system)])
    try:
        out = await asyncio.wait_for(_collect(), timeout=_PROBE_TIMEOUT_S)
    except asyncio.TimeoutError:
        return ProbeResult(False, False, t("setup.probe_rating_fail"),
                           t("setup.probe_timeout", timeout=int(_PROBE_TIMEOUT_S)))
    except Exception as e:  # noqa: BLE001 — 连通失败如实报(含状态码/真因)
        detail = str(e)
        return ProbeResult(False, False, t("setup.probe_rating_fail"),
                           t("setup.probe_connect_error", detail=detail[:200]))
    if extract_code_block(out) is not None:
        return ProbeResult(True, True, t("setup.probe_rating_ok"),
                           t("setup.probe_ok_message"))
    return ProbeResult(True, False, t("setup.probe_rating_marginal"),
                       t("setup.probe_marginal_message"))


# ── 交互向导编排(spec §6.1) ────────────────────────────────────────────────────

def _rule(console, key: str) -> None:
    """章节分隔线(仅真 CLI 传了 console 时画);测试 / 非 TTY 静默。"""
    if console is not None:
        console.rule(f"[dim]{t(key)}[/dim]")


def _banner(console) -> None:
    """向导开场标题(仅真 CLI)。"""
    if console is not None:
        console.print(t("setup.banner"), style="bold cyan")


def _emit_probe(console, writer, res: "ProbeResult") -> None:
    """探针评级:有 console 按连通态上色(绿/黄/红);否则纯文本一行。"""
    line = t("setup.probe_rating", rating=res.rating, message=res.message)
    if console is not None:
        console.print(line, style="green" if res.codeact_ok else ("yellow" if res.connected else "red"))
    else:
        writer(line)


def _select_key_method(reader, writer, console) -> str:
    """选 key 方式:真终端 ↑↓ 选,非 TTY 回退文字输入。返回 'paste' 或 'env'。"""
    try:
        idx = _arrow_select([t("setup.key_method_paste"), t("setup.key_method_env")],
                            title=t("setup.section_apikey"), writer=writer)
        return "paste" if idx == 0 else "env"
    except _NotATTY:
        return (reader(t("setup.prompt_key_method")) or "paste").strip()


async def _probe_with_status(console, writer, *, protocol, base_url, model, api_key) -> "ProbeResult":
    """连通探针:有 console 用 spinner(干掉 20 秒静默卡屏);否则打一行静态'正在连通…'。"""
    if console is not None:
        with console.status(t("setup.probing")):
            return await probe_connection(protocol=protocol, base_url=base_url, model=model, api_key=api_key)
    writer(t("setup.probing"))
    return await probe_connection(protocol=protocol, base_url=base_url, model=model, api_key=api_key)


async def run(*, reader, writer, config_dir: Path | None = None,
              console=None, advanced: bool = False) -> None:
    """CLI 向导编排(spec §6.1)。reader/writer 注入 I/O(可脚本化、可测);console 可选——真 CLI
    传 rich Console → 上色 / 章节标题 / 连通探针 spinner;测试不传 → 纯文本。advanced=True 才问
    max_tokens / context_window / embedding(默认走合理缺省,少打扰首次用户;价格已不再询问)。

    reader 调用顺序(每轮一个模型,默认非 advanced):
      provider 选 → [Custom: protocol, base_url] → model id → key 方式 → key 值 / env 名
      → [advanced: max_tokens, context_window, (openai)embedding] → [连不通: 重试?]
      → 深探?(y/N) → profile 名 → [已有模型: 设为默认?] → 再配?(y/N)
    """
    from argos import config as C
    cdir = config_dir or Path(C.get("ARGOS_CONFIG_DIR") or (Path.home() / ".argos"))
    names = list(PRESETS)
    _banner(console)
    # 非 TTY 友好兜底(2026-06-09):管道/CI 跑 setup 时 input() 抛 EOFError,以前裸 traceback
    # 退出,用户完全不知道"setup 需要真终端"或"可以手工写 config"。接住 → 打友好提示 → return。
    try:
        while True:
            _rule(console, "setup.section_provider")
            # provider 选择:真终端用 ↑↓ 方向键,非 TTY(测试/管道)回退编号输入(保持可测)。
            try:
                pidx = _arrow_select(names, title=t("setup.choose_provider_title"), writer=writer)
            except _NotATTY:
                writer(t("setup.available_presets"))
                for i, n in enumerate(names, 1):
                    writer(t("setup.preset_item", i=i, name=n))
                choice = (reader(t("setup.choose_provider_title")) or "").strip()
                try:
                    pidx = int(choice) - 1
                    if not (0 <= pidx < len(names)):
                        raise ValueError
                except ValueError:
                    writer(t("setup.invalid_choice"))
                    continue
            preset = PRESETS[names[pidx]]
            # 「Custom」预设 protocol/base_url 为空 → 向用户询问(spec §6.1 表格「(问)」)
            protocol = preset["protocol"] or (reader(t("setup.prompt_protocol")) or "openai").strip()
            base_url = preset["base_url"] or (reader(t("setup.prompt_base_url")) or "").strip()
            default_model = preset["model"]
            model = (reader(t("setup.prompt_model", default=default_model)) or default_model).strip()
            # API key
            _rule(console, "setup.section_apikey")
            way = _select_key_method(reader, writer, console)
            if way == "env":
                api_key = None
                api_key_env = (reader(t("setup.prompt_env_var_name")) or "").strip()
                derive_env = False
            else:
                api_key = (reader(t("setup.prompt_paste_key")) or "").strip()
                if not api_key:
                    # 空 key:别静默拿占位 "x" 去探针换一个迷惑的 401,当场说清并重配本模型。
                    writer(t("setup.key_empty"))
                    continue
                api_key_env = ""        # paste 路径:env 名延后由【唯一 profile 名】派生
                derive_env = True       # (避免同 model 不同 key 的两 profile 撞同名 env 互相覆盖)
            # 高级项(可选):默认走合理缺省,--advanced 才问。价格不再询问(费用显示已移除)。
            max_tokens, ctx, embedding_model = 4096, 200_000, ""
            if advanced:
                _rule(console, "setup.section_advanced")
                max_tokens = _ask_int(reader, writer, t("setup.prompt_max_tokens"), 4096)
                ctx = _ask_int(reader, writer, t("setup.prompt_context_window"), 200000)
                # 记忆向量语义召回:复用 provider 的 /embeddings(仅 OpenAI 协议有;Anthropic 端没有)。
                if protocol == "openai":
                    embedding_model = (reader(t("setup.prompt_embedding_model")) or "").strip()
                else:
                    writer(t("setup.no_embeddings_note"))
            # 连通+格式探针(必做)
            _rule(console, "setup.section_connect")
            res = await _probe_with_status(console, writer, protocol=protocol,
                                           base_url=base_url, model=model, api_key=api_key)
            _emit_probe(console, writer, res)
            if not res.connected:
                again = (reader(t("setup.reconnect_prompt")) or "y").strip().lower()
                if again != "n":
                    continue
            # 可选深度探针(默认跳过)
            if (reader(t("setup.deep_probe_prompt")) or "n").strip().lower() == "y":
                writer(t("setup.deep_probing"))
                dres = await deep_probe(protocol=protocol, base_url=base_url, model=model, api_key=api_key)
                writer(t("setup.deep_probe_result", rating=dres.rating, message=dres.message))
            # profile 命名:向用户提问,默认用 model id;重名追加序号(spec §6.1 step 5)
            cfg_existing = _read_config(cdir)
            existing_models = cfg_existing.get("models", {})
            default_name = model.lower().replace(" ", "-") if model else "custom"
            raw_name = (reader(t("setup.prompt_profile_name", default=default_name)) or default_name).strip() or default_name
            name = raw_name
            idx = 2
            while name in existing_models:
                name = f"{raw_name}-{idx}"
                idx += 1
            # paste 路径:env 名由唯一 profile 名派生(此时 name 已去重),杜绝同 model 撞名覆盖。
            if derive_env:
                api_key_env = f"{name.upper().replace('-', '_').replace('/', '_')}_KEY"
            # 是否设为当前默认:首个模型自动设;已有模型时默认【不】改 active(重跑 setup 加模型不静默劫持)。
            if existing_models:
                make_active = (reader(t("setup.set_active_prompt")) or "n").strip().lower() == "y"
            else:
                make_active = True
            if not res.connected and make_active:
                # 诚实:把明知连不通的模型设为当前 active 时不静默(spec §10 验收②的诚实兜底)。
                writer(t("setup.warn_set_active_disconnected"))
            try:
                write_profile(config_dir=cdir, name=name, protocol=protocol, base_url=base_url,
                              model=model, api_key=api_key, api_key_env=api_key_env,
                              max_tokens=max_tokens, context_window=ctx,
                              embedding_model=embedding_model, set_active=make_active)
            except C.ConfigError as e:
                # fail-closed:配置不合法绝不假成功,也不顶掉原 active;让用户重配这个模型。
                writer(t("setup.save_failed", err=e))
                continue
            if make_active:
                writer(t("setup.saved_active", name=name))
            else:
                writer(t("setup.saved_inactive", name=name))
            if api_key:
                writer(t("setup.key_stored_warning"))
            if (reader(t("setup.add_another_prompt")) or "n").strip().lower() != "y":
                writer(t("setup.done"))
                break
    except EOFError:
        # 非 TTY(管道 / CI)兜底:input() 抛 EOFError 时给一条清楚出路(不裸 traceback)。
        # 关键:真用户来用会卡在这,必须显式告诉他"setup 需真终端"+"可以手工写 config"。
        writer(t("setup.no_tty"))


# ── 深度探针(spec §6.3) ──────────────────────────────────────────────────────────

async def deep_probe(*, protocol: str, base_url: str, model: str, api_key: str | None,
                     model_factory=None) -> ProbeResult:
    """可选深度探针(spec §6.3):真 sandbox+loop 跑一个极小 write+verify 往返,出 行/勉强/不行。
    复用 __main__._run_selftest 的装配。非 macOS(无 Seatbelt)或异常 → 诚实返 '不行' 不抛。
    model_factory(tier,key)->model 注入(测试用脚本模型,默认走真 ModelClient)。"""
    import tempfile
    from pathlib import Path as _P
    from argos import runtime
    from argos.approval import ApprovalGate, ApprovalLevel
    from argos.core.loop import AgentLoop, LoopConfig
    from argos.core.models import ModelClient, CredentialPool, ModelTier
    from argos.core.verify_gate import Verifier
    from argos.memory.store import ArgosStore
    from argos.sandbox.broker import CapabilityBroker
    from argos.sandbox.egress import EgressPolicy
    from argos.sandbox.executor import SeatbeltExecutor
    from argos.tools.receipts import ReceiptSigner
    from argos.protocol.events import VerifyVerdict
    from argos.protocol.events import EventBus

    tier = ModelTier(name="probe", model=model, base_url=base_url, max_tokens=1024,
                     context_window=8192, protocol=protocol)
    if model_factory is None:
        def model_factory(t, k):
            return ModelClient(tier=t, pool=CredentialPool([k or "x"]))
    with tempfile.TemporaryDirectory() as td:
        proj = _P(td) / "proj"; proj.mkdir()
        _prev_ws = os.environ.get("ARGOS_WORKSPACE")   # 存旧值,finally 还原(防同进程复用时污染后续真 run)
        os.environ["ARGOS_WORKSPACE"] = str(proj)
        tok = runtime.use_project(str(proj))
        store = None
        try:
            gate = ApprovalGate(level=ApprovalLevel.AUTO)
            broker = CapabilityBroker(gate=gate, egress=EgressPolicy(
                llm_hosts=set(), search_hosts=set(), mcp_hosts=set()),
                signer=ReceiptSigner(key=b"probe"))
            sandbox = SeatbeltExecutor(broker_handler=lambda a, ar: broker.execute_sync(a, ar)[0])
            store = ArgosStore(db_path=str(_P(td) / "p.db"))
            loop = AgentLoop(store=store, bus=EventBus(), sandbox=sandbox, broker=broker,
                             model=model_factory(tier, api_key), verifier=Verifier(max_rounds=3),
                             config=LoopConfig(approval_level=ApprovalLevel.AUTO, compaction=False),
                             workspace=proj, verify_dir=proj)
            vs = []
            async for ev in loop.run(t("setup.deep_probe_task"), "probe"):
                if isinstance(ev, VerifyVerdict):
                    vs.append(ev.verdict.status)
            if vs and vs[-1] == "passed":
                if len(vs) == 1:
                    rating = t("setup.probe_rating_ok")
                    msg = t("setup.deep_probe_pass_one", vs=vs)
                else:
                    rating = t("setup.probe_rating_marginal")
                    msg = t("setup.deep_probe_pass_marginal", vs=vs)
                return ProbeResult(True, True, rating, msg)
            return ProbeResult(True, False, t("setup.probe_rating_fail"),
                               t("setup.deep_probe_fail", vs=vs))
        except Exception as e:  # noqa: BLE001 — 平台/装配失败诚实返不行,不抛
            return ProbeResult(False, False, t("setup.probe_rating_fail"),
                               t("setup.deep_probe_error", err=f"{type(e).__name__}: {e}"))
        finally:
            if store is not None:
                store.close()
            runtime.reset(tok)
            if _prev_ws is None:
                os.environ.pop("ARGOS_WORKSPACE", None)
            else:
                os.environ["ARGOS_WORKSPACE"] = _prev_ws
