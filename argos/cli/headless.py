from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid

from argos.i18n import t

try:
    from argos.config import ConfigError as _ConfigError
except ImportError:
    _ConfigError = RuntimeError  # type: ignore[assignment,misc]


def add_subparser(sub) -> None:
    p = sub.add_parser(
        "exec",
        help=t("cli.exec.help"),
    )
    p.add_argument("prompt", nargs="?", help=t("cli.exec.prompt.help"))
    p.add_argument("--json", action="store_true", dest="as_json",
                   help=t("cli.exec.json.help"))
    p.add_argument("--full-access", action="store_true",
                   help=t("cli.exec.full_access.help"))
    p.add_argument("--verify", metavar="CMD", dest="verify_cmd",
                   help=t("cli.exec.verify.help"))
    p.add_argument("--project", metavar="PATH", help=t("cli.exec.project.help"))
    p.add_argument("--model", metavar="NAME", help=t("cli.exec.model.help"))
    p.add_argument("--quiet", action="store_true",
                   help=t("cli.exec.quiet.help"))
    p.set_defaults(func=run_exec)


def _read_prompt(args) -> str:
    prompt = getattr(args, "prompt", None)
    if not prompt or prompt == "-":
        try:
            prompt = sys.stdin.read().strip()
        except Exception:  # noqa: BLE001
            prompt = ""
    return (prompt or "").strip()


def run_exec(args) -> int:
    prompt = _read_prompt(args)
    if not prompt:
        print(t("cli.exec.missing_prompt"), file=sys.stderr)
        return 2

    _verify_cmd_arg = getattr(args, "verify_cmd", None)
    if _verify_cmd_arg:
        try:
            from argos.core.types import TRIVIAL_VERIFY_BINS
            import shlex as _shlex
            from pathlib import Path as _Path
            _bin = _Path(_shlex.split(_verify_cmd_arg)[0]).name
            if _bin in TRIVIAL_VERIFY_BINS:
                print(
                    t("cli.exec.trivial_verify", cmd=_verify_cmd_arg),
                    file=sys.stderr,
                )
                return 2
        except Exception:  # noqa: BLE001
            pass

    from argos.app_factory import build_components, build_loop_factory
    from argos.config import ConfigError
    from argos.permissions.mode import PermissionMode
    from argos.protocol.events import (
        CostUpdate, Error, Escalation, PhaseChange, TokenDelta, VerifyVerdict,
    )
    from argos.routing.effort import EffortLevel

    quiet = bool(getattr(args, "quiet", False))

    def _progress(msg: str) -> None:
        if not quiet:
            print(msg, file=sys.stderr, flush=True)

    effective_ws = getattr(args, "project", None) or os.getcwd()
    permission_mode = (
        PermissionMode.FULL_ACCESS
        if getattr(args, "full_access", False)
        else PermissionMode.SMART_APPROVAL
    )

    try:
        _effort = EffortLevel(getattr(args, "effort", None) or EffortLevel.MEDIUM.value)
    except ValueError:
        _effort = EffortLevel.MEDIUM
    try:
        components = build_components(
            workspace=effective_ws,
            model_override=getattr(args, "model", None),
            permission_mode=permission_mode,
            verify_cmd=_verify_cmd_arg,
            effort=_effort,
        )
    except (RuntimeError, ConfigError) as e:
        print(t("cli.exec.no_key", err=e), file=sys.stderr)
        print(t("cli.exec.run_setup_hint"), file=sys.stderr)
        return 2

    if permission_mode is PermissionMode.SMART_APPROVAL:
        gate = components.gate
        gate.set_ask_listener(lambda call_id, _payload: gate.respond(call_id, "deny"))

    loop = build_loop_factory(components)()
    session_id = "exec-" + uuid.uuid4().hex[:8]

    _progress(t("cli.exec.progress_start", prompt=prompt[:80] + ("…" if len(prompt) > 80 else "")))

    state: dict = {
        "phase_text": [], "all_text": [], "verdict": None, "cost": None,
        "escalation": None, "error": None,
        "step": 0,
    }

    _PHASE_LABEL: dict[str, str] = {
        "plan": "plan", "act": "act", "verify": "verify", "report": "report",
    }

    async def _drive() -> None:
        async for ev in loop.run(prompt, session_id):
            if isinstance(ev, TokenDelta):
                state["phase_text"].append(ev.text)
                state["all_text"].append(ev.text)
            elif isinstance(ev, PhaseChange):
                state["phase_text"] = []
                label = _PHASE_LABEL.get(getattr(ev, "phase", ""), getattr(ev, "phase", "?"))
                _progress(t("cli.exec.progress_phase", label=label))
            elif isinstance(ev, VerifyVerdict):
                state["verdict"] = ev.verdict.status
                state["self_verified"] = bool(getattr(ev.verdict, "self_verified", False))
                _progress(t("cli.exec.progress_verify", status=ev.verdict.status))
            elif isinstance(ev, CostUpdate):
                if ev.cost_usd is not None:
                    state["cost"] = ev.cost_usd
            elif isinstance(ev, Escalation):
                state["escalation"] = getattr(ev, "message", None) or getattr(ev, "reason", "") or "agent escalated"
                _progress(t("cli.exec.progress_escalation", msg=state["escalation"]))
            elif isinstance(ev, Error):
                state["error"] = ev.message
                _progress(t("cli.exec.progress_error", msg=state["error"]))

    try:
        asyncio.run(_drive())
    except Exception as e:  # noqa: BLE001
        state["error"] = state["error"] or f"{type(e).__name__}: {e}"
    finally:
        try:
            components.close()
        except Exception:  # noqa: BLE001
            pass

    result_text = "".join(state["phase_text"]).strip() or "".join(state["all_text"]).strip()
    verdict = state["verdict"]
    self_verified = bool(state.get("self_verified", False))
    is_error = bool(state["error"]) or bool(state["escalation"]) or verdict in ("failed", "unverifiable")

    if state["error"]:
        code = 1
    elif verdict == "passed":
        code = 0
    elif verdict in ("failed", "unverifiable"):
        code = 1
    elif state["escalation"]:
        code = 1
    else:
        code = 0

    out_verdict = "passed_self" if (verdict == "passed" and self_verified) else verdict

    if getattr(args, "as_json", False):
        print(json.dumps({
            "result": result_text,
            "verdict": out_verdict,
            "self_verified": self_verified,
            "session_id": session_id,
            "cost_usd": state["cost"],
            "is_error": is_error,
            "escalation": state["escalation"],
            "error": state["error"],
        }, ensure_ascii=False))
    else:
        if result_text:
            print(result_text)
        if state["escalation"]:
            print(f"\n[escalation] {state['escalation']}", file=sys.stderr)
        if state["error"]:
            print(f"\n[error] {state['error']}", file=sys.stderr)
        _label = {
            "passed": t("cli.exec.verdict_passed"),
            "passed_self": t("cli.exec.verdict_passed_self"),
            "failed": t("cli.exec.verdict_failed"),
            "unverifiable": t("cli.exec.verdict_unverifiable"),
        }.get(out_verdict or "", t("cli.exec.verdict_no_test"))
        print(f"[verify] {_label}", file=sys.stderr)

    return code
