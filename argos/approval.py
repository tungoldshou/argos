from __future__ import annotations

import asyncio
import contextvars
import enum
import functools
import inspect
import json
import re
import shlex
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Literal
from urllib.parse import urlparse

from argos.i18n import t

if TYPE_CHECKING:
    from argos.permissions.evaluator import DecisionMeta  # noqa: F401


RiskLevel = Literal["low", "medium", "high"]
DecisionKind = Literal["deny", "once", "session", "always"]


class ApprovalLevel(enum.Enum):
    OBSERVE = "observe"
    PROPOSE = "propose"
    CONFIRM = "confirm"
    AUTO = "auto"
    ACCEPT_EDITS = "accept_edits"


@dataclass(frozen=True, slots=True)
class Decision:
    kind: DecisionKind               # deny | once | session | always
    reason: str = ""

    @property
    def approved(self) -> bool:
        return self.kind != "deny"


@dataclass
class _Pending:
    call_id: str
    payload: dict[str, Any]
    created_at: float
    future: asyncio.Future[Decision]
    loop: asyncio.AbstractEventLoop


def _resolve(fut: asyncio.Future, decision: "Decision") -> None:
    if not fut.done():
        fut.set_result(decision)


@dataclass
class _SessionApproval:
    payload_hash: str
    approved_at: float


def _hash_payload(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, ensure_ascii=False)


