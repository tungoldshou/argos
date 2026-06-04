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
