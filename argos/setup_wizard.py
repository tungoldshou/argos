from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from argos.i18n import t


class _NotATTY(Exception):
    pass


def _arrow_select(options: list[str], *, title: str, writer) -> int:
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
                body = f"\x1b[7m{body}\x1b[0m"
            out.write(f"\r\x1b[K{body}\r\n")
        out.flush()

    draw()
    try:
        tty.setraw(fd)
        while True:
            ch = sys.stdin.read(1)
            if ch == "\x1b":
                seq = sys.stdin.read(2)
                if seq == "[A":
                    idx = (idx - 1) % n
                elif seq == "[B":
                    idx = (idx + 1) % n
                else:
                    continue
            elif ch in ("\r", "\n"):
                break
            elif ch == "\x03":                     # Ctrl-C
                raise KeyboardInterrupt
            else:
                continue
            out.write(f"\x1b[{n}A")
            draw()
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
    out.write("\r\n")
    out.flush()
    return idx

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
    f = config_dir / "config.json"
    if not f.exists():
        return {"models": {}}
    def backup_corrupt() -> dict:
        backup = config_dir / "config.json.corrupt.bak"
        idx = 1
        while backup.exists():
            backup = config_dir / f"config.json.corrupt.bak.{idx}"
            idx += 1
        try:
            f.replace(backup)
        except OSError as e:
            from argos.config import ConfigError
            raise ConfigError(t("setup.corrupt_backup_failed", path=f, err=e)) from e
        return {"models": {}}
    try:
        data = json.loads(f.read_text())
    except (json.JSONDecodeError, UnicodeDecodeError):
        return backup_corrupt()
    if not isinstance(data, dict):
        return backup_corrupt()
    if "models" in data and not isinstance(data["models"], dict):
        return backup_corrupt()
    return data


def _validate_final_config(cfg: dict) -> None:
    from argos import config as _config

    models = cfg.get("models")
    if not isinstance(models, dict):
        raise _config.ConfigError(t("config.profile.missing_field", name="config", field="models"))
    active = cfg.get("active")
    if not isinstance(active, str) or active not in models:
        raise _config.ConfigError(t("config.load.active_not_in_models", active=active))
    for model_name, profile in models.items():
        _config._validate_profile(model_name, profile)


