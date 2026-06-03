"""配置:从仓库根的 .env.local 读 LLM provider 配置(key/model/base/provider,与前端共用一份)。"""
from __future__ import annotations

import os
from pathlib import Path


def _load_env_local() -> dict[str, str]:
    env: dict[str, str] = {}
    # agent/argos_agent/config.py → 仓库根是上上上级
    envfile = Path(__file__).resolve().parents[2] / ".env.local"
    if envfile.exists():
        for line in envfile.read_text().splitlines():
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


_ENV = _load_env_local()


def get(key: str, default: str | None = None) -> str | None:
    # 环境变量优先(打包后由 Tauri 注入),其次 .env.local(开发)。
    return os.environ.get(key) or _ENV.get(key, default)


# 通用 LLM 配置。优先读新 VITE_LLM_*,回退旧 VITE_MINIMAX_*(保已配置用户零破坏)。
LLM_PROVIDER = get("VITE_LLM_PROVIDER", "anthropic")  # anthropic | openai
LLM_KEY = get("VITE_LLM_KEY") or get("VITE_MINIMAX_KEY")
LLM_MODEL = get("VITE_LLM_MODEL") or get("VITE_MINIMAX_MODEL", "MiniMax-M2")
LLM_BASE = get("VITE_LLM_BASE") or get("VITE_MINIMAX_URL", "https://api.minimaxi.com/anthropic")

# 向后兼容别名(仍有代码引用 MINIMAX_*):指向通用值。
MINIMAX_KEY = LLM_KEY
MINIMAX_MODEL = LLM_MODEL
MINIMAX_BASE = LLM_BASE
