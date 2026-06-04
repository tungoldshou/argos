"""argos setup 向导(spec §6)。I/O 解耦:纯逻辑(预设/写配置/探针)可单测,
CLI 交互(run)注入 reader/writer/client 工厂。密钥进 .env(0600),设置进 config.json。"""
from __future__ import annotations

import json
import os
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
