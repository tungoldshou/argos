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
# 模型单价(USD / 1M tokens)——可选。设了才能在 UI 显真实成本;不设则诚实显 $(N/A),
# 绝不为自带模型编造占位价(诚实协议)。两价都设才生效(不接受半价)。
_WORKER_PRICE_IN = get("ARGOS_LLM_PRICE_IN")
_WORKER_PRICE_OUT = get("ARGOS_LLM_PRICE_OUT")

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
        protocol: str = "anthropic"


WORKER_TIER = ModelTier(name="worker", model=_WORKER_MODEL or "MiniMax-M2",
                        base_url=_WORKER_BASE or "https://api.minimaxi.com/anthropic",
                        max_tokens=_WORKER_MAX_TOKENS,
                        context_window=_WORKER_CONTEXT_WINDOW)
PREMIUM_TIER = ModelTier(name="premium", model=_PREMIUM_MODEL or "claude-sonnet-4-6",
                         base_url=_PREMIUM_BASE or "https://api.anthropic.com",
                         max_tokens=_PREMIUM_MAX_TOKENS,
                         context_window=_PREMIUM_CONTEXT_WINDOW)


# ── 用户自带模型的单价注入(可选) ────────────────────────────────────────────
# 用户在 .env.local / 环境变量里设 ARGOS_LLM_PRICE_IN / ARGOS_LLM_PRICE_OUT 后,
# 把真实单价注册进 observability.PRICING,让成本栏对自带模型(如 MiniMax-M3)显真实成本。
# 不设则该模型不在表里 → loop 诚实回退 $(N/A),不编价。
if _WORKER_PRICE_IN and _WORKER_PRICE_OUT:
    try:
        from argos_agent.core.observability import PRICING as _PRICING
        _PRICING[_WORKER_MODEL or "MiniMax-M2"] = {
            "in": float(_WORKER_PRICE_IN), "out": float(_WORKER_PRICE_OUT),
        }
    except Exception:  # noqa: BLE001 — 注册失败不应阻断启动;成本只是退回 $(N/A)
        pass


# ── 声明式配置:config.json + .env 加载器(Phase 2 Task 4) ───────────────────
import json as _json


class ConfigError(Exception):
    """配置文件畸形/缺字段/active 悬空 —— fail-closed,诚实报错不假装能跑。"""


def _config_dir() -> Path:
    return Path(get("ARGOS_CONFIG_DIR") or (Path.home() / ".argos")).expanduser()


def load_env_file(path: Path) -> dict[str, str]:
    """读 ~/.argos/.env(KEY=value 一行一个);文件不存在返回空 dict。"""
    env: dict[str, str] = {}
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


_REQUIRED = ("protocol", "base_url", "model")


@dataclass(frozen=True, slots=True)
class ArgosConfig:
    active: str
    tiers: dict  # name -> ModelTier
    key_envs: dict  # name -> api_key_env(str)
    secrets: dict  # ~/.argos/.env 读出的密钥表


def load_config() -> ArgosConfig:
    """加载 ~/.argos/config.json + ~/.argos/.env,构造 ModelTier 表。
    校验 fail-closed:active 悬空 / 缺必填 / json 畸形 → ConfigError。价格注入 PRICING。"""
    cdir = _config_dir()
    cfile = cdir / "config.json"
    if not cfile.exists():
        raise ConfigError(f"无 {cfile}")   # Task 5 的回退在 active_tier 层处理
    try:
        raw = _json.loads(cfile.read_text())
    except _json.JSONDecodeError as e:
        raise ConfigError(f"config.json 解析失败:{e}") from e
    models = raw.get("models") or {}
    active = raw.get("active")
    if not models or active not in models:
        raise ConfigError(f"active='{active}' 不在 models 中(或 models 为空)")
    secrets = load_env_file(cdir / ".env")
    tiers, key_envs = {}, {}
    for name, m in models.items():
        for f in _REQUIRED:
            if not m.get(f):
                raise ConfigError(f"profile '{name}' 缺必填字段 '{f}'")
        tiers[name] = ModelTier(
            name=name, model=m["model"], base_url=m["base_url"],
            max_tokens=int(m.get("max_tokens", 4096)),
            context_window=int(m.get("context_window", 200_000)),
            protocol=m["protocol"],
        )
        key_envs[name] = m.get("api_key_env", "")
        if m.get("price_in") is not None and m.get("price_out") is not None:
            try:
                from argos_agent.core.observability import PRICING
                PRICING[m["model"]] = {"in": float(m["price_in"]), "out": float(m["price_out"])}
            except Exception:  # noqa: BLE001
                pass
    return ArgosConfig(active=active, tiers=tiers, key_envs=key_envs, secrets=secrets)


def _has_config_file() -> bool:
    return (_config_dir() / "config.json").exists()


def active_tier():
    """当前激活模型的 ModelTier(优先 config.json;无则旧 env 回退至 WORKER_TIER)。"""
    if _has_config_file():
        cfg = load_config()
        return cfg.tiers[cfg.active]
    # 向后兼容:无 config.json → 用旧 env 合成的 WORKER_TIER(模块级已构造,protocol 默认 anthropic)。
    return WORKER_TIER


def active_key() -> str | None:
    """当前激活模型的密钥:进程 env > ~/.argos/.env > None。无 config.json 则回退 WORKER_KEYS。"""
    if _has_config_file():
        cfg = load_config()
        env_name = cfg.key_envs.get(cfg.active) or ""
        return os.environ.get(env_name) or cfg.secrets.get(env_name) or None
    return WORKER_KEYS[0] if WORKER_KEYS else None