def _normalized_path(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return str(Path(value).expanduser().resolve(strict=False))


def _url_origin(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    parsed = urlparse(value.strip())
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"
    if parsed.netloc:
        return parsed.netloc.lower()
    return None


def derive_persistent_allow_rule(action: str, args: dict[str, Any]) -> tuple[str, str] | None:
    if action == "run_command":
        cmd = str((args or {}).get("command", "")).strip()
        try:
            toks = shlex.split(cmd)
        except ValueError:
            toks = cmd.split()
        if toks:
            end = next((i for i, tok in enumerate(toks[1:], start=1) if not tok.startswith("-")), 0)
            parts = [re.escape(tok) for tok in toks[: end + 1]]
            return action, "^" + r"\s+".join(parts) + r"(\s|$)"
        return None
    if action in ("write_file", "edit_file"):
        path = _normalized_path((args or {}).get("path") or (args or {}).get("file") or (args or {}).get("filepath"))
        return (action, "^" + re.escape(path) + "$") if path else None
    if action in ("browser_navigate", "web_extract"):
        origin = _url_origin((args or {}).get("url"))
        return (action, "^" + re.escape(origin) + "$") if origin else None
    if action == "mcp_call":
        server = str((args or {}).get("server", "")).strip()
        tool = str((args or {}).get("tool", "")).strip()
        if server and tool:
            return action, "^" + re.escape(f"{server}/{tool}") + "$"
    return None


def _derive_allow_matcher(action: str, args: dict[str, Any]) -> tuple[str, str]:
    return derive_persistent_allow_rule(action, args) or (action, "*")


class ApprovalGate:

    def __init__(
        self,
        level: ApprovalLevel = ApprovalLevel.CONFIRM,
        *,
        permissions_config: "Any | None" = None,
        audit_log: "Any | None" = None,
    ) -> None:
        self.level = level
        self._pending: dict[str, _Pending] = {}
        self._session_approvals: dict[str, _SessionApproval] = {}
        self._workspace: str | None = None
        self._session_id: str = ""
        self._decision_listener: Callable[[str, str, str], None] | None = None
        self._ask_listener: Callable[[str, dict[str, Any]], None] | None = None
        self._permissions_config: Any | None = permissions_config
        self._audit_log: Any | None = audit_log
        self._ask_readonly: bool = False
        self._reversible_check: bool = False
        self._reversible_lookup: "Callable[[str], bool | None] | None" = None
        self._low_risk_auto: bool = False

    def set_level(self, level: ApprovalLevel) -> None:
        self.level = level

    def push_override_semantics(self, level: "ApprovalLevel") -> tuple:
        snap = (self.level, self._low_risk_auto, self._ask_readonly, self._reversible_check)
        if level is ApprovalLevel.CONFIRM:
            self.level = ApprovalLevel.CONFIRM
            self._low_risk_auto = False
            self._ask_readonly = False
        elif level is ApprovalLevel.ACCEPT_EDITS:
            self.level = ApprovalLevel.CONFIRM
            self._low_risk_auto = True
            self._ask_readonly = False
        else:
            self.level = level
        return snap

    def pop_override_semantics(self, snap: tuple) -> None:
        self.level, self._low_risk_auto, self._ask_readonly, self._reversible_check = snap

    def set_trust_level(self, trust: "Any") -> None:
        from argos.permissions.trust_dial import TrustLevel, to_approval_semantics
        sem = to_approval_semantics(trust)
        al_str = sem["approval_level"]
        self.set_level(ApprovalLevel(al_str))
        self._ask_readonly: bool = bool(sem.get("ask_readonly", False))
        self._reversible_check: bool = bool(sem.get("reversible_check", False))
        self._low_risk_auto: bool = bool(sem.get("low_risk_auto", False))
        self._trust_level = trust

    def set_workspace(self, workspace: str | None) -> None:
        self._workspace = workspace

    def set_reversible_lookup(self, fn: "Callable[[str], bool | None] | None") -> None:
        self._reversible_lookup = fn

    def set_session_id(self, session_id: str) -> None:
        self._session_id = session_id or ""

    def set_decision_listener(self, fn: Callable[[str, str, str], None] | None) -> None:
        self._decision_listener = fn

    def set_ask_listener(self, fn: "Callable[[str, dict[str, Any]], None] | None") -> None:
        self._ask_listener = fn

    def pending(self) -> list[_Pending]:
        return list(self._pending.values())

    async def request(self, action: str, args: dict[str, Any], *, description: str,
                      risk: RiskLevel, timeout: float = 60.0,
                      call_id: str | None = None) -> Decision:
        eval_meta = self._evaluate(action, args, risk=risk)
        if eval_meta is not None:
            if eval_meta.decision == "approve":
                self._audit(
                    action=action, args=args, decision="approved",
                    trigger=eval_meta.trigger, by="rule" if eval_meta.rule_name else "level",
                    risk=risk, secret_pattern=eval_meta.secret_pattern,
                )
                self._notify("approved", action, eval_meta.trigger)
                return Decision(kind="once", reason=eval_meta.reason or eval_meta.trigger)
            if eval_meta.decision == "deny":
                self._audit(
                    action=action, args=args, decision="denied",
                    trigger=eval_meta.trigger, by="rule",
                    risk=risk, secret_pattern=eval_meta.secret_pattern,
                )
                self._notify("denied", action, eval_meta.trigger)
                return Decision(kind="deny", reason=eval_meta.reason or eval_meta.trigger)
        if self.level is ApprovalLevel.AUTO and (eval_meta is None or eval_meta.decision != "ask"):
            self._audit(
                action=action, args=args, decision="approved",
                trigger="level:auto", by="level", risk=risk,
            )
            self._notify("approved", action, "level:auto")
            return Decision(kind="once", reason=t("approval.reason.auto"))
        if self.level is ApprovalLevel.OBSERVE and (eval_meta is None or eval_meta.decision != "ask"):
            self._audit(
                action=action, args=args, decision="denied",
                trigger="level:observe", by="level", risk=risk,
            )
            self._notify("denied", action, "level:observe")
            return Decision(kind="deny", reason=t("approval.reason.observe"))
        payload = {"action": action, "args": args}
        key = _hash_payload(payload)
        if self._session_approvals.get(key) is not None:
            self._notify("approved", action, "session:cached")
            return Decision(kind="session", reason=t("approval.reason.session_cached"))
        _caller_supplied_call_id = call_id is not None
        call_id = call_id or uuid.uuid4().hex[:12]
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[Decision] = loop.create_future()
        ask_trigger = eval_meta.trigger if eval_meta is not None else (
            f"level:{self.level.value}"
        )
        ask_payload: dict[str, Any] = {
            **payload, "description": description, "risk": risk,
            "trigger": ask_trigger,
        }
        if eval_meta is not None and eval_meta.secret_pattern:
            ask_payload["secret_pattern"] = eval_meta.secret_pattern
        self._pending[call_id] = _Pending(
            call_id=call_id, payload=ask_payload,
            created_at=time.time(), future=fut, loop=loop,
        )
        self._notify("asked", action, ask_trigger)
        if not _caller_supplied_call_id and self._ask_listener is not None:
            try:
                self._ask_listener(call_id, dict(ask_payload))
            except Exception:  # noqa: BLE001
                pass
        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            self._pending.pop(call_id, None)
            return Decision(kind="deny", reason=t("approval.reason.timeout"))

    def _evaluate(self, action: str, args: dict[str, Any],
                  risk: str = "medium") -> "DecisionMeta | None":
        try:
            from argos.permissions import evaluate, get_config
            from argos.permissions.evaluator import DecisionMeta
            cfg = self._permissions_config if self._permissions_config is not None else get_config()
            rl = self._reversible_lookup if getattr(self, "_reversible_check", False) else None
            return evaluate(
                action, args, gate_level=self.level, config=cfg,
                workspace=self._workspace,
                ask_readonly=getattr(self, "_ask_readonly", False),
                reversible_lookup=rl,
                low_risk_auto=getattr(self, "_low_risk_auto", False),
                risk=risk,
            )
        except Exception:  # noqa: BLE001
            if (
                action in {
                    "write_file", "edit_file", "run_command", "mcp_call",
                    "browser_click", "browser_type",
                }
                or action.startswith("computer_")
                or risk == "high"
            ):
                try:
                    from argos.permissions.evaluator import DecisionMeta as _DecisionMeta
                    return _DecisionMeta(
                        decision="deny",
                        trigger="evaluator:error",
                        reason="permission evaluator failed; denied fail-closed",
                    )
                except Exception:  # noqa: BLE001
                    pass
            return None

    def evaluate_sync(self, action: str, args: dict[str, Any]) -> "DecisionMeta | None":
        return self._evaluate(action, args)

    def _audit(
        self, *, action: str, args: dict[str, Any], decision: str, trigger: str,
        by: str, risk: str, secret_pattern: str | None = None,
    ) -> None:
        try:
            if self._audit_log is not None:
                log = self._audit_log
            else:
                from argos.permissions import get_audit_log
                log = get_audit_log()
            log.session_id = self._session_id or log.session_id
            args_str = json.dumps(args, ensure_ascii=False, sort_keys=True)
            log.log(
                tool=action, args=args_str, decision=decision, trigger=trigger,
                by=by, secret_pattern=secret_pattern, risk=str(risk),
            )
        except Exception:  # noqa: BLE001
            pass

    def _notify(self, decision: str, action: str, trigger: str) -> None:
        fn = self._decision_listener
        if fn is None:
            return
        try:
            fn(action, decision, trigger)
        except Exception:  # noqa: BLE001
            pass

    def respond(self, call_id: str, decision: DecisionKind) -> bool:
        p = self._pending.pop(call_id, None)
        if p is None:
            return False
        if decision in ("session", "always"):
            payload = {"action": p.payload.get("action"), "args": p.payload.get("args")}
            key = _hash_payload(payload)
            self._session_approvals[key] = _SessionApproval(
                payload_hash=key, approved_at=time.time(),
            )
        if decision == "always":
            try:
                from argos.permissions import config as _pcfg
                rule = derive_persistent_allow_rule(
                    str(p.payload.get("action", "")), p.payload.get("args") or {},
                )
                if rule is not None and _pcfg.save_allow_rule(*rule):
                    self._permissions_config = _pcfg.get_config()
            except Exception:  # noqa: BLE001
                pass
        self._settle(p, Decision(kind=decision))
        return True

    def approve(self, call_id: str, scope: Literal["once", "session"] = "once") -> bool:
        kind: DecisionKind = "session" if scope == "session" else "once"
        return self.respond(call_id, kind)

    def deny(self, call_id: str, reason: str = "") -> bool:
        p = self._pending.pop(call_id, None)
        if p is None:
            return False
        self._settle(p, Decision(kind="deny", reason=reason))
        return True

    def cancel_all(self) -> int:
        n = 0
        for p in list(self._pending.values()):
            self._settle(p, Decision(kind="deny", reason=t("approval.reason.session_cancelled")))
            n += 1
        self._pending.clear()
        return n

    @staticmethod
    def _settle(p: _Pending, decision: "Decision") -> None:
        try:
            p.loop.call_soon_threadsafe(_resolve, p.future, decision)
        except RuntimeError:
            pass  # event loop is closed


def requires_approval(description: str, risk: RiskLevel = "medium") -> Callable:

    def deco(fn: Callable) -> Callable:
        try:
            sig = inspect.signature(fn)
            param_names = list(sig.parameters.keys())
            var_positional = {n for n, p in sig.parameters.items()
                              if p.kind == inspect.Parameter.VAR_POSITIONAL}
            var_keyword = {n for n, p in sig.parameters.items()
                           if p.kind == inspect.Parameter.VAR_KEYWORD}
        except Exception:
            param_names = []
            var_positional = set()
            var_keyword = set()

        def _serialize(args: tuple, kwargs: dict[str, Any]) -> dict[str, Any]:
            out: dict[str, Any] = {}
            extra_pos: list[Any] = []
            for i, a in enumerate(args):
                if i < len(param_names) and param_names[i] in var_positional:
                    extra_pos.append(a)
                    continue
                if i < len(param_names) and param_names[i] not in var_keyword:
                    key = param_names[i]
                else:
                    extra_pos.append(a)
                    continue
                try:
                    json.dumps(a)
                    out[key] = a
                except (TypeError, ValueError):
                    out[key] = repr(a)
            if extra_pos:
                try:
                    json.dumps(extra_pos)
                    out["*args"] = extra_pos
                except (TypeError, ValueError):
                    out["*args"] = repr(extra_pos)
            extra_kw: dict[str, Any] = {}
            for k, v in kwargs.items():
                if k in var_keyword:
                    extra_kw[k] = v
                    continue
                try:
                    json.dumps(v)
                    out[k] = v
                except (TypeError, ValueError):
                    out[k] = repr(v)
            if extra_kw:
                out["**kwargs"] = extra_kw
            return out

        @functools.wraps(fn)
        async def async_wrapper(*args: Any, **kwargs: Any) -> str:
            gate = _current_gate()
            if gate is None:
                return t("approval.err.no_gate")
            tool_name = getattr(fn, "__name__", str(fn))
            serialized_args = _serialize(args, kwargs)
            decision = await gate.request(
                tool_name, serialized_args,
                description=description,
                risk=risk,
            )
            if not decision.approved:
                return t(
                    "approval.err.denied",
                    reason=decision.reason or t("approval.err.denied_no_reason"),
                )
            return await _call_original(fn, args, kwargs)

        @functools.wraps(fn)
        def sync_wrapper(*args: Any, **kwargs: Any) -> str:
            gate = _current_gate()
            if gate is None:
                return t("approval.err.no_gate")
            if asyncio.iscoroutinefunction(fn):
                return t("approval.err.async_path")
            try:
                asyncio.get_running_loop()
                in_loop = True
            except RuntimeError:
                in_loop = False
            if in_loop:
                return t("approval.err.in_loop")
            return asyncio.run(async_wrapper(*args, **kwargs))

        wrapper = async_wrapper if asyncio.iscoroutinefunction(fn) else sync_wrapper
        wrapper._approval_required = True  # type: ignore[attr-defined]
        wrapper._approval_description = description  # type: ignore[attr-defined]
        wrapper._approval_risk = risk  # type: ignore[attr-defined]
        return wrapper

    return deco


_current_gate_var: contextvars.ContextVar["ApprovalGate | None"] = contextvars.ContextVar(
    "argos_approval_gate", default=None,
)


def set_current_gate(gate: "ApprovalGate | None") -> contextvars.Token:
    return _current_gate_var.set(gate)


def reset_current_gate(token: contextvars.Token) -> None:
    _current_gate_var.reset(token)


def _current_gate() -> "ApprovalGate | None":
    return _current_gate_var.get()


async def guarded_call(
    action: str,
    args: dict[str, Any],
    run: Callable[[], Any],
    *,
    description: str,
    risk: RiskLevel,
    timeout: float = 60.0,
) -> Any:
    gate = _current_gate()
    if gate is None:
        return t("approval.err.no_gate")
    decision = await gate.request(action, args, description=description, risk=risk, timeout=timeout)
    if not decision.approved:
        return t(
            "approval.err.denied",
            reason=decision.reason or t("approval.err.denied_no_reason"),
        )
    return await run()


async def _call_original(fn: Callable, args: tuple, kwargs: dict[str, Any]) -> Any:
    res = fn(*args, **kwargs)
    if asyncio.iscoroutine(res):
        return await res
    return res
