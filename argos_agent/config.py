"""配置(契约 §8):ARGOS_* 最高优先,回退 VITE_LLM_* → VITE_MINIMAX_*(零破坏已配用户)。
优先级:os.environ[ARGOS_*] > os.environ[VITE_*] > .env.local > 默认。
组装 WORKER_TIER / PREMIUM_TIER(ModelTier) + WORKER_KEYS(逗号拆分喂 CredentialPool)。"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _load_env_local() -> dict[str, str]:
    env: dict[str, str] = {}
    # config.py 在 argos_agent/ 下 → 仓库根是上一级(parents[1])。
    # 注意:原来在 agent/argos_agent/config.py 时用 parents[2],
    # 现在已移到 argos_agent/config.py(仓库根下一级)故用 parents[1]。
    root = Path(__file__).resolve().parents[1]
    envfile = root / ".env.local"
    if envfile.exists():
        for line in envfile.read_text().splitlines():
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


_ENV = _load_env_local()


def get(key: str, default: str | None = None) -> str | None:
    """环境变量优先(打包后注入),其次 .env.local(开发),最后 default。"""
    return os.environ.get(key) or _ENV.get(key, default)


def _first(*keys: str, default: str | None = None) -> str | None:
    """按序返回第一个有值的 key(实现 ARGOS_* > VITE_LLM_* > VITE_MINIMAX_* 回退链)。"""
    for k in keys:
        v = get(k)
        if v:
            return v
    return default


# ── worker(便宜默认,MiniMax) ─────────────────────────────────────────────
LLM_PROVIDER = _first("ARGOS_LLM_PROVIDER", "VITE_LLM_PROVIDER", default="anthropic")
_WORKER_KEY_RAW = _first("ARGOS_LLM_KEY", "VITE_LLM_KEY", "VITE_MINIMAX_KEY", default="") or ""
WORKER_KEYS: list[str] = [k.strip() for k in _WORKER_KEY_RAW.split(",") if k.strip()]
_WORKER_MODEL = _first("ARGOS_LLM_MODEL", "VITE_LLM_MODEL", "VITE_MINIMAX_MODEL", default="MiniMax-M2")
_WORKER_BASE = _first("ARGOS_LLM_BASE", "VITE_LLM_BASE", "VITE_MINIMAX_URL",
                      default="https://api.minimaxi.com/anthropic")
_WORKER_MAX_TOKENS = int(get("ARGOS_LLM_MAX_TOKENS", "4096") or "4096")
# MiniMax-M2 官方上下文上限 ~192k;可经 ARGOS_LLM_CONTEXT_WINDOW 覆盖(按实际模型填真值)。
_WORKER_CONTEXT_WINDOW = int(get("ARGOS_LLM_CONTEXT_WINDOW", "192000") or "192000")

# ── premium(Claude,--premium) ───────────────────────────────────────────
PREMIUM_KEY = get("ARGOS_PREMIUM_KEY")
_PREMIUM_MODEL = get("ARGOS_PREMIUM_MODEL", "claude-sonnet-4-6")
_PREMIUM_BASE = get("ARGOS_PREMIUM_BASE", "https://api.anthropic.com")
_PREMIUM_MAX_TOKENS = int(get("ARGOS_PREMIUM_MAX_TOKENS", "8192") or "8192")
# Claude 上下文上限 200k;可经 ARGOS_PREMIUM_CONTEXT_WINDOW 覆盖。
_PREMIUM_CONTEXT_WINDOW = int(get("ARGOS_PREMIUM_CONTEXT_WINDOW", "200000") or "200000")

# ── 向后兼容别名(旧代码仍引用) ───────────────────────────────────────────
LLM_KEY = WORKER_KEYS[0] if WORKER_KEYS else None
LLM_MODEL = _WORKER_MODEL
LLM_BASE = _WORKER_BASE
MINIMAX_KEY = LLM_KEY
MINIMAX_MODEL = LLM_MODEL
MINIMAX_BASE = LLM_BASE


# ── ModelTier 组装 ──────────────────────────────────────────────────────
try:
    from argos_agent.core.models import ModelTier  # canonical(Task 5)
except Exception:  # Task 5 未落地时的占位,结构与 canonical 一致
    @dataclass(frozen=True, slots=True)
    class ModelTier:  # type: ignore[no-redef]
        name: str
        model: str
        base_url: str
        max_tokens: int
        context_window: int = 200_000


WORKER_TIER = ModelTier(name="worker", model=_WORKER_MODEL or "MiniMax-M2",
                        base_url=_WORKER_BASE or "https://api.minimaxi.com/anthropic",
                        max_tokens=_WORKER_MAX_TOKENS,
                        context_window=_WORKER_CONTEXT_WINDOW)
PREMIUM_TIER = ModelTier(name="premium", model=_PREMIUM_MODEL or "claude-sonnet-4-6",
                         base_url=_PREMIUM_BASE or "https://api.anthropic.com",
                         max_tokens=_PREMIUM_MAX_TOKENS,
                         context_window=_PREMIUM_CONTEXT_WINDOW)
