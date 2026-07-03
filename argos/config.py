"""Runtime configuration loader.

Persistent config lives at ARGOS_CONFIG_DIR/config.json and local environment
overrides live at ARGOS_CONFIG_DIR/.env when exported by setup flows.
"""
from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from argos.i18n import t


def _load_env_local() -> dict[str, str]:
    env: dict[str, str] = {}
    root = Path(__file__).resolve().parents[1]
    envfile = root / ".env.local"
    if envfile.exists():
        for line in envfile.read_text().splitlines():
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                v = v.strip()
                if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
                    v = v[1:-1]
                env[k.strip()] = v
    return env


_ENV = _load_env_local()


def get(key: str, default: str | None = None) -> str | None:
    """Internal documentation."""
    return os.environ.get(key) or _ENV.get(key, default)


def _first(*keys: str, default: str | None = None) -> str | None:
    """Internal documentation."""
    for k in keys:
        v = get(k)
        if v:
            return v
    return default


LLM_PROVIDER = _first("ARGOS_LLM_PROVIDER", "VITE_LLM_PROVIDER", default="anthropic")
_DEFAULT_KEY_RAW = _first("ARGOS_LLM_KEY", "VITE_LLM_KEY", "VITE_MINIMAX_KEY", default="") or ""
DEFAULT_KEYS: list[str] = [k.strip() for k in _DEFAULT_KEY_RAW.split(",") if k.strip()]
_DEFAULT_MODEL = _first("ARGOS_LLM_MODEL", "VITE_LLM_MODEL", "VITE_MINIMAX_MODEL", default="MiniMax-M2")
_DEFAULT_BASE = _first("ARGOS_LLM_BASE", "VITE_LLM_BASE", "VITE_MINIMAX_URL",
                       default="https://api.minimaxi.com/anthropic")
_DEFAULT_MAX_TOKENS = int(get("ARGOS_LLM_MAX_TOKENS", "4096") or "4096")
_DEFAULT_CONTEXT_WINDOW = int(get("ARGOS_LLM_CONTEXT_WINDOW", "192000") or "192000")
_DEFAULT_PRICE_IN = get("ARGOS_LLM_PRICE_IN")
_DEFAULT_PRICE_OUT = get("ARGOS_LLM_PRICE_OUT")

WORKER_KEYS = DEFAULT_KEYS
LLM_KEY = DEFAULT_KEYS[0] if DEFAULT_KEYS else None
LLM_MODEL = _DEFAULT_MODEL
LLM_BASE = _DEFAULT_BASE
MINIMAX_KEY = LLM_KEY
MINIMAX_MODEL = LLM_MODEL
MINIMAX_BASE = LLM_BASE


try:
    from argos.core.models import ModelTier  # canonical
except Exception:
    @dataclass(frozen=True, slots=True)
    class ModelTier:  # type: ignore[no-redef]
        name: str
        model: str
        base_url: str
        max_tokens: int
        context_window: int = 200_000
        protocol: str = "anthropic"


DEFAULT_TIER = ModelTier(name="default", model=_DEFAULT_MODEL or "MiniMax-M2",
                         base_url=_DEFAULT_BASE or "https://api.minimaxi.com/anthropic",
                         max_tokens=_DEFAULT_MAX_TOKENS,
                         context_window=_DEFAULT_CONTEXT_WINDOW)


if _DEFAULT_PRICE_IN and _DEFAULT_PRICE_OUT:
    try:
        from argos.core.observability import PRICING as _PRICING
        _PRICING[_DEFAULT_MODEL or "MiniMax-M2"] = {
            "in": float(_DEFAULT_PRICE_IN), "out": float(_DEFAULT_PRICE_OUT),
        }
    except Exception:  # noqa: BLE001
        pass


import json as _json


class ConfigError(Exception):
    """Internal documentation."""


def _write_json_atomic(path: Path, raw: dict) -> None:
    tmp = path.with_name(f"{path.name}.tmp")
    try:
        tmp.write_text(_json.dumps(raw, indent=2, ensure_ascii=False))
        os.replace(tmp, path)
    except Exception:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
        raise


def _config_dir() -> Path:
    return Path(get("ARGOS_CONFIG_DIR") or (Path.home() / ".argos")).expanduser()


def load_env_file(path: Path) -> dict[str, str]:
    """Internal documentation."""
    env: dict[str, str] = {}
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if line.startswith("export "):
                line = line[len("export "):].lstrip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                v = v.strip()
                if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
                    v = v[1:-1]
                env[k.strip()] = v
    return env


