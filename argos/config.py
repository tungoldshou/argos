"""配置(契约 §8):ARGOS_* 最高优先,回退 VITE_LLM_* → VITE_MINIMAX_*(零破坏已配用户)。
优先级:os.environ[ARGOS_*] > os.environ[VITE_*] > .env.local > 默认。
模型不绑定、无 worker/premium 档位:实际模型由 config.json 的 active(active_tier/active_key)决定;
无 config.json 时合成单个 DEFAULT_TIER(旧 env 回退,DEFAULT_KEYS 逗号拆分喂 CredentialPool)。"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from argos.i18n import t


def _load_env_local() -> dict[str, str]:
    env: dict[str, str] = {}
    # config.py 在 argos/ 下 → 仓库根是上一级(parents[1])。
    # 注意:原来在 agent/argos/config.py 时用 parents[2],
    # 现在已移到 argos/config.py(仓库根下一级)故用 parents[1]。
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


# ── 默认 profile(模型不绑定,无 worker/premium 档位之分:实际模型由 config.json 的 active /
#    环境变量决定。以下仅是【无 config.json 时】旧 env 用户的回退默认值 —— MiniMax 是历史预设
#    之一,不代表 Argos 绑定 MiniMax;新用户经 `argos setup` 接任意模型)──
LLM_PROVIDER = _first("ARGOS_LLM_PROVIDER", "VITE_LLM_PROVIDER", default="anthropic")
_DEFAULT_KEY_RAW = _first("ARGOS_LLM_KEY", "VITE_LLM_KEY", "VITE_MINIMAX_KEY", default="") or ""
DEFAULT_KEYS: list[str] = [k.strip() for k in _DEFAULT_KEY_RAW.split(",") if k.strip()]
_DEFAULT_MODEL = _first("ARGOS_LLM_MODEL", "VITE_LLM_MODEL", "VITE_MINIMAX_MODEL", default="MiniMax-M2")
_DEFAULT_BASE = _first("ARGOS_LLM_BASE", "VITE_LLM_BASE", "VITE_MINIMAX_URL",
                       default="https://api.minimaxi.com/anthropic")
_DEFAULT_MAX_TOKENS = int(get("ARGOS_LLM_MAX_TOKENS", "4096") or "4096")
_DEFAULT_CONTEXT_WINDOW = int(get("ARGOS_LLM_CONTEXT_WINDOW", "192000") or "192000")
# 模型单价(USD / 1M tokens)——可选。设了才能在 UI 显真实成本;不设则诚实显 $N/A,
# 绝不为自带模型编造占位价(诚实协议)。两价都设才生效(不接受半价)。
_DEFAULT_PRICE_IN = get("ARGOS_LLM_PRICE_IN")
_DEFAULT_PRICE_OUT = get("ARGOS_LLM_PRICE_OUT")

# ── 向后兼容别名(旧代码/旧测试仍引用) ───────────────────────────────────────
WORKER_KEYS = DEFAULT_KEYS   # 旧名别名(已无 worker/premium 档位概念;逐步淘汰)
LLM_KEY = DEFAULT_KEYS[0] if DEFAULT_KEYS else None
LLM_MODEL = _DEFAULT_MODEL
LLM_BASE = _DEFAULT_BASE
MINIMAX_KEY = LLM_KEY
MINIMAX_MODEL = LLM_MODEL
MINIMAX_BASE = LLM_BASE


# ── ModelTier 组装 ──────────────────────────────────────────────────────
try:
    from argos.core.models import ModelTier  # canonical
except Exception:  # canonical 未就绪时的占位,结构与 canonical 一致
    @dataclass(frozen=True, slots=True)
    class ModelTier:  # type: ignore[no-redef]
        name: str
        model: str
        base_url: str
        max_tokens: int
        context_window: int = 200_000
        protocol: str = "anthropic"


# 默认 profile(旧 env 回退用):无 worker/premium 之分,就一个"默认模型"。
# 真实选用走 active_tier()(config.json 的 active);此处仅是无 config 时的回退。
DEFAULT_TIER = ModelTier(name="default", model=_DEFAULT_MODEL or "MiniMax-M2",
                         base_url=_DEFAULT_BASE or "https://api.minimaxi.com/anthropic",
                         max_tokens=_DEFAULT_MAX_TOKENS,
                         context_window=_DEFAULT_CONTEXT_WINDOW)


# ── 用户自带模型的单价注入(可选) ────────────────────────────────────────────
# 用户在 .env.local / 环境变量里设 ARGOS_LLM_PRICE_IN / ARGOS_LLM_PRICE_OUT 后,
# 把真实单价注册进 observability.PRICING,让成本栏对自带模型(如 MiniMax-M3)显真实成本。
# 不设则该模型不在表里 → loop 诚实回退 $N/A,不编价。
if _DEFAULT_PRICE_IN and _DEFAULT_PRICE_OUT:
    try:
        from argos.core.observability import PRICING as _PRICING
        _PRICING[_DEFAULT_MODEL or "MiniMax-M2"] = {
            "in": float(_DEFAULT_PRICE_IN), "out": float(_DEFAULT_PRICE_OUT),
        }
    except Exception:  # noqa: BLE001 — 注册失败不应阻断启动;成本只是退回 $N/A
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
_VALID_PROTOCOLS = ("anthropic", "openai")


def _validate_profile(name: str, m: dict) -> None:
    """校验单个 profile dict(fail-closed,raises ConfigError)。load_config 与 set_active 共用,
    避免把 active 切到一个畸形 profile 后失败被推迟到下次启动才暴露。"""
    for f in _REQUIRED:
        if not m.get(f):
            raise ConfigError(t("config.profile.missing_field", name=name, field=f))
    # protocol 必须在已知集合内:拼错(如 'anthropc')会让 get_protocol 静默退化成 Anthropic
    # 框架去打 OpenAI 端点 → 运行时困惑的假退化;在加载/切换期 fail-closed 明确报错。
    if m["protocol"] not in _VALID_PROTOCOLS:
        raise ConfigError(t(
            "config.profile.invalid_protocol",
            name=name, protocol=m["protocol"], valid=_VALID_PROTOCOLS,
        ))
    # 数字字段:非数字 int() 会漏 ValueError;0/负数会让请求 400 或 on_context 占用%除零。
    # 一律包成 ConfigError 守住 fail-closed 契约,且要求为正整数。
    try:
        mt = int(m.get("max_tokens", 4096))
        cw = int(m.get("context_window", 200_000))
    except (ValueError, TypeError) as e:
        raise ConfigError(
            t("config.profile.non_integer_tokens", name=name, exc=e)) from e
    if mt <= 0 or cw <= 0:
        raise ConfigError(
            t("config.profile.non_positive_tokens", name=name, mt=mt, cw=cw))


@dataclass(frozen=True, slots=True)
class ArgosConfig:
    active: str
    tiers: dict  # name -> ModelTier
    key_envs: dict  # name -> api_key_env(str)
    secrets: dict  # ~/.argos/.env 读出的密钥表
    embed_models: dict  # name -> embedding 模型名(可选;空=该 profile 记忆走 FTS5 不调模型)


def load_config() -> ArgosConfig:
    """加载 ~/.argos/config.json + ~/.argos/.env,构造 ModelTier 表。
    校验 fail-closed:active 悬空 / 缺必填 / json 畸形 → ConfigError。价格注入 PRICING。"""
    cdir = _config_dir()
    cfile = cdir / "config.json"
    if not cfile.exists():
        raise ConfigError(t("config.load.no_config_file", path=cfile))   # Task 5 的回退在 active_tier 层处理
    try:
        raw = _json.loads(cfile.read_text())
    except _json.JSONDecodeError as e:
        raise ConfigError(t("config.load.json_parse_error", exc=e)) from e
    models = raw.get("models") or {}
    active = raw.get("active")
    if not models or active not in models:
        raise ConfigError(t("config.load.active_not_in_models", active=active))
    secrets = load_env_file(cdir / ".env")
    tiers, key_envs, embed_models = {}, {}, {}
    for name, m in models.items():
        _validate_profile(name, m)
        max_tokens = int(m.get("max_tokens", 4096))
        context_window = int(m.get("context_window", 200_000))
        tiers[name] = ModelTier(
            name=name, model=m["model"], base_url=m["base_url"],
            max_tokens=max_tokens, context_window=context_window, protocol=m["protocol"],
            multimodal=m.get("multimodal"),   # 未设→None(走探针);true/false→显式 override
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
    """OS 沙箱是否启用 —— opt-in,**默认关**(对齐 Claude Code:CC 的 OS 沙箱也是 opt-in)。
    `ARGOS_SANDBOX=1`(或 `--sandbox`)开启 Seatbelt/bwrap 的内核级"网络断 + 写牢笼"。

    关闭时治理**不**塌:broker(唯一副作用路径)+ 审批闸 + egress 策略 + smolagents AST 限制
    都不依赖 OS 沙箱、继续生效。仅去掉内核级兜底 —— 诚实代价:AST 允许的模块的裸网络/越界写
    不再被内核拦(与 CC 同档,CC 靠逐命令人工确认补)。关沙箱时启动/UI 必须如实标"未沙箱化"。"""
    return os.environ.get("ARGOS_SANDBOX", "").strip().lower() in ("1", "true", "yes", "on")


def extra_write_dirs() -> list[Path]:
    """`--add-dir` / `ARGOS_ADD_DIRS` 授权的额外可写目录(#2 CC对齐:对齐 CC 的 --add-dir /
    additionalDirectories)。os.pathsep 分隔,expanduser + resolve + 去重。

    语义:这些目录在 workspace 写牢笼【之外】也可写。应用层(write_file/edit_file 的路径 cage +
    hard-path workspace 边界)恒放行它们;OS 层仅在【开沙箱】时把它们加进 Seatbelt/bwrap 可写集。
    用户显式授权 → 视同 workspace 内可写(不再"越界")。"""
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
    """当前激活模型的 ModelTier(优先 config.json;无则旧 env 回退至 DEFAULT_TIER)。"""
    if _has_config_file():
        cfg = load_config()
        return cfg.tiers[cfg.active]
    # 向后兼容:无 config.json → 用旧 env 合成的 DEFAULT_TIER(模块级已构造,protocol 默认 anthropic)。
    return DEFAULT_TIER


def active_key() -> str | None:
    """当前激活模型的密钥:进程 env > ~/.argos/.env > None。无 config.json 则回退 DEFAULT_KEYS。"""
    if _has_config_file():
        cfg = load_config()
        env_name = cfg.key_envs.get(cfg.active) or ""
        return os.environ.get(env_name) or cfg.secrets.get(env_name) or None
    return DEFAULT_KEYS[0] if DEFAULT_KEYS else None


def active_embedder():
    """按 active profile 构造记忆向量召回的 embedder(复用同一 provider 的 base_url+key):
    OpenAI 协议 + 配了 embedding_model → OpenAIEmbedder(打 /embeddings);否则 None → 记忆走 FTS5。
    诚实:Anthropic 协议无 embeddings 端点 / 未配 embedding 模型 / 无 key → 一律 None,不偷调模型。
    无 config.json(旧 env 回退)→ None(要语义召回请 `argos setup` 配 embedding 模型)。"""
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
    except Exception:  # noqa: BLE001 — 任何配置问题 → None → FTS5(fail-soft,不崩)
        return None


def tier_for(name: str):
    """按 profile 名取 ModelTier(供 `argos --model <name>` 启动覆盖用);无 config.json 时只认
    DEFAULT_TIER 的名字,其余 → ConfigError。"""
    if _has_config_file():
        cfg = load_config()
        if name not in cfg.tiers:
            raise ConfigError(t("config.tier_for.not_found", name=name, available=list(cfg.tiers)))
        return cfg.tiers[name]
    if name == DEFAULT_TIER.name:
        return DEFAULT_TIER
    raise ConfigError(t("config.tier_for.no_config", default=DEFAULT_TIER.name))


def key_for(name: str) -> str | None:
    """按 profile 名取密钥(供启动覆盖用)。"""
    if _has_config_file():
        cfg = load_config()
        env_name = cfg.key_envs.get(name) or ""
        return os.environ.get(env_name) or cfg.secrets.get(env_name) or None
    return DEFAULT_KEYS[0] if DEFAULT_KEYS else None


def list_profiles() -> list[str]:
    """返回所有可用 profile 名列表。无 config.json 时返回 ['default'](回退态单 profile)。"""
    if not _has_config_file():
        return [DEFAULT_TIER.name]   # 回退态:单一 profile
    return list(load_config().tiers)


def set_active(name: str) -> None:
    """把 config.json 里的 active 切到 name;不存在的 profile → ConfigError(fail-closed)。
    切换后下次启动/新任务生效(模型在 build_components 时注入)。"""
    cfile = _config_dir() / "config.json"
    if not cfile.exists():
        raise ConfigError(t("config.set_active.no_config"))
    raw = _json.loads(cfile.read_text())
    models = raw.get("models") or {}
    if name not in models:
        raise ConfigError(t("config.set_active.not_found", name=name))
    # fail-closed:切之前校验目标 profile 合法,避免切到畸形 profile 后失败被推迟到下次启动才暴露。
    _validate_profile(name, models[name])
    raw["active"] = name
    cfile.write_text(_json.dumps(raw, indent=2, ensure_ascii=False))
