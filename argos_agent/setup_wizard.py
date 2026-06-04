"""argos setup 向导(spec §6)。I/O 解耦:纯逻辑(预设/写配置/探针)可单测,
CLI 交互(run)注入 reader/writer/client 工厂。密钥进 .env(0600),设置进 config.json。"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

# provider 预设:预填 protocol + base_url + 常见默认 model(spec §6.1)。
PRESETS: dict[str, dict] = {
    "OpenAI": {"protocol": "openai", "base_url": "https://api.openai.com/v1", "model": "gpt-4o"},
    "Anthropic (Claude)": {"protocol": "anthropic", "base_url": "https://api.anthropic.com",
                           "model": "claude-sonnet-4-6"},
    "MiniMax": {"protocol": "anthropic", "base_url": "https://api.minimaxi.com/anthropic",
                "model": "MiniMax-M3"},
    "DeepSeek": {"protocol": "openai", "base_url": "https://api.deepseek.com/v1",
                 "model": "deepseek-chat"},
    "Ollama (本地)": {"protocol": "openai", "base_url": "http://localhost:11434/v1",
                     "model": "qwen2.5-coder"},
    "OpenRouter": {"protocol": "openai", "base_url": "https://openrouter.ai/api/v1",
                   "model": "anthropic/claude-sonnet-4-6"},
    "自定义": {"protocol": "openai", "base_url": "", "model": ""},
}


def _read_config(config_dir: Path) -> dict:
    f = config_dir / "config.json"
    if f.exists():
        try:
            return json.loads(f.read_text())
        except json.JSONDecodeError:
            return {"models": {}}
    return {"models": {}}


def _append_env(config_dir: Path, name: str, value: str) -> None:
    """把 NAME=value 写进 ~/.argos/.env(已存在同名则替换),权限 0600。"""
    f = config_dir / ".env"
    lines = f.read_text().splitlines() if f.exists() else []
    lines = [ln for ln in lines if not ln.strip().startswith(f"{name}=")]
    lines.append(f"{name}={value}")
    f.write_text("\n".join(lines) + "\n")
    os.chmod(f, 0o600)


def write_profile(*, config_dir: Path, name: str, protocol: str, base_url: str, model: str,
                  api_key: str | None, api_key_env: str, set_active: bool,
                  max_tokens: int = 4096, context_window: int = 200_000,
                  price_in: float | None = None, price_out: float | None = None) -> None:
    """写一个 profile:设置进 config.json,密钥(若给)进 .env(0600);密钥绝不进 config.json。"""
    config_dir.mkdir(parents=True, exist_ok=True)
    cfg = _read_config(config_dir)
    cfg.setdefault("models", {})
    prof = {"protocol": protocol, "base_url": base_url, "model": model,
            "api_key_env": api_key_env, "max_tokens": max_tokens,
            "context_window": context_window}
    if price_in is not None and price_out is not None:
        prof["price_in"] = price_in
        prof["price_out"] = price_out
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


_PROBE_PROMPT = "请只用一个 ```python 代码块输出:print('ok')。不要任何其它文字。"


async def probe_connection(*, protocol: str, base_url: str, model: str, api_key: str | None,
                           client_factory=None) -> ProbeResult:
    """真发一次流式小调用(spec §6.2):连通?吐 ```python 围栏?诚实评级,绝不假定。
    client_factory(tier, key)->ModelClient(可注入 MockTransport);默认走真网络。"""
    from argos_agent.core.models import ModelClient, CredentialPool, ModelTier
    tier = ModelTier(name="probe", model=model, base_url=base_url, max_tokens=256,
                     context_window=8192, protocol=protocol)
    if client_factory is None:
        def client_factory(t, k):
            return ModelClient(tier=t, pool=CredentialPool([k or "x"]))
    client = client_factory(tier, api_key)
    try:
        out = "".join([c async for c in client.stream(
            [{"role": "user", "content": _PROBE_PROMPT}], system="You are a coding agent.")])
    except Exception as e:  # noqa: BLE001 — 连通失败如实报(含状态码/真因)
        detail = str(e)
        return ProbeResult(False, False, "不行", f"连不上 / 端点报错:{detail[:200]}")
    fenced = "```python" in out
    if fenced:
        return ProbeResult(True, True, "行", "连通正常,CodeAct 格式合规。")
    return ProbeResult(True, False, "勉强",
                       "连通正常,但此模型默认不吐 ```python 围栏(Argos 实测 MiniMax-M3 也曾如此,"
                       "靠系统提示契约掰正)——能用但可能需要更强提示;仍可保存。")