def _ask_int(reader, writer, prompt: str, default: int) -> int:
    raw = (reader(prompt) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        writer(t("setup.not_integer", val=raw, default=default))
        return default


def _append_env(config_dir: Path, name: str, value: str) -> None:
    if "\n" in value or "\r" in value:
        from argos.config import ConfigError
        raise ConfigError(t("setup.key_invalid"))
    f = config_dir / ".env"
    try:
        lines = f.read_text().splitlines() if f.exists() else []
    except UnicodeDecodeError:
        backup = config_dir / ".env.corrupt.bak"
        idx = 1
        while backup.exists():
            backup = config_dir / f".env.corrupt.bak.{idx}"
            idx += 1
        f.replace(backup)
        lines = []
    lines = [
        ln for ln in lines
        if "=" not in ln or ln.split("=", 1)[0].strip().removeprefix("export ").strip() != name
    ]
    lines.append(f"{name}={value}")
    content = "\n".join(lines) + "\n"
    tmp = f.with_suffix(".env.tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.fchmod(fd, 0o600)
        os.write(fd, content.encode())
    finally:
        os.close(fd)
    os.replace(tmp, f)
    os.chmod(f, 0o600)


def _restore_env(config_dir: Path, old_content: bytes | None) -> None:
    f = config_dir / ".env"
    if old_content is None:
        try:
            f.unlink()
        except FileNotFoundError:
            pass
        return
    tmp = f.with_suffix(".env.tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.fchmod(fd, 0o600)
        os.write(fd, old_content)
    finally:
        os.close(fd)
    os.replace(tmp, f)
    os.chmod(f, 0o600)


def _write_config_atomic(config_dir: Path, cfg: dict) -> None:
    target = config_dir / "config.json"
    tmp = config_dir / "config.json.tmp"
    try:
        tmp.write_text(json.dumps(cfg, indent=2, ensure_ascii=False))
        os.replace(tmp, target)
    except Exception:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
        raise


def _env_name_for_profile(name: str) -> str:
    """Derive a shell-friendly env var name from a profile name."""
    stem = re.sub(r"[^A-Z0-9]+", "_", name.upper()).strip("_")
    if stem[:1].isdigit():
        stem = f"ARGOS_{stem}"
    return f"{stem or 'ARGOS_PROFILE'}_KEY"


def _profile_key_available(config_dir: Path, cfg: dict, profile_name: str | None) -> bool:
    if not profile_name:
        return False
    models = cfg.get("models")
    if not isinstance(models, dict):
        return False
    profile = models.get(profile_name)
    if not isinstance(profile, dict):
        return False
    env_name = profile.get("api_key_env")
    if not isinstance(env_name, str) or not env_name.strip():
        return False
    env_name = env_name.strip()
    if os.environ.get(env_name):
        return True
    env_file = config_dir / ".env"
    try:
        lines = env_file.read_text().splitlines()
    except (FileNotFoundError, UnicodeDecodeError, OSError):
        return False
    for line in lines:
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().removeprefix("export ").strip()
        if key == env_name and value.strip():
            return True
    return False


def write_profile(*, config_dir: Path, name: str, protocol: str, base_url: str, model: str,
                  api_key: str | None, api_key_env: str, set_active: bool,
                  max_tokens: int = 4096, context_window: int = 200_000,
                  price_in: float | None = None, price_out: float | None = None,
                  embedding_model: str = "", multimodal: bool | None = None) -> None:
    from argos.config import ConfigError
    if not isinstance(name, str):
        raise ConfigError(t("config.profile.missing_field", name=name, field="profile name"))
    for field, value in (
        ("protocol", protocol),
        ("base_url", base_url),
        ("model", model),
        ("api_key_env", api_key_env),
        ("embedding_model", embedding_model),
    ):
        if not isinstance(value, str):
            raise ConfigError(t("config.profile.missing_field", name=name, field=field))
    if api_key is not None and not isinstance(api_key, str):
        raise ConfigError(t("setup.key_invalid"))
    name = name.strip()
    protocol = protocol.strip().lower()
    base_url = base_url.strip().rstrip("/")
    model = model.strip()
    api_key_env = api_key_env.strip()
    if api_key is not None:
        api_key = api_key.strip()
        if not api_key:
            raise ConfigError(t("setup.key_empty"))
        if "\n" in api_key or "\r" in api_key:
            raise ConfigError(t("setup.key_invalid"))
    embedding_model = embedding_model.strip()
    prof = {"protocol": protocol, "base_url": base_url, "model": model,
            "api_key_env": api_key_env, "max_tokens": max_tokens,
            "context_window": context_window}
    if price_in is not None or price_out is not None:
        prof["price_in"] = price_in
        prof["price_out"] = price_out
    if embedding_model:
        prof["embedding_model"] = embedding_model
    if multimodal is not None:
        prof["multimodal"] = multimodal
    from argos import config as _config
    _config._validate_profile(name, prof)
    config_dir.mkdir(parents=True, exist_ok=True)
    cfg = _read_config(config_dir)
    cfg.setdefault("models", {})
    cfg["models"][name] = prof
    if set_active or "active" not in cfg or cfg.get("active") not in cfg["models"]:
        cfg["active"] = name
    _validate_final_config(cfg)
    old_env = (config_dir / ".env").read_bytes() if api_key and (config_dir / ".env").exists() else None
    if api_key:
        _append_env(config_dir, api_key_env, api_key)
    try:
        _write_config_atomic(config_dir, cfg)
    except Exception:
        if api_key:
            _restore_env(config_dir, old_env)
        raise


def _config_dir(config_dir: Path | None) -> Path:
    if config_dir is not None:
        return config_dir
    from argos import config as C
    return C.config_dir()


def print_status(*, writer, config_dir: Path | None = None) -> None:
    from argos import config as C

    cdir = _config_dir(config_dir)
    cfile = cdir / "config.json"
    old = os.environ.get("ARGOS_CONFIG_DIR")
    if config_dir is not None:
        os.environ["ARGOS_CONFIG_DIR"] = str(config_dir)
    try:
        if C._has_config_file():
            cfg = C.load_config()
            active = cfg.active
            tier = cfg.tiers[active]
            env_name = cfg.key_envs.get(active, "")
            embedding_model = cfg.embed_models.get(active, "")
            key_found = bool(env_name and (os.environ.get(env_name) or cfg.secrets.get(env_name)))
            key_source = (
                "environment" if env_name and os.environ.get(env_name)
                else ".env" if key_found
                else "missing"
            )
        else:
            embedding_model = ""
            fallback_keys = ("ARGOS_LLM_KEY", "VITE_LLM_KEY", "VITE_MINIMAX_KEY")
            env_name = next((k for k in fallback_keys if os.environ.get(k)), "ARGOS_LLM_KEY")
            key_found = C.active_key() is not None
            if key_found:
                active = C.DEFAULT_TIER.name
                tier = C.active_tier()
            else:
                active = t("setup.status_not_configured_value")
                tier = None
            key_source = (
                "environment" if any(os.environ.get(k) for k in fallback_keys)
                else ".env.local" if key_found
                else "missing"
            )
    except (C.ConfigError, OSError) as e:
        writer(t("setup.status_not_configured", err=e))
        writer(t("setup.status_next_setup"))
        return
    finally:
        if config_dir is not None:
            if old is None:
                os.environ.pop("ARGOS_CONFIG_DIR", None)
            else:
                os.environ["ARGOS_CONFIG_DIR"] = old

    key_state = t("setup.status_key_found") if key_found else t("setup.status_key_missing")

    writer(t("setup.status_active", active=active))
    if tier is None:
        writer(t("setup.status_model_unconfigured"))
    else:
        writer(t(
            "setup.status_model",
            protocol=tier.protocol,
            base_url=tier.base_url,
            model=tier.model,
        ))
    writer(t("setup.status_key", env=env_name or "(none)", status=key_state, source=key_source))
    writer(t(
        "setup.status_embedding",
        model=embedding_model or t("setup.status_embedding_fts5"),
    ))
    if tier is None:
        image_mode = t("setup.status_image_auto")
    elif tier.multimodal is True:
        image_mode = t("setup.status_image_enabled")
    elif tier.multimodal is False:
        image_mode = t("setup.status_image_disabled")
    else:
        image_mode = t("setup.status_image_auto")
    writer(t("setup.status_image", mode=image_mode))
    writer(t("setup.status_config", path=cfile))
    if not key_found:
        writer(t("setup.status_next_setup"))



@dataclass(frozen=True, slots=True)
class ProbeResult:
    connected: bool
    codeact_ok: bool
    rating: str
    message: str


def _probe_prompt() -> str:
    return t("setup.probe_prompt")
_PROBE_TIMEOUT_S = 20.0


async def probe_connection(*, protocol: str, base_url: str, model: str, api_key: str | None,
                           client_factory=None) -> ProbeResult:
    from argos.core.models import ModelClient, CredentialPool, ModelTier
    tier = ModelTier(name="probe", model=model, base_url=base_url, max_tokens=256,
                     context_window=8192, protocol=protocol)
    if client_factory is None:
        def client_factory(t, k):
            return ModelClient(tier=t, pool=CredentialPool([k or "x"]))
    client = client_factory(tier, api_key)
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
    except Exception as e:  # noqa: BLE001
        detail = str(e)
        return ProbeResult(False, False, t("setup.probe_rating_fail"),
                           t("setup.probe_connect_error", detail=detail[:200]))
    if extract_code_block(out) is not None:
        return ProbeResult(True, True, t("setup.probe_rating_ok"),
                           t("setup.probe_ok_message"))
    return ProbeResult(True, False, t("setup.probe_rating_marginal"),
                       t("setup.probe_marginal_message"))



def _rule(console, key: str) -> None:
    if console is not None:
        console.rule(f"[dim]{t(key)}[/dim]")


def _banner(console) -> None:
    if console is not None:
        console.print(t("setup.banner"), style="bold cyan")


def _emit_probe(console, writer, res: "ProbeResult") -> None:
    line = t("setup.probe_rating", rating=res.rating, message=res.message)
    if console is not None:
        console.print(line, style="green" if res.codeact_ok else ("yellow" if res.connected else "red"))
    else:
        writer(line)


def _select_key_method(reader, writer, console) -> str:
    try:
        idx = _arrow_select([t("setup.key_method_paste"), t("setup.key_method_env")],
                            title=t("setup.section_apikey"), writer=writer)
        return "paste" if idx == 0 else "env"
    except _NotATTY:
        while True:
            raw = (reader(t("setup.prompt_key_method")) or "paste").strip().lower()
            if raw in {"", "1", "p", "paste"}:
                return "paste"
            if raw in {"2", "e", "env", "environment", "environment variable"}:
                return "env"
            writer(t("setup.invalid_choice"))


async def _probe_with_status(console, writer, *, protocol, base_url, model, api_key) -> "ProbeResult":
    if console is not None:
        with console.status(t("setup.probing")):
            return await probe_connection(protocol=protocol, base_url=base_url, model=model, api_key=api_key)
    writer(t("setup.probing"))
    return await probe_connection(protocol=protocol, base_url=base_url, model=model, api_key=api_key)


async def run(*, reader, writer, config_dir: Path | None = None,
              console=None, advanced: bool = False) -> None:
    from argos import config as C
    cdir = _config_dir(config_dir)
    names = list(PRESETS)
    _banner(console)
    try:
        while True:
            _rule(console, "setup.section_provider")
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
                    lowered = choice.lower()
                    matches = [i for i, n in enumerate(names) if n.lower() == lowered]
                    if not matches:
                        matches = [i for i, n in enumerate(names) if n.lower().startswith(lowered)]
                    if not matches:
                        writer(t("setup.invalid_choice"))
                        continue
                    if len(matches) > 1:
                        writer(t(
                            "setup.ambiguous_provider_choice",
                            choice=choice,
                            matches=", ".join(names[i] for i in matches),
                        ))
                        continue
                    pidx = matches[0]
            preset = PRESETS[names[pidx]]
            protocol = preset["protocol"] or (reader(t("setup.prompt_protocol")) or "openai").strip().lower()
            base_url = preset["base_url"] or (reader(t("setup.prompt_base_url")) or "").strip()
            default_model = preset["model"]
            model = (reader(t("setup.prompt_model", default=default_model)) or default_model).strip()
            # API key
            _rule(console, "setup.section_apikey")
            way = _select_key_method(reader, writer, console)
            if way == "env":
                api_key = None
                api_key_env = (reader(t("setup.prompt_env_var_name")) or "").strip()
                if not api_key_env:
                    writer(t("setup.env_var_empty"))
                    continue
                if not C._ENV_VAR_RE.fullmatch(api_key_env):
                    writer(t(
                        "setup.save_failed",
                        err=t("config.profile.invalid_api_key_env", name="probe", env=api_key_env),
                    ))
                    continue
                probe_api_key = os.environ.get(api_key_env)
                if not probe_api_key:
                    writer(t("setup.env_var_missing", env=api_key_env))
                    continue
                derive_env = False
            else:
                api_key = (reader(t("setup.prompt_paste_key")) or "").strip()
                if not api_key:
                    writer(t("setup.key_empty"))
                    continue
                probe_api_key = api_key
                api_key_env = ""
                derive_env = True
            max_tokens, ctx, embedding_model, multimodal = 4096, 200_000, "", None
            if advanced:
                _rule(console, "setup.section_advanced")
                max_tokens = _ask_int(reader, writer, t("setup.prompt_max_tokens"), 4096)
                ctx = _ask_int(reader, writer, t("setup.prompt_context_window"), 200000)
                if protocol == "openai":
                    embedding_model = (reader(t("setup.prompt_embedding_model")) or "").strip()
                else:
                    writer(t("setup.no_embeddings_note"))
                raw_multimodal = (reader(t("setup.prompt_multimodal")) or "").strip().lower()
                if raw_multimodal in ("y", "yes", "true", "1"):
                    multimodal = True
                elif raw_multimodal in ("n", "no", "false", "0"):
                    multimodal = False
                elif raw_multimodal:
                    writer(t("setup.invalid_multimodal_choice"))
                    continue
            try:
                C._validate_profile("probe", {
                    "protocol": protocol,
                    "base_url": base_url,
                    "model": model,
                    "api_key_env": api_key_env,
                    "max_tokens": max_tokens,
                    "context_window": ctx,
                }, require_key_env=not derive_env)
            except C.ConfigError as e:
                writer(t("setup.save_failed", err=e))
                continue
            _rule(console, "setup.section_connect")
            res = await _probe_with_status(console, writer, protocol=protocol,
                                           base_url=base_url, model=model, api_key=probe_api_key)
            _emit_probe(console, writer, res)
            if not res.connected:
                again = (reader(t("setup.reconnect_prompt")) or "y").strip().lower()
                if again != "n":
                    continue
            if (reader(t("setup.deep_probe_prompt")) or "n").strip().lower() == "y":
                writer(t("setup.deep_probing"))
                dres = await deep_probe(protocol=protocol, base_url=base_url, model=model, api_key=probe_api_key)
                writer(t("setup.deep_probe_result", rating=dres.rating, message=dres.message))
            cfg_existing = _read_config(cdir)
            existing_models = cfg_existing.get("models", {})
            default_name = model.lower().replace(" ", "-") if model else "custom"
            raw_name = (reader(t("setup.prompt_profile_name", default=default_name)) or default_name).strip() or default_name
            name = raw_name
            idx = 2
            while name in existing_models:
                name = f"{raw_name}-{idx}"
                idx += 1
            if derive_env:
                api_key_env = _env_name_for_profile(name)
            if existing_models:
                active_name = cfg_existing.get("active") if isinstance(cfg_existing.get("active"), str) else None
                active_usable = _profile_key_available(cdir, cfg_existing, active_name)
                default_active = bool(res.connected and not active_usable)
                prompt_key = "setup.set_active_prompt_default_yes" if default_active else "setup.set_active_prompt"
                default_answer = "y" if default_active else "n"
                make_active = (reader(t(prompt_key)) or default_answer).strip().lower().startswith("y")
            else:
                make_active = True
            if not res.connected and make_active:
                writer(t("setup.warn_set_active_disconnected"))
            try:
                write_profile(config_dir=cdir, name=name, protocol=protocol, base_url=base_url,
                              model=model, api_key=api_key, api_key_env=api_key_env,
                              max_tokens=max_tokens, context_window=ctx,
                              embedding_model=embedding_model, multimodal=multimodal,
                              set_active=make_active)
            except C.ConfigError as e:
                writer(t("setup.save_failed", err=e))
                continue
            except OSError as e:
                writer(t("setup.save_failed_io", err=e))
                continue
            if make_active:
                writer(t("setup.saved_active", name=name))
            else:
                writer(t("setup.saved_inactive", name=name))
            if api_key:
                writer(t("setup.key_stored_warning", path=cdir / ".env"))
            if (reader(t("setup.add_another_prompt")) or "n").strip().lower() != "y":
                writer(t("setup.done_active" if make_active else "setup.done_inactive"))
                next_key = "setup.next_steps_active" if make_active else "setup.next_steps_inactive"
                writer(t(next_key, name=name, config=str(cdir / "config.json")))
                break
    except EOFError:
        writer(t("setup.no_tty", config_path=cdir / "config.json", env_path=cdir / ".env"))
    except KeyboardInterrupt:
        writer(t("setup.cancelled"))



async def deep_probe(*, protocol: str, base_url: str, model: str, api_key: str | None,
                     model_factory=None) -> ProbeResult:
    import tempfile
    from pathlib import Path as _P
    from argos import runtime
    from argos.approval import ApprovalGate
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
        _prev_ws = os.environ.get("ARGOS_WORKSPACE")
        os.environ["ARGOS_WORKSPACE"] = str(proj)
        tok = runtime.use_project(str(proj))
        store = None
        try:
            gate = ApprovalGate()
            broker = CapabilityBroker(gate=gate, egress=EgressPolicy(
                llm_hosts=set(), search_hosts=set(), mcp_hosts=set()),
                signer=ReceiptSigner(key=b"probe"))
            sandbox = SeatbeltExecutor(broker_handler=lambda a, ar: broker.execute_sync(a, ar)[0])
            store = ArgosStore(db_path=str(_P(td) / "p.db"))
            loop = AgentLoop(store=store, bus=EventBus(), sandbox=sandbox, broker=broker,
                             model=model_factory(tier, api_key), verifier=Verifier(max_rounds=3),
                             config=LoopConfig(compaction=False),
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
        except Exception as e:  # noqa: BLE001
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