_REQUIRED = ("protocol", "base_url", "model")
_VALID_PROTOCOLS = ("anthropic", "openai")
_ENV_VAR_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _validate_profile(name: str, m: dict, *, require_key_env: bool = True) -> None:
    """Internal documentation."""
    if not str(name).strip() or "\n" in str(name) or "\r" in str(name):
        raise ConfigError(t("config.profile.missing_field", name=name, field="profile name"))
    if not isinstance(m, dict):
        raise ConfigError(t("config.profile.missing_field", name=name, field="profile object"))
    for f in _REQUIRED:
        value = m.get(f)
        if not isinstance(value, str) or not value.strip() or "\n" in value or "\r" in value:
            raise ConfigError(t("config.profile.missing_field", name=name, field=f))
    base_url = urlparse(m["base_url"])
    if base_url.scheme not in ("http", "https") or not base_url.netloc:
        raise ConfigError(t("config.profile.invalid_base_url", name=name, base_url=m["base_url"]))
    api_key_env = m.get("api_key_env")
    if require_key_env and (not isinstance(api_key_env, str) or not api_key_env.strip()):
        raise ConfigError(t("config.profile.missing_field", name=name, field="api_key_env"))
    if api_key_env and (not isinstance(api_key_env, str) or not _ENV_VAR_RE.fullmatch(api_key_env)):
        raise ConfigError(t("config.profile.invalid_api_key_env", name=name, env=api_key_env))
    if m["protocol"] not in _VALID_PROTOCOLS:
        raise ConfigError(t(
            "config.profile.invalid_protocol",
            name=name, protocol=m["protocol"], valid=_VALID_PROTOCOLS,
        ))
    try:
        if isinstance(m.get("max_tokens"), (bool, float)) or isinstance(m.get("context_window"), (bool, float)):
            raise TypeError("token limit is not an integer")
        mt = int(m.get("max_tokens", 4096))
        cw = int(m.get("context_window", 200_000))
    except (ValueError, TypeError) as e:
        raise ConfigError(
            t("config.profile.non_integer_tokens", name=name, exc=e)) from e
    if mt <= 0 or cw <= 0:
        raise ConfigError(
            t("config.profile.non_positive_tokens", name=name, mt=mt, cw=cw))
    if "multimodal" in m and not isinstance(m["multimodal"], bool):
        raise ConfigError(t("config.profile.invalid_multimodal", name=name))
    if "embedding_model" in m:
        embedding_model = m["embedding_model"]
        if not isinstance(embedding_model, str) or not embedding_model.strip() or "\n" in embedding_model or "\r" in embedding_model:
            raise ConfigError(t("config.profile.missing_field", name=name, field="embedding_model"))
    has_price_in = m.get("price_in") is not None
    has_price_out = m.get("price_out") is not None
    if has_price_in != has_price_out:
        raise ConfigError(t("config.profile.invalid_price", name=name))
    if has_price_in:
        try:
            if isinstance(m["price_in"], bool) or isinstance(m["price_out"], bool):
                raise TypeError("boolean is not a price")
            price_in = float(m["price_in"])
            price_out = float(m["price_out"])
        except (ValueError, TypeError) as e:
            raise ConfigError(t("config.profile.invalid_price", name=name)) from e
        if not math.isfinite(price_in) or not math.isfinite(price_out) or price_in < 0 or price_out < 0:
            raise ConfigError(t("config.profile.invalid_price", name=name))


@dataclass(frozen=True, slots=True)
class ArgosConfig:
    active: str
    tiers: dict  # name -> ModelTier
    key_envs: dict  # name -> api_key_env(str)
    secrets: dict
    embed_models: dict