# ── 交互向导编排(spec §6.1) ────────────────────────────────────────────────────

async def run(*, reader, writer, config_dir: Path | None = None) -> None:
    """CLI 向导编排(spec §6.1)。reader(prompt)->str 注入输入;writer(line) 注入输出;
    config_dir 注入(测试/打包);默认 ~/.argos。

    reader 调用顺序(每轮一个模型,9 步):
      1. 选编号
      2. 模型 id(留空=默认)
      3. API key 方式(paste/env)
      4. 若 paste:粘贴 key;若 env:环境变量名
      5. max_tokens(留空=4096)
      6. context_window(留空=200000)
      7. 价格 in(留空=跳过,则跳过 price_out)
      8. 深度探针?(y/N)
      9. 再配一个模型?(y/N)
    profile name 从 model id 自动推导(不单独提问),保持 reader 调用数可预测。
    """
    from argos_agent import config as C
    cdir = config_dir or Path(C.get("ARGOS_CONFIG_DIR") or (Path.home() / ".argos"))
    names = list(PRESETS)
    while True:
        writer("可选 provider 预设:")
        for i, n in enumerate(names, 1):
            writer(f"  {i}. {n}")
        choice = (reader("选编号:") or "").strip()   # reader 调用 1
        try:
            preset = PRESETS[names[int(choice) - 1]]
        except (ValueError, IndexError):
            writer("无效编号,重来。")
            continue
        protocol = preset["protocol"] or "openai"
        base_url = preset["base_url"] or ""
        default_model = preset["model"]
        model = (reader(f"模型 id [{default_model}]:") or default_model).strip()   # reader 调用 2
        # key 方式:paste 或 env
        way = (reader("API key 方式:粘贴(paste) / 用已有环境变量(env):") or "paste").strip()   # reader 调用 3
        if way == "env":
            api_key = None
            api_key_env = (reader("环境变量名:") or "").strip()   # reader 调用 4(env 分支)
        else:
            api_key = (reader("粘贴 API key:") or "").strip()   # reader 调用 4(paste 分支)
            api_key_env = f"{model.upper().replace('-', '_').replace('/', '_')}_KEY"
        max_tokens = int((reader("max_tokens [4096]:") or "4096").strip() or 4096)   # reader 调用 5
        ctx = int((reader("context_window [200000]:") or "200000").strip() or 200000)   # reader 调用 6
        pin = (reader("价格 in (USD/1M, 留空跳过):") or "").strip()   # reader 调用 7
        pout = (reader("价格 out (USD/1M, 留空跳过):") or "").strip() if pin else ""
        price_in = float(pin) if pin else None
        price_out = float(pout) if pout else None
        # 连通+格式探针(必做)
        writer("正在连通测试…")
        res = await probe_connection(protocol=protocol, base_url=base_url, model=model,
                                     api_key=api_key)
        writer(f"[{res.rating}] {res.message}")
        if not res.connected:
            again = (reader("连不上,重配这个模型?(Y/n):") or "y").strip().lower()
            if again != "n":
                continue
        # 可选深度探针(默认跳过)
        if (reader("要顺手深测一下吗?(真跑 write+verify, ~10-30s) [y/N]:") or "n").strip().lower() == "y":   # reader 调用 8
            writer("(深度探针见 Task 10;此处占位:已跳过)")
        # profile name 自动从 model id 推导,不额外提问(保持 reader 调用数可预测)
        name = model.lower().replace(" ", "-")
        write_profile(config_dir=cdir, name=name, protocol=protocol, base_url=base_url,
                      model=model, api_key=api_key, api_key_env=api_key_env,
                      max_tokens=max_tokens, context_window=ctx,
                      price_in=price_in, price_out=price_out, set_active=True)
        writer(f"已保存 '{name}' 并设为当前模型。")
        writer("注意:API key 以明文存于 ~/.argos/.env(权限 0600),不加密。")
        if (reader("再配一个模型?(y/N):") or "n").strip().lower() != "y":   # reader 调用 9
            break
    writer("setup 完成。运行 `argos` 即用当前模型。")