def load_config() -> ArgosConfig:
    """Internal documentation."""
    cdir = _config_dir()
    cfile = cdir / "config.json"
    if not cfile.exists():
        raise ConfigError(t("config.load.no_config_file", path=cfile))
    try:
        raw = _json.loads(cfile.read_text())
    except (_json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ConfigError(t("config.load.json_parse_error", exc=e)) from e
    if not isinstance(raw, dict):
        raise ConfigError(t("config.load.json_parse_error", exc="top-level JSON must be an object"))
    models = raw.get("models") or {}
    if not isinstance(models, dict):
        raise ConfigError(t("config.profile.missing_field", name="config", field="models"))
    active = raw.get("active")
    if not isinstance(active, str) or not active.strip() or "\n" in active or "\r" in active:
        raise ConfigError(t("config.load.active_not_in_models", active=active))
    if not models or active not in models:
        raise ConfigError(t("config.load.active_not_in_models", active=active))
    try:
        secrets = load_env_file(cdir / ".env")
    except (OSError, UnicodeDecodeError) as e:
        raise ConfigError(t("config.load.env_parse_error", path=cdir / ".env", exc=e)) from e
    tiers, key_envs, embed_models = {}, {}, {}
    for name, m in models.items():
        _validate_profile(name, m)
        max_tokens = int(m.get("max_tokens", 4096))
        context_window = int(m.get("context_window", 200_000))
        tiers[name] = ModelTier(
            name=name, model=m["model"], base_url=m["base_url"],
            max_tokens=max_tokens, context_window=context_window, protocol=m["protocol"],
            multimodal=m.get("multimodal"),
        )
        key_envs[name] = m.get("api_key_env", "")
        embed_models[name] = m.get("embedding_model", "")
        if m.get("price_in") is not None and m.get("price_out") is not None:
            try:
                from argos.core.observability import PRICING
                PRICING[m["model"]] = {"in": float(m["price_in"]), "out": float(m["price_out"])}
            except Exception:  # noqa: BLE001
                pass
    return ArgosConfig(active=active, tiers=tiers, key_envs=key_envs,
                       secrets=secrets, embed_models=embed_models)


def _has_config_file() -> bool:
    return (_config_dir() / "config.json").exists()


def sandbox_enabled() -> bool:
    """Internal documentation."""
    return os.environ.get("ARGOS_SANDBOX", "").strip().lower() in ("1", "true", "yes", "on")


def weak_model() -> bool:
    """Internal documentation."""
    return os.environ.get("ARGOS_WEAK_MODEL", "").strip().lower() in ("1", "true", "yes", "on")


def extra_write_dirs() -> list[Path]:
    """Internal documentation."""
    raw = os.environ.get("ARGOS_ADD_DIRS", "")
    if not raw:
        return []
    out: list[Path] = []
    seen: set[str] = set()
    for part in raw.split(os.pathsep):
        part = part.strip()
        if not part:
            continue
        try:
            p = Path(part).expanduser().resolve()
        except (OSError, RuntimeError):
            continue
        s = str(p)
        if s not in seen:
            seen.add(s)
            out.append(p)
    return out


def active_tier():
    """Internal documentation."""
    if _has_config_file():
        cfg = load_config()
        return cfg.tiers[cfg.active]
    return DEFAULT_TIER


def active_key() -> str | None:
    """Internal documentation."""
    if _has_config_file():
        cfg = load_config()
        env_name = cfg.key_envs.get(cfg.active) or ""
        return os.environ.get(env_name) or cfg.secrets.get(env_name) or None
    return DEFAULT_KEYS[0] if DEFAULT_KEYS else None


def active_embedder():
    """Internal documentation."""
    try:
        if not _has_config_file():
            return None
        cfg = load_config()
        tier = cfg.tiers[cfg.active]
        emb_model = cfg.embed_models.get(cfg.active) or ""
        key = active_key()
        if tier.protocol != "openai" or not emb_model or not key:
            return None
        from argos.memory.embedding import OpenAIEmbedder
        return OpenAIEmbedder(base_url=tier.base_url, api_key=key, model=emb_model)
    except Exception:  # noqa: BLE001
        return None


def tier_for(name: str):
    """Internal documentation."""
    if not isinstance(name, str) or not name.strip() or "\n" in name or "\r" in name:
        raise ConfigError(t("config.tier_for.not_found", name=name, available=[]))
    if _has_config_file():
        cfg = load_config()
        if name not in cfg.tiers:
            raise ConfigError(t("config.tier_for.not_found", name=name, available=list(cfg.tiers)))
        return cfg.tiers[name]
    if name == DEFAULT_TIER.name:
        return DEFAULT_TIER
    raise ConfigError(t("config.tier_for.no_config", name=name, default=DEFAULT_TIER.name))


def key_for(name: str) -> str | None:
    """Internal documentation."""
    if not isinstance(name, str) or not name.strip() or "\n" in name or "\r" in name:
        raise ConfigError(t("config.tier_for.not_found", name=name, available=[]))
    if _has_config_file():
        cfg = load_config()
        if name not in cfg.key_envs:
            raise ConfigError(t("config.tier_for.not_found", name=name, available=list(cfg.tiers)))
        env_name = cfg.key_envs.get(name) or ""
        return os.environ.get(env_name) or cfg.secrets.get(env_name) or None
    if name != DEFAULT_TIER.name:
        raise ConfigError(t("config.tier_for.no_config", name=name, default=DEFAULT_TIER.name))
    return DEFAULT_KEYS[0] if DEFAULT_KEYS else None


def list_profiles() -> list[str]:
    """Internal documentation."""
    if not _has_config_file():
        return [DEFAULT_TIER.name]
    return list(load_config().tiers)


def set_active(name: str) -> None:
    """Internal documentation."""
    cfile = _config_dir() / "config.json"
    if not cfile.exists():
        raise ConfigError(t("config.set_active.no_config"))
    try:
        raw = _json.loads(cfile.read_text())
    except (_json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ConfigError(t("config.load.json_parse_error", exc=e)) from e
    if not isinstance(raw, dict):
        raise ConfigError(t("config.load.json_parse_error", exc="top-level JSON must be an object"))
    models = raw.get("models") or {}
    if not isinstance(models, dict):
        raise ConfigError(t("config.profile.missing_field", name="config", field="models"))
    if not isinstance(name, str) or not name.strip() or "\n" in name or "\r" in name:
        raise ConfigError(t("config.set_active.not_found", name=name))
    if name not in models:
        raise ConfigError(t("config.set_active.not_found", name=name))
    _validate_profile(name, models[name])
    raw["active"] = name
    _write_json_atomic(cfile, raw)
