from __future__ import annotations

import asyncio
import hashlib
import os
import re
import shlex
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, AsyncIterator, Callable

from argos.core.harness import Harness
from argos.core.honesty import (
    HONESTY_SYSTEM, StreamingContextScrubber, compose_system, format_untrusted,
)
from argos.core.plan_mode import PlanExitDecision, PlanRenderer
from argos.core.types import ModelTierName, TRIVIAL_VERIFY_BINS
from argos.protocol.events import (
    CodeAction, CodeResult, CostUpdate, Escalation, Error, Event, PhaseChange,
    MemoryRecallEvent, PlanDecisionRequest, PlanRendered, PlanUpdate,
    TokenDelta, ToolReceipt,
)
from argos.protocol.events import EventBus
from argos import hooks as _hooks
from argos.i18n import is_error_result, t as _i18n_t
from argos.hooks.payload import (
    build_post_payload, build_pre_payload, build_session_start_payload,
    build_stop_payload, extract_tool_names,
)
from argos.hooks.events import HookFired
from argos.permissions.mode import PermissionMode, parse_permission_mode

if TYPE_CHECKING:
    from argos.memory.store import ArgosStore
    from argos.sandbox.backend import SandboxBackend
    from argos.sandbox.broker import CapabilityBroker

_CODE_BLOCK = re.compile(r"```python\s*\n(.*?)```", re.DOTALL)

_PROPOSE_VERIFY = re.compile(r"propose_verify\(\s*(?:[a-zA-Z]+)?['\"](.+?)['\"]\s*\)")

_PROPOSE_DOM_VERIFY = re.compile(
    r"propose_dom_verify\s*\(([^)]*)\)",
    re.DOTALL,
)
_DOM_KW_URL = re.compile(r"""url\s*=\s*['"]([^'"]+)['"]""")
_DOM_KW_SEL = re.compile(r"""selector\s*=\s*['"]([^'"]+)['"]""")
_DOM_KW_EXP = re.compile(r"""expected_text\s*=\s*['"]([^'"]+)['"]""")
_PROPOSE_GUI_VERIFY = re.compile(r"propose_gui_verify\s*\(([^)]*)\)", re.DOTALL)
_GUI_KW_EXP = re.compile(r"""expected_text\s*=\s*['"]([^'"]+)['"]""")
_PROBE_EXPECTED_MIN = 3
_DOM_URL_ALLOWED = re.compile(r"^https?://", re.I)
_DOM_PARAM_MAX = 500

# ponytail: 2 consecutive identical (code,stdout) pairs = stuck; break + escalate.
STAGNATION_LIMIT = 2


_UPDATE_PLAN = re.compile(r"update_plan\(", re.DOTALL)

_PROPOSE_WORKFLOW = re.compile(r"propose_workflow\(", re.DOTALL)

_FIXED_SPAWN_NAMESPACE: dict[str, Any] = {}

_FEEDBACK_MAX_CHARS = 10000
_MUTATION_TOOL_NAMES = frozenset({"write_file", "edit_file"})


def _tool_names_indicate_mutation(tool_names: list[str] | tuple[str, ...] | set[str]) -> bool:
    return any(name in _MUTATION_TOOL_NAMES for name in tool_names)


def _code_mentions_file_mutation(code: str) -> bool:
    return "write_file(" in code or "edit_file(" in code


def _clamp_feedback(out: str, limit: int = _FEEDBACK_MAX_CHARS) -> str:
    if len(out) <= limit:
        return out
    head = out[: limit * 2 // 3]
    tail = out[-(limit // 3):]
    elided = len(out) - len(head) - len(tail)
    return f"{head}\n…[{elided} chars elided]…\n{tail}"


def extract_code_block(text: str) -> str | None:
    m = _CODE_BLOCK.search(text)
    if not m:
        return None
    return m.group(1).strip()


def _context_used_from_usage(
    usage: dict[str, Any],
    *,
    system: str = "",
    system_dynamic: str | None = None,
    messages: list[dict] | None = None,
) -> int:
    total = usage.get("context_total")
    if total is not None:
        return int(total)
    used = (int(usage.get("input_tokens") or 0)
            + int(usage.get("cache_read") or 0)
            + int(usage.get("cache_creation") or 0))
    if used:
        return used
    if not (system or system_dynamic or messages):
        return 0
    chunks = [system, system_dynamic or ""]
    for msg in messages or []:
        content = msg.get("content", "")
        if isinstance(content, list):
            content = "\n".join(str(part.get("text", part)) if isinstance(part, dict) else str(part)
                                for part in content)
        chunks.append(str(content))
    from argos.context.tokens import token_estimate
    estimate, _ = token_estimate("\n".join(chunks))
    return estimate


_LAZY_CLAIM_ZH: tuple[str, ...] = (
    "我来", "我先", "我会", "我将", "我去", "让我", "马上", "稍等", "正在", "接下来",
    "完成了", "已完成", "已经完成", "做完了", "修复了", "改好了", "搞定", "处理好了",
    "我查一下", "我找一下", "我抓一下", "我读一下", "我看一下", "我重新",
    "我需要",
    "我们查一下", "我们找一下", "我们抓一下", "我们读一下", "我们看一下",
    "定位到仓库", "读 README",
)
_LAZY_CLAIM_EN: tuple[str, ...] = (
    "i'll", "i will", "let me", "i'm going to", "i am going to", "i'll go",
    "i've ", "i have ", "now i ", "fixed", "done.", "completed", "finished",
)


def _looks_like_lazy_claim(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return True
    low = t.lower()
    return (any(kw in t for kw in _LAZY_CLAIM_ZH)
            or any(kw in low for kw in _LAZY_CLAIM_EN))


def _has_unfinished_todos(todos: list[dict]) -> bool:
    return any(t.get("status") != "completed" for t in todos)


_CONFIRMATION_BEFORE_ACTION = re.compile(
    r"(允许|准许|许可|批准|同意|确认|点头).{0,80}(吗|么|\?|？)"
    r"|((等|待).{0,20}(你|用户).{0,20}(确认|批准|点头|同意))"
    r"|((确认|批准|点头|同意).{0,20}(后|了|再))"
    r"|\b(may i|can i|should i|shall i|allow me|with your permission|"
    r"once you confirm|if you approve|wait for your approval)\b",
    re.IGNORECASE | re.DOTALL,
)


def _asks_user_confirmation_before_action(text: str) -> bool:
    """Assistant asked for user confirmation before the first executable block."""
    code_at = text.find("```python")
    if code_at < 0:
        return False
    return bool(_CONFIRMATION_BEFORE_ACTION.search(text[:code_at]))


def extract_plan_todos(text: str) -> list[dict] | None:
    import ast
    last: list[dict] | None = None
    for m in _UPDATE_PLAN.finditer(text):
        i = m.end()
        depth = 1
        in_str: str | None = None
        esc = False
        j = i
        limit = min(len(text), i + 65536)
        while j < limit and depth > 0:
            ch = text[j]
            if in_str is not None:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == in_str:
                    in_str = None
            elif ch in ("'", '"'):
                in_str = ch
            elif ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            j += 1
        if depth != 0:
            continue
        arg = text[i:j - 1].strip()
        try:
            val = ast.literal_eval(arg)
        except (ValueError, SyntaxError):
            continue
        if isinstance(val, list):
            last = [d for d in val if isinstance(d, dict)]
    return last


def extract_workflow_spec(text: str) -> dict | None:
    import ast
    last: dict | None = None
    for m in _PROPOSE_WORKFLOW.finditer(text):
        i = m.end()
        depth = 1
        in_str: str | None = None
        esc = False
        j = i
        limit = min(len(text), i + 65536)
        while j < limit and depth > 0:
            ch = text[j]
            if in_str is not None:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == in_str:
                    in_str = None
            elif ch in ("'", '"'):
                in_str = ch
            elif ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            j += 1
        if depth != 0:
            continue
        arg = text[i:j - 1].strip()
        try:
            val = ast.literal_eval(arg)
        except (ValueError, SyntaxError):
            continue
        if isinstance(val, dict):
            last = val
    return last


class _CollectingBus(EventBus):

    def __init__(self) -> None:
        super().__init__()
        self._collected: list[Event] = []

    async def emit(self, ev: Event) -> None:  # type: ignore[override]
        self._collected.append(ev)

    def drain(self) -> list[Event]:
        out = self._collected
        self._collected = []
        return out


def _git_status_snapshot(workspace: Path) -> str:
    import subprocess
    try:
        out = subprocess.run(
            ["git", "-C", str(workspace), "status", "--short", "--branch"],
            capture_output=True, text=True, timeout=5,
        )
    except Exception:  # noqa: BLE001
        return ""
    if out.returncode != 0:
        return ""
    lines = (out.stdout or "").splitlines()
    if len(lines) > 40:
        lines = lines[:40] + [f"… (+{len(lines) - 40} more changed files)"]
    return "\n".join(lines).strip()


def _env_context(workspace: Path) -> str:
    import platform
    from datetime import date
    block = (
        "\n\n<environment>\n"
        f"- Working directory (relative paths resolve against it): {workspace}\n"
        f"- OS: {platform.system()} {platform.machine()}\n"
        f"- Today: {date.today().isoformat()}\n"
        "These are known facts — don't probe them at runtime (os.getcwd / pathlib.Path.cwd / pwd).\n"
        "</environment>"
    )
    gs = _git_status_snapshot(workspace)
    if gs:
        block += (
            "\n\n<git_status>\n"
            f"{gs}\n"
            "Snapshot at run start — don't re-run `git status` just to learn this.\n"
            "</git_status>"
        )
    return block


def _governance_context(permission_mode: PermissionMode | str) -> str:
    from argos import config as _config
    mode = parse_permission_mode(permission_mode)
    if _config.sandbox_enabled():
        cage = (
            "ON — an OS sandbox cages side effects this session "
            "(the CodeAct child process has no direct network and writes are confined "
            "to the workspace). The host-side broker tools such as web_search/web_extract "
            "can still use governed network access; don't report sandbox/network "
            "failure just because inline code timed out."
        )
    else:
        cage = (
            "OFF — side effects are NOT OS-contained this session; the capability broker, "
            "approval gate, egress policy and AST limits govern them, and the verify gate "
            "still checks your work. Don't assume a kernel cage will catch a mistake."
        )
    return (
        "\n\n<runtime>\n"
        f"- OS-level sandbox: {cage}\n"
        f"- Permission mode: {mode.label}\n"
        "</runtime>"
    )


@dataclass(frozen=True, slots=True)
class LoopConfig:
    model_tier: ModelTierName = "default"
    verify_cmd: str | None = None
    max_rounds: int = 3
    max_steps: int = 40
    compaction: bool = True
    recall: bool = True
    permission_mode: PermissionMode = PermissionMode.SMART_APPROVAL
    compact_threshold: float = 0.8
    prune_aggressiveness: float = 0.5
    # Task 1.2: hard budget ceilings — None = no limit (pure-additive, behavior identical when unset).
    max_tokens_in: int | None = None    # cumulative input-token ceiling (works even for un-priced models)
    max_cost_usd: float | None = None


class AgentLoop:

    def __init__(
        self,
        *,
        store: "ArgosStore",
        bus: "EventBus",
        sandbox: "SandboxBackend",
        broker: "CapabilityBroker | None",
        model: Any,
        verifier: Any,
        config: LoopConfig,
        workspace: Path | None = None,
        verify_dir: Path | None = None,
        project_id: str | None = None,
        allow_workflow: bool = True,
        read_only: bool = False,
        tool_allowlist: "list[str] | None" = None,
        workflow_engine_factory: Callable[[], object] | None = None,
        router: Any = None,
        mcp_manager: Any = None,
        capability_hints: dict[str, str] | None = None,
        dom_prober: Any = None,
        gui_prober: Any = None,
        manage_runtime_context: bool = False,
        project_mode: bool = False,
        ledger_store: "Any | None" = None,
    ) -> None:
        self._store = store
        self._bus = bus
        self._sandbox = sandbox
        self._broker = broker
        self._model = model
        self._project_id = project_id
        self._verifier = verifier
        self._cfg = config
        from argos import config as _argos_config
        _argos_dir = _argos_config.config_dir()
        self._workspace = workspace or _argos_dir / "workspace"
        self._verify_dir = verify_dir or _argos_dir / "verify"
        self._allow_workflow = allow_workflow
        self._read_only = read_only
        self._tool_allowlist = tool_allowlist
        self._mcp_manager = mcp_manager
        self._workflow_engine_factory = workflow_engine_factory
        self._capability_hints: dict[str, str] = capability_hints or {}
        self._dom_prober = dom_prober
        self._pending_l3_strategy: "Any | None" = None
        self._pending_dom_expected_text: str = ""
        self._gui_prober = gui_prober
        self._pending_gui_expected_text: str = ""
        self._manage_runtime_context = manage_runtime_context
        self._project_mode = project_mode
        # ponytail: None-check keeps daemon path 100% unchanged; inline path just adds to it
        self._ledger_store = ledger_store
        self._ledger_seq = 0
        self._actions = 0
        self._fail_count = 0
        self._started = 0.0
        self._verify_cmd: str | None = config.verify_cmd
        self._verify_rejected: str | None = None
        self._todos: list[dict] = []
        self._tok_in = 0
        self._tok_out = 0
        self._cache_read = 0
        self._hbus = _CollectingBus()
        self._harness = Harness(
            verifier=verifier,
            signer=self._broker.signer if self._broker is not None else _ReceiptSigner(key=b"_no_broker_"),
            bus=self._hbus,
            max_rounds=config.max_rounds,
        )
        self.mode: str = "act"
        self._plan_decision_event: asyncio.Event = asyncio.Event()
        self._plan_decision: PlanExitDecision | None = None
        self._plan_call_registry: dict[str, asyncio.Event] = {}
        self._router = router
        self._current_tier: str = config.model_tier
        from argos.context.threshold import LastCompactedAt as _LCA
        self._last_compact_used: _LCA | None = None
        self._messages_override: list[dict] | None = None
        self._compacted: bool = False
        self._reverified_since_compact: bool = True
        self._current_goal: str = ""
        self._user_goal: str = ""

    @property
    def bus(self) -> "EventBus":
        return self._bus

    @property
    def store(self) -> "ArgosStore":
        return self._store

    @property
    def sandbox(self) -> "SandboxBackend":
        return self._sandbox

    @property
    def broker(self) -> "CapabilityBroker | None":
        return self._broker

    def _reset_run_state(self) -> None:
        self._actions = 0
        self._fail_count = 0
        self._verify_cmd = self._cfg.verify_cmd
        self._verify_rejected = None
        self._todos = []
        self._tok_in = 0
        self._tok_out = 0
        self._cache_read = 0
        self._started = time.time()
        self._plan_decision = None
        self._plan_decision_event = asyncio.Event()
        self._pending_l3_strategy = None
        self._pending_dom_expected_text = ""
        self._pending_gui_expected_text = ""

    def _on_propose_verify(self, cmd: str) -> bool:
        cmd = (cmd or "").strip()
        if not cmd:
            return False
        if "{" in cmd and "}" in cmd:
            self._verify_rejected = cmd
            self._verify_rejected_fstring = True
            return False
        if (os.environ.get("ARGOS_BRIDGE_VERIFY_LOCK", "1") != "0"
                and os.environ.get("ARGSOS_BRIDGE_VERIFY_LOCK", "1") != "0")\
                and self._cfg.verify_cmd is not None and self._cfg.verify_cmd.strip():
            self._verify_rejected = cmd
            return False
        try:
            bin_name = Path(shlex.split(cmd)[0]).name
        except (ValueError, IndexError):
            return False
        if bin_name in TRIVIAL_VERIFY_BINS:
            self._verify_rejected = cmd
            return False
        self._verify_cmd = cmd
        return True

    def _on_propose_dom_verify(self, raw_args: str) -> bool:
        if self._verify_cmd is not None and self._verify_cmd.strip():
            return False
        if self._dom_prober is None:
            return False

        url_m = _DOM_KW_URL.search(raw_args)
        sel_m = _DOM_KW_SEL.search(raw_args)
        exp_m = _DOM_KW_EXP.search(raw_args)

        url = url_m.group(1).strip() if url_m else ""
        selector = sel_m.group(1).strip() if sel_m else "body"
        expected_text = exp_m.group(1).strip() if exp_m else ""
        if expected_text and len(expected_text) < _PROBE_EXPECTED_MIN:
            expected_text = ""

        if not url or not _DOM_URL_ALLOWED.match(url):
            return False
        if len(selector) > _DOM_PARAM_MAX or len(expected_text) > _DOM_PARAM_MAX:
            return False

        try:
            from argos.verify.strategy import VerifyStrategy
            hints: dict[str, str] = {
                "dom_url": url,
                "dom_selector": selector,
            }
            if expected_text:
                hints["dom_expected_text"] = expected_text
            from argos.verify.strategy import _l3_dom_assert
            strategy = _l3_dom_assert(hints)
            self._pending_l3_strategy = strategy
            self._pending_dom_expected_text = expected_text
            return True
        except Exception:  # noqa: BLE001
            return False

    def _on_propose_gui_verify(self, raw_args: str) -> bool:
        if self._verify_cmd is not None and self._verify_cmd.strip():
            return False
        if self._gui_prober is None:
            return False
        exp_m = _GUI_KW_EXP.search(raw_args)
        expected_text = exp_m.group(1).strip() if exp_m else ""
        if (not expected_text or len(expected_text) < _PROBE_EXPECTED_MIN
                or len(expected_text) > _DOM_PARAM_MAX):
            return False
        self._pending_gui_expected_text = expected_text
        return True

    def respond_plan_decision(
        self, call_id: str, action: str, feedback: str | None = None,
    ) -> bool:
        if call_id not in self._plan_call_registry:
            return False
        from argos.core.plan_mode import ExitPlanMode
        result = ExitPlanMode(self, action, feedback)
        if is_error_result(result):
            return False
        self._plan_call_registry.pop(call_id, None)
        return True

    @staticmethod
    def _todos_summary(todos: list[dict]) -> str:
        glyph = {"completed": "[x]", "in_progress": "[~]", "pending": "[ ]"}
        done = sum(1 for t in todos if t.get("status") == "completed")
        lines = [_i18n_t("loop.todos.header", done=done, total=len(todos))]
        for t in todos:
            mark = glyph.get(t.get("status", "pending"), "[ ]")
            lines.append(f"{mark} {t.get('content', '')}")
        return "\n".join(lines)

    def _pick_strategy_cmd(self, goal: str) -> str | None:
        try:
            from argos.verify.strategy import generate, probe_workspace, WorkspaceFacts
            from argos.tools import ALLOWED_CMDS

            ws = self._workspace
            facts = probe_workspace(ws) if ws and ws.is_dir() else WorkspaceFacts()

            strategies = generate(
                goal,
                workspace_facts=facts,
                capability_hints=self._capability_hints or {},
            )

            for s in strategies:
                if s.level == "L5":
                    return None
                if s.level == "L3" and s.kind == "dom_assert":
                    if self._dom_prober is not None:
                        self._pending_l3_strategy = s
                        return None
                    continue
                if s.cmd is None:
                    continue
                try:
                    cmd_parts = shlex.split(s.cmd)
                except ValueError:
                    continue
                if not cmd_parts:
                    continue
                bin_name = Path(cmd_parts[0]).name
                if bin_name in TRIVIAL_VERIFY_BINS:
                    continue
                if bin_name not in ALLOWED_CMDS:
                    continue
                return s.cmd

            return None
        except Exception:  # noqa: BLE001
            return None

    async def _run_dom_probe_verdict(self, strategy: Any, *, attempt: int) -> "Verdict":
        import asyncio as _asyncio
        from argos.core.types import Verdict
        from argos.protocol.events import VerifyVerdict as _VV

        target = strategy.target or ""
        if "#" in target:
            url_part, selector = target.split("#", 1)
        else:
            url_part, selector = target, "body"
        url = url_part if url_part.startswith("http") else None

        expected_text: str | None = (
            self._pending_dom_expected_text
            or self._capability_hints.get("dom_expected_text")
            or None
        )

        try:
            prober = self._dom_prober
            result = await _asyncio.to_thread(
                prober.probe, url, selector, expected_text=expected_text
            )
        except Exception as exc:  # noqa: BLE001 — fail-closed
            result_type = type(exc).__name__
            result_err = _i18n_t("loop.dom_probe.thread_error", result_type=result_type, exc=exc)
            class _R:  # noqa: N801
                found = False
                text_excerpt = ""
                error = result_err
            result = _R()  # type: ignore[assignment]

        rationale = strategy.rationale_human
        label = f"dom_assert:{selector}"

        if result.error:
            detail = _i18n_t("loop.dom_probe.error_detail", rationale=rationale, error=result.error)
            verdict = Verdict(
                status="unverifiable",
                detail=detail,
                verify_cmd=label,
                attempts=attempt,
            )
        elif result.found:
            excerpt = result.text_excerpt[:200] if result.text_excerpt else _i18n_t("loop.dom_probe.no_excerpt")
            detail = _i18n_t("loop.dom_probe.found_detail", rationale=rationale, selector=selector, excerpt=excerpt)
            verdict = Verdict.passed(detail=detail, verify_cmd=label, attempts=attempt)
        else:
            detail = _i18n_t("loop.dom_probe.not_found_detail", rationale=rationale, selector=selector)
            verdict = Verdict.failed(detail=detail, verify_cmd=label, attempts=attempt)

        await self._harness.bus.emit(_VV(verdict=verdict))
        return verdict

    async def _run_gui_probe_verdict(self, expected_text: str, *, attempt: int) -> "Verdict":
        import asyncio as _asyncio
        from argos.core.types import Verdict
        from argos.protocol.events import VerifyVerdict as _VV

        label = f"gui_assert:{expected_text[:40]}"
        try:
            result = await _asyncio.to_thread(self._gui_prober.probe, expected_text)
        except Exception as exc:  # noqa: BLE001 — fail-closed
            class _R:  # noqa: N801
                found = False
                text_excerpt = ""
                error = _i18n_t("loop.gui_probe.thread_error", exc_type=type(exc).__name__, exc=exc)
            result = _R()  # type: ignore[assignment]

        if result.error:
            verdict = Verdict(
                status="unverifiable",
                detail=_i18n_t("loop.gui_probe.unverifiable_detail", error=result.error),
                verify_cmd=label, attempts=attempt,
            )
        elif result.found:
            excerpt = result.text_excerpt[:200] if result.text_excerpt else _i18n_t("loop.gui_probe.no_excerpt")
            verdict = Verdict.passed(
                detail=_i18n_t("loop.gui_probe.found_detail", expected_text=expected_text, excerpt=excerpt),
                verify_cmd=label, attempts=attempt,
            )
        else:
            verdict = Verdict.failed(
                detail=_i18n_t("loop.gui_probe.not_found_detail", expected_text=expected_text),
                verify_cmd=label, attempts=attempt,
            )
        await self._harness.bus.emit(_VV(verdict=verdict))
        return verdict

    async def run(self, goal: str, session_id: str,  # noqa: E501
                  attachments: "list | None" = None) -> AsyncIterator["Event"]:
        await self._resolve_vision_capable(attachments)
        self._reset_run_state()
        if self._manage_runtime_context:
            from argos import runtime as _rt
            _rt.set_context(_rt.RunContext(
                workspace=self._workspace, verify_dir=self._verify_dir,
                project_mode=self._project_mode,
            ))
        self._last_snapshot = None
        try:
            from argos.core.snapshot import RunSnapshot, SNAPSHOT_ROOT
            tar_path = SNAPSHOT_ROOT / f"{session_id}-{int(time.time() * 1000)}.tar"
            self._last_snapshot = await asyncio.to_thread(
                RunSnapshot.take, self._workspace, tar_path,
            )
        except Exception:  # noqa: BLE001
            pass
        spawn_namespace = dict(_FIXED_SPAWN_NAMESPACE)
        assert "__authorized_imports__" not in spawn_namespace, (
            _i18n_t("core2.loop.m8_assert")
        )
        _spawn_kwargs: dict = dict(
            workspace=self._workspace, namespace=spawn_namespace,
            allow_workflow=self._allow_workflow, read_only=self._read_only,
        )
        if self._tool_allowlist is not None:
            _spawn_kwargs["tool_allowlist"] = self._tool_allowlist
        self._sandbox.spawn(**_spawn_kwargs)
        try:
            from argos import runtime
            runtime.guard_project_tests()
        except Exception:  # noqa: BLE001
            pass
        if self._broker is not None and hasattr(self._broker, "set_host_loop"):
            try:
                self._broker.set_host_loop(asyncio.get_running_loop())
            except RuntimeError:
                pass
        try:
            async for ev in self._drive(goal, session_id, attachments=attachments):
                self._store.append_event(session_id, ev)
                # ponytail: fail-soft; ledger loss must not abort the run
                if self._ledger_store is not None:
                    self._inline_maybe_append_ledger(ev, session_id)
                yield ev
        except Exception as e:  # noqa: BLE001
            chain: list[str] = []
            cur: BaseException | None = e
            while cur is not None and len(chain) < 4:
                chain.append(f"{type(cur).__name__}: {cur}")
                cur = cur.__cause__ or cur.__context__
            import httpx as _httpx
            _raw_msg = str(e)
            _friendly: str | None = None
            _status = getattr(getattr(e, "response", None), "status_code", None)
            if _status == 429 or (
                "429" in _raw_msg or "too many requests" in _raw_msg.lower()
                or "rate_limit" in _raw_msg.lower()
            ):
                _friendly = _i18n_t("loop.error.rate_limit", raw_msg=_raw_msg[:120])
            elif isinstance(e, _httpx.TransportError) or isinstance(
                e, (_httpx.ConnectError, _httpx.ConnectTimeout, _httpx.ReadTimeout)
            ):
                _friendly = _i18n_t("loop.error.network", raw_msg=_raw_msg[:200])
            msg = _friendly if _friendly is not None else _raw_msg
            err = Error(message=msg, chain=chain)
            self._store.append_event(session_id, err)
            yield err
        finally:
            if self._broker is not None and hasattr(self._broker, "set_host_loop"):
                self._broker.set_host_loop(None)
                gate = getattr(self._broker, "gate", None)
                if gate is not None and hasattr(gate, "cancel_all"):
                    try:
                        gate.cancel_all()
                    except Exception:  # noqa: BLE001
                        pass
            self._sandbox.close()

    async def _enter_phase(self, phase: str) -> AsyncIterator["Event"]:
        await self._harness.enter_phase(phase, actions=self._actions, max_steps=self._cfg.max_steps)  # type: ignore[arg-type]
        for ev in self._hbus.drain():
            yield ev

    async def _resolve_vision_capable(self, attachments: "list | None") -> None:
        self._vision_capable = None
        if not (attachments or os.environ.get("ARGOS_COMPUTER_USE")):
            return
        tier = getattr(getattr(self, "_model", None), "tier", None)
        if tier is None:
            return
        if attachments:
            if getattr(tier, "multimodal", None) is False:
                raise ValueError(
                    _i18n_t("loop.vision.unsupported",
                            model_name=getattr(tier, "model", "current model"))
                )
            self._vision_capable = True
            return
        from argos.core.vision_capability import (
            resolve_vision_capability, VisionCapabilityCache,
        )
        self._vision_capable = await resolve_vision_capability(
            tier, self._model, VisionCapabilityCache()
        )
        if attachments and not self._vision_capable:
            raise ValueError(
                _i18n_t("loop.vision.unsupported",
                        model_name=getattr(tier, "model", "current model"))
            )

    def _maybe_attach_screenshot(self, fb_msg: dict, shot: "tuple | None") -> None:
        if shot is None:
            return
        if not getattr(self, "_vision_capable", False):
            return
        try:
            from argos.input.attachments import load_from_path
            path, size = shot
            fb_msg["attachments"] = [load_from_path(path)]
            if size and tuple(size) != (0, 0):
                fb_msg["content"] = (
                    f"{fb_msg['content']}"
                    + _i18n_t("loop.screenshot.pixel_note", w=size[0], h=size[1])
                )
            try:
                Path(path).unlink(missing_ok=True)
            except OSError:
                pass
        except Exception as exc:  # noqa: BLE001
            __import__("logging").getLogger(__name__).debug("screenshot attach skipped: %s", exc)

    def _tool_signatures_block(self) -> str:
        return (
            "\n\n<tool_signatures>\n"
            "- read_file(path, offset: int = 0, limit: int | None = None) "
            "— offset = start line (0-based), limit = how many lines (None = to EOF)\n"
            "- edit_file(path, old, new, all_occurrences: bool = False) "
            "— all_occurrences=False (default) = unique match; True = replace all (max 1000)\n"
            "- slash /undo reverts this run's file changes; /retry resends your last "
            "message (press Esc first if busy).\n"
            "</tool_signatures>"
        )

    def _inline_maybe_append_ledger(self, ev: "Any", run_id: str) -> None:
        import time as _time
        import os as _os
        from argos.ledger.builder import build_entry
        from argos.ledger.entry import LedgerEntry
        try:
            ev_kind = getattr(ev, "kind", None)

            if ev_kind == "tool_receipt":
                receipt = getattr(ev, "receipt", None)
                if receipt is None:
                    return
                self._ledger_seq += 1
                entry = build_entry(
                    receipt=receipt,
                    run_id=run_id,
                    seq=self._ledger_seq,
                    args={},
                    undo_token=None,
                )
                self._ledger_store.append(entry)

            elif ev_kind == "file_diff":
                path_str = str(getattr(ev, "path", "") or "")
                if not path_str:
                    return
                added = int(getattr(ev, "added", 0))
                removed = int(getattr(ev, "removed", 0))
                basename = _os.path.basename(path_str) or path_str
                # Reuse same i18n keys as daemon/worker.py:634-638 — inline/daemon parity
                if added or removed:
                    summary = _i18n_t("daemon.srv.ledger_modified_diff",
                                      basename=basename, added=added, removed=removed)
                else:
                    summary = _i18n_t("daemon.srv.ledger_modified", basename=basename)
                self._ledger_seq += 1
                entry = LedgerEntry(
                    ts=_time.time(),
                    run_id=run_id,
                    seq=self._ledger_seq,
                    action="file_diff",
                    summary_human=summary,
                    risk="low",
                    reversible="unknown",   # type: ignore[arg-type]
                    undo_token=None,
                    receipt_sig="",
                    undo_state="impossible",   # type: ignore[arg-type]
                )
                self._ledger_store.append(entry)
        except Exception as e:  # noqa: BLE001
            import logging as _log
            _log.getLogger("argos.ledger.inline").warning(
                "inline ledger append failed for %s: %s", run_id, e
            )

    async def _maybe_proactive_compact(self, session_id: str, step: int) -> AsyncIterator["Event"]:
        from argos.context.threshold import (
            _should_compact, LastCompactedAt as _LCA, safe_compact_threshold,
        )
        threshold = safe_compact_threshold(float(getattr(self._cfg, "compact_threshold", 0.8) or 0.0))
        if threshold <= 0:
            return
        usage = getattr(self._model, "last_usage", None) or {}
        used = (int(usage.get("input_tokens") or 0)
                + int(usage.get("cache_read") or 0)
                + int(usage.get("cache_creation") or 0))
        # window:model.tier.context_window;fallback 200_000
        try:
            window = int(self._model.tier.context_window or 0) or 200_000
        except Exception:  # noqa: BLE001
            window = 200_000
        if not _should_compact(
            used=used, window=window, threshold=threshold,
            phase="act",
            compaction_enabled=bool(getattr(self._cfg, "compaction", True)),
            already_compacted_at=self._last_compact_used,
            last_verdict_fail_count=self._fail_count,
        ):
            return
        if not hasattr(self._store, "compact_messages"):
            return
        pre_used = used
        try:
            self._store.compact_messages(session_id, keep_recent=5)  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            return
        new_messages = self._store.get_messages(session_id) if hasattr(self._store, "get_messages") else []  # type: ignore[attr-defined]
        new_messages = self._anchor_core_messages(new_messages, self._current_goal)
        new_total = sum(max(1, len(m.get("content") or "") // 4) for m in new_messages)
        self._messages_override = new_messages
        self._last_compact_used = _LCA(used=pre_used)
        self._compacted = True
        self._reverified_since_compact = False
        from argos.protocol.events import CompactedEvent
        yield CompactedEvent(
            before=pre_used, after=new_total,
            reduction_pct=max(0.0, (pre_used - new_total) / max(1, pre_used)),
            triggered_by="proactive", session_id=session_id,
        )

    def _anchor_core_messages(self, messages: list[dict], goal: str) -> list[dict]:
        if not goal:
            return messages
        try:
            if any((m.get("content") or "") == goal for m in messages):
                return messages
            return [{"role": "user", "content": goal}] + list(messages)
        except Exception:  # noqa: BLE001
            return messages

    def _maybe_prune(self, messages: list[dict], session_id: str = "") -> tuple[list[dict], "PrunedEvent | None"]:
        aggressiveness = float(getattr(self._cfg, "prune_aggressiveness", 0.5) or 0.0)
        if aggressiveness <= 0 or not messages:
            return messages, None
        try:
            from argos.context.prune import CoreKeep, prune_messages
            core = CoreKeep(recent_turns=6, verify_cmd=self._verify_cmd)
            result = prune_messages(messages, core=core, aggressiveness=aggressiveness)
        except Exception:  # noqa: BLE001
            return messages, None
        if result.removed <= 0:
            return messages, None
        from argos.context.tokens import token_estimate
        before = sum(token_estimate(m.get("content") or "")[0] for m in messages)
        after = before - result.removed_tokens
        from argos.protocol.events import PrunedEvent
        ev = PrunedEvent(
            before=before, after=after, removed=result.removed,
            reduction_pct=max(0.0, result.removed_tokens / max(1, before)),
            aggressiveness=aggressiveness, session_id=session_id,
        )
        return result.messages, ev

    def _build_system(self, goal: str) -> str:
        stable, dynamic = self._build_system_pair(goal)
        if not dynamic:
            return stable
        return compose_system(stable, untrusted=dynamic)

    def _build_system_pair(
        self, goal: str, *, _prefetched_memory_lines: list[str] | None = None,
    ) -> tuple[str, str]:
        safe = (
            HONESTY_SYSTEM
            + _env_context(self._workspace)
            + _governance_context(self._cfg.permission_mode)
        )
        try:
            from argos.memory import auto as _mem_auto
            _mem_block = _mem_auto._memory_context_block(
                workspace=self._workspace,
                project_id=self._project_id or _mem_auto.project_id_for(self._workspace),
                session_id=None,
            )
            if _mem_block:
                safe = safe + "\n\n" + _mem_block
        except Exception:  # noqa: BLE001
            pass
        safe = safe + self._tool_signatures_block()
        try:
            from argos import contracts
            _dom, contract_text = contracts.contract_for(goal)
            if contract_text:
                safe = safe + contract_text
        except Exception:  # noqa: BLE001
            pass

        try:
            if self._mcp_manager is not None:
                _mcp_mgr = self._mcp_manager
            else:
                from argos import mcp_native
                _mcp_mgr = mcp_native.get_manager()
            mcp_summary = _mcp_mgr.tools_summary()
            if mcp_summary:
                safe = safe + "\n\n" + mcp_summary
        except Exception:  # noqa: BLE001
            pass

        import os as _os_cu
        if _os_cu.environ.get("ARGOS_COMPUTER_USE"):
            from argos.core.honesty import COMPUTER_USE_PROMPT
            safe = safe + "\n\n" + COMPUTER_USE_PROMPT
        # ponytail: workflow toggle is deferred (no client-side on/off switch
        # yet); control via ARGOS_WORKFLOWS env var only for now.
        if _os_cu.environ.get("ARGOS_WORKFLOWS") == "1":
            from argos.core.honesty import WORKFLOW_PROMPT
            safe = safe + "\n\n" + WORKFLOW_PROMPT
        try:
            from argos.lsp import config as _lsp_config
            _lsp_path = _lsp_config.LSP_CONFIG_PATH or _lsp_config._default_config_path()
            if _lsp_path.exists() and _lsp_config.load(_lsp_path).servers:
                from argos.core.honesty import LSP_TOOLS
                safe = safe + "\n\n" + LSP_TOOLS
        except Exception:  # noqa: BLE001
            pass

        from argos import config as _cfg_wm
        _weak_reminder = (
            "\n\n<final_reminder>\n"
            "Implement completely. Never leave a function body as a comment, a truncation "
            "like \"# ...\" or \"// ...\", a TODO, or a stub where working code was asked "
            "for. If you wrote a file, run it through run_command before you call it done.\n"
            "</final_reminder>"
        ) if _cfg_wm.weak_model() else ""
        safe = safe + _weak_reminder

        if not self._cfg.recall:
            return (safe, "")

        skill_bodies: list[str] = []
        try:
            from argos import skills as _skills
            skill_bodies = [
                _i18n_t("core2.loop.skill_header", name=s.name, description=s.description, body=s.body.strip())
                for s in _skills.recall(goal)
            ]
        except Exception:  # noqa: BLE001
            skill_bodies = []

        memory_lines: list[str] = []
        if _prefetched_memory_lines is not None:
            memory_lines = _prefetched_memory_lines
        elif hasattr(self._store, "recall"):
            try:
                hits = self._store.recall(goal)  # type: ignore[attr-defined]
                memory_lines = [
                    f"- {rec.goal} → {rec.verdict or '?'}（{reason}）" for rec, reason in hits
                ]
            except Exception:  # noqa: BLE001
                memory_lines = []

        dynamic = format_untrusted(skill_bodies=skill_bodies, memory_lines=memory_lines)
        return (safe, dynamic)

    async def _drive(self, goal: str, session_id: str,
                     attachments: "list | None" = None) -> AsyncIterator["Event"]:
        if hasattr(self._store, "ensure_session"):
            self._store.ensure_session(  # type: ignore[attr-defined]
                session_id, title=goal[:80], model=self._cfg.model_tier, system_snapshot="",
            )
        from argos import config as _config
        try:
            tier_name = _config.active_tier().name
        except Exception:  # noqa: BLE001
            tier_name = "default"
        ss_payload = build_session_start_payload(
            session_id=session_id, cwd=str(self._workspace), model_tier=tier_name,
        )
        ss_result = await _hooks.fire("SessionStart", ss_payload,
                                      cwd=self._workspace, session_id=session_id)
        for h in ss_result.per_hook:
            yield HookFired(event_name="SessionStart", command=h.command,
                            success=h.success, returncode=h.returncode,
                            elapsed_ms=h.elapsed_ms, timed_out=h.timed_out,
                            not_found=h.not_found, stop_reason=h.stop_reason,
                            error=h.error)
        # ── plan ──
        async for ev in self._enter_phase("plan"):
            yield ev
        if hasattr(self._store, "get_messages"):
            messages: list[dict] = self._store.get_messages(session_id)
        else:
            messages = []
        _user_msg: dict = {"role": "user", "content": goal}
        if attachments:
            _user_msg["attachments"] = list(attachments)
        messages.append(_user_msg)
        self._store.append_message(session_id, role="user", content=goal)
        self._current_goal = goal
        self._user_goal = goal
        _prefetched_mem: list[str] = []
        if self._cfg.recall and hasattr(self._store, "recall"):
            try:
                if hasattr(self._store, "arecall"):
                    _mem_raw = await self._store.arecall(goal)  # type: ignore[attr-defined]
                else:
                    _mem_raw = await asyncio.to_thread(
                        self._store.recall, goal,  # type: ignore[attr-defined]
                    )
                _prefetched_mem = [
                    f"- {rec.goal} → {rec.verdict or '?'}（{reason}）"
                    for rec, reason in _mem_raw
                ]
            except Exception:  # noqa: BLE001
                _prefetched_mem = []
        system_stable, system_dynamic = self._build_system_pair(
            goal, _prefetched_memory_lines=_prefetched_mem,
        )
        system = system_stable if not system_dynamic else compose_system(
            system_stable, untrusted=system_dynamic,
        )

        _recall_hits: list[str] = [line.lstrip("- ") for line in _prefetched_mem]
        yield MemoryRecallEvent(hits=_recall_hits)

        if self.mode == "plan":
            async for ev in self._run_plan_phase_loop(goal, messages, system):
                yield ev

        async for ev in self._enter_phase("act"):
            yield ev
        step = 0
        report_note = ""
        last_verdict: Any = None
        escalated = False
        noaction_nudged = False
        made_changes = False
        conversational_done = False
        verify_nudged = False
        compactions = 0
        last_fp: str | None = None   # stagnation guard: fingerprint of last (code, stdout)
        fp_run: int = 0              # consecutive run-length of the same fingerprint
        escalation_reason: str = "max_rounds_exceeded"  # telemetry label; overwritten at each escalated=True site
        text = ""
        while step < self._cfg.max_steps:
            messages, _prune_ev = self._maybe_prune(messages, session_id)
            if _prune_ev is not None:
                yield _prune_ev
            async for ev in self._maybe_proactive_compact(session_id, step):
                yield ev
            if self._messages_override is not None:
                messages = self._messages_override
                self._messages_override = None
            if self._router is not None:
                _code_so_far = text or ""
                _code_block = extract_code_block(_code_so_far) if _code_so_far else None
                _tool_names = extract_tool_names(_code_block) if _code_block else []
                _primary_tool = _tool_names[0] if _tool_names else None
                _phase = "act"
                try:
                    from argos.routing.categorizer import categorize as _categorize
                    _category = _categorize(
                        tool=_primary_tool, code=_code_block, phase=_phase, step=step,
                    )
                    _client, _decision = self._router.select(
                        category=_category, tool=_primary_tool, step=step,
                    )
                    self._model = _client
                    self._current_tier = _decision.tier
                except Exception:  # noqa: BLE001
                    self._current_tier = self._cfg.model_tier
            scrubber = StreamingContextScrubber()
            text = ""
            prompt_messages = list(messages)
            try:
                async for delta in self._model.stream(messages, system=system_stable,
                                                        system_dynamic=system_dynamic):
                    text += delta
                    clean = scrubber.feed(delta)
                    if clean:
                        yield TokenDelta(text=clean)
            except Exception as e:  # noqa: BLE001
                from argos.core.recovery import classify_error
                ce = classify_error(e)
                if (ce.should_compress and self._cfg.compaction and compactions < 3
                        and hasattr(self._store, "compact_messages")):
                    compactions += 1
                    self._store.compact_messages(session_id, keep_recent=5)   # type: ignore[attr-defined]
                    messages = self._store.get_messages(session_id)
                    messages = self._anchor_core_messages(messages, self._current_goal)
                    self._compacted = True
                    self._reverified_since_compact = False
                    continue
                raise
            tail = scrubber.flush()
            if tail:
                yield TokenDelta(text=tail)
            messages.append({"role": "assistant", "content": text})

            for m in _PROPOSE_VERIFY.finditer(text):
                self._on_propose_verify(m.group(1))

            for dm in _PROPOSE_DOM_VERIFY.finditer(text):
                self._on_propose_dom_verify(dm.group(1))

            for gm in _PROPOSE_GUI_VERIFY.finditer(text):
                self._on_propose_gui_verify(gm.group(1))

            if self._verify_rejected is not None:
                if getattr(self, "_verify_rejected_fstring", False):
                    messages.append({"role": "user", "content":
                        _i18n_t("loop.verify_gate.fstring_rejected", cmd=self._verify_rejected)})
                    self._verify_rejected_fstring = False
                elif (os.environ.get("ARGOS_BRIDGE_VERIFY_LOCK", "1") != "0"
                        and os.environ.get("ARGSOS_BRIDGE_VERIFY_LOCK", "1") != "0")\
                        and self._cfg.verify_cmd is not None and self._cfg.verify_cmd.strip():
                    messages.append({"role": "user", "content":
                        _i18n_t("loop.verify_gate.bridge_locked", cmd=self._verify_rejected)})
                else:
                    messages.append({"role": "user", "content":
                        _i18n_t("loop.verify_gate.trivial_rejected", cmd=self._verify_rejected)})
                self._verify_rejected = None

            new_todos = extract_plan_todos(text)
            if new_todos is not None and new_todos != self._todos:
                self._todos = new_todos
                yield PlanUpdate(todos=new_todos)

            usage = getattr(self._model, "last_usage", None) or {}
            self._tok_in += int(usage.get("input_tokens") or 0)
            self._tok_out += int(usage.get("output_tokens") or 0)
            self._cache_read += int(usage.get("cache_read") or 0)
            context_used = _context_used_from_usage(
                usage, system=system_stable, system_dynamic=system_dynamic,
                messages=prompt_messages,
            )
            from argos.core.observability import PRICING, cost_of
            _tier = getattr(self._model, "tier", None)
            model_name = getattr(_tier, "model", "") if _tier is not None else ""
            _sc = cost_of({"input_tokens": self._tok_in, "output_tokens": self._tok_out}, model=model_name)
            cost = _sc.cost_usd if model_name in PRICING else None
            yield CostUpdate(
                tokens_in=self._tok_in, tokens_out=self._tok_out,
                cost_usd=cost, elapsed_s=time.time() - self._started,
                cache_read=self._cache_read, context_used=context_used,
                tier_name=self._current_tier,
            )

            # Task 1.2: hard budget circuit-breaker — checked after each step's accounting.
            # None ceiling = no limit; both guards use the same running counters as CostUpdate.
            _budget_msg: str | None = None
            if self._cfg.max_tokens_in is not None and self._tok_in > self._cfg.max_tokens_in:
                _budget_msg = (
                    f"budget exceeded: cumulative input tokens {self._tok_in} "
                    f"> max_tokens_in {self._cfg.max_tokens_in}"
                )
            elif (self._cfg.max_cost_usd is not None
                  and cost is not None
                  and cost > self._cfg.max_cost_usd):
                _budget_msg = (
                    f"budget exceeded: cumulative cost ${cost:.6f} "
                    f"> max_cost_usd ${self._cfg.max_cost_usd:.6f}"
                )
            if _budget_msg is not None:
                await self._hbus.emit(Escalation(
                    reason=_budget_msg,
                    attempts=step,
                    last_failure=_budget_msg,
                ))
                for ev in self._hbus.drain():
                    yield ev
                escalation_reason = "budget_exceeded"
                escalated = True
                break

            code = extract_code_block(text)
            awaiting_user_confirmation = (
                code is not None and _asks_user_confirmation_before_action(text)
            )
            if awaiting_user_confirmation:
                code = None
            if code is not None:
                # ── PreToolUse hook fire(spec §2.5)────────────────
                tool_names = extract_tool_names(code)
                pre_payload = build_pre_payload(
                    session_id=session_id, cwd=str(self._workspace),
                    code=code, tool_names=tool_names,
                )
                pre_result = await _hooks.fire(
                    "PreToolUse", pre_payload,
                    cwd=self._workspace, session_id=session_id,
                )
                for h in pre_result.per_hook:
                    yield HookFired(event_name="PreToolUse", command=h.command,
                                    success=h.success, returncode=h.returncode,
                                    elapsed_ms=h.elapsed_ms, timed_out=h.timed_out,
                                    not_found=h.not_found, stop_reason=h.stop_reason,
                                    error=h.error)
                if not pre_result.success:
                    reason = pre_result.stop_reason or _i18n_t("loop.hook.no_reason")
                    messages.append({"role": "user", "content":
                        _i18n_t("loop.hook.pretooluse_rejected", reason=reason)})
                    step += 1
                    continue
                yield CodeAction(code=code, step=step)
                result = await asyncio.to_thread(self._sandbox.exec_code, code)
                self._actions += 1
                if result.ok and _tool_names_indicate_mutation(tool_names):
                    made_changes = True
                elif result.ok and _code_mentions_file_mutation(code):
                    made_changes = True
                if result.ok:
                    try:
                        from argos import lsp as _lsp
                        from argos.lsp.trigger import (
                            extract_file_writes, extract_file_paths,
                        )
                        _lsp_mgr = _lsp.get_manager()
                        if _lsp_mgr is not None:
                            written: dict[str, str] = {
                                p: c for p, c in extract_file_writes(code)
                            }
                            for rel_path in extract_file_paths(code):
                                if rel_path in written:
                                    continue
                                abs_p = self._workspace / rel_path
                                if abs_p.exists():
                                    try:
                                        written[rel_path] = abs_p.read_text(
                                            encoding="utf-8", errors="replace",
                                        )
                                    except OSError:  # noqa: PERF203
                                        pass
                            from argos.lsp.manager import sync_file_sync
                            for rel_path, content in written.items():
                                abs_p = self._workspace / rel_path
                                sync_file_sync(_lsp_mgr, str(abs_p), content, timeout=3.0)
                    except Exception as _lsp_exc:  # noqa: BLE001
                        log.debug("LSP trigger skipped: %s", _lsp_exc)
                yield CodeResult(
                    step=step, stdout=result.stdout,
                    value_repr=result.value_repr, exc=result.exc, ok=result.ok,
                )
                # ── Stagnation guard (Task 1.1) ───────────────────
                # Same (code, stdout) pair repeated >= STAGNATION_LIMIT consecutive
                # times on a *failing* execution → model is stuck; break + escalate.
                # Successful execution resets: idempotent-but-ok code isn't stagnant.
                if not result.ok:
                    _fp = hashlib.sha256(
                        (code + "\x00" + (result.stdout or "")).encode()
                    ).hexdigest()
                    if _fp == last_fp:
                        fp_run += 1
                    else:
                        last_fp = _fp
                        fp_run = 1
                else:
                    last_fp = None
                    fp_run = 0
                if fp_run >= STAGNATION_LIMIT:
                    _stag_msg = (
                        f"stagnant: identical (code, stdout) repeated "
                        f"{fp_run} consecutive times"
                    )
                    await self._hbus.emit(Escalation(
                        reason=_stag_msg,
                        attempts=fp_run,
                        last_failure=_stag_msg,
                    ))
                    for ev in self._hbus.drain():
                        yield ev
                    escalation_reason = "stagnation"
                    escalated = True
                    break
                # ── PostToolUse hook fire(spec §2.5)───────────────
                post_payload = build_post_payload(
                    session_id=session_id, cwd=str(self._workspace),
                    code=code, tool_names=extract_tool_names(code),
                    stdout=result.stdout, value_repr=result.value_repr,
                    exc=result.exc, ok=result.ok,
                )
                post_result = await _hooks.fire(
                    "PostToolUse", post_payload,
                    cwd=self._workspace, session_id=session_id,
                )
                for h in post_result.per_hook:
                    yield HookFired(event_name="PostToolUse", command=h.command,
                                    success=h.success, returncode=h.returncode,
                                    elapsed_ms=h.elapsed_ms, timed_out=h.timed_out,
                                    not_found=h.not_found, stop_reason=h.stop_reason,
                                    error=h.error)

                if not result.ok and result.exc:
                    try:
                        from argos.memory import auto as _mem_auto
                        from argos.memory.auto import project_id_for as _pid
                        _tool_names = extract_tool_names(code)
                        for _t in _tool_names:
                            _mem_auto.capture_event(
                                "tool_repeat_fail",
                                project_id=_pid(self._workspace),
                                tool=_t,
                                error=str(result.exc)[:200],
                            )
                    except Exception:  # noqa: BLE001
                        pass
                elif result.ok:
                    try:
                        from argos.memory import auto as _mem_auto
                        from argos.memory.auto import (
                            project_id_for as _pid,
                            _reset_tool_fail_counter as _rst,
                        )
                        for _t in extract_tool_names(code):
                            _rst(_pid(self._workspace), _t)
                    except Exception:  # noqa: BLE001
                        pass

                if self._broker is not None:
                    new_receipt = self._broker.take_receipt()
                    if new_receipt is not None and self._harness.accept_receipt(new_receipt):
                        if new_receipt.action in _MUTATION_TOOL_NAMES:
                            made_changes = True
                        yield ToolReceipt(receipt=new_receipt)
                if self._broker is not None and hasattr(self._broker, "take_computer_artifact"):
                    self._pending_screenshot = self._broker.take_computer_artifact()
                _wf_on = __import__("os").environ.get("ARGOS_WORKFLOWS") == "1"
                _wf_spec = (extract_workflow_spec(text) if "propose_workflow" in text else None)
                if _wf_spec is not None and _wf_on:
                    async for ev in self._run_workflow(_wf_spec, messages):
                        yield ev
                    step += 1
                    continue
                feedback = self._feedback(result)
                if _wf_spec is not None and not _wf_on:
                    feedback = _i18n_t("loop.workflow.not_enabled") + "\n" + feedback
                if self._todos:
                    feedback += "\n\n" + self._todos_summary(self._todos)
                _fb_msg: dict = {"role": "user", "content": feedback}
                _shot = getattr(self, "_pending_screenshot", None)
                self._pending_screenshot = None
                self._maybe_attach_screenshot(_fb_msg, _shot)
                messages.append(_fb_msg)
                step += 1
                continue

            if awaiting_user_confirmation:
                async for ev in self._enter_phase("verify"):
                    yield ev
                conversational_done = True
                last_verdict = None
                report_note = ""
                break

            if ((self._actions == 0 or _has_unfinished_todos(self._todos))
                    and not noaction_nudged
                    and _looks_like_lazy_claim(text)):
                noaction_nudged = True
                messages.append({"role": "user", "content":
                    _i18n_t("loop.nudge.no_code_action")})
                step += 1
                continue

            if made_changes and self._verify_cmd is None and not verify_nudged:
                verify_nudged = True
                messages.append({"role": "user", "content":
                    _i18n_t("loop.nudge.verify_missing")})
                step += 1
                continue

            async for ev in self._enter_phase("verify"):
                yield ev

            if (not made_changes and self._verify_cmd is None
                    and self._pending_l3_strategy is None
                    and not self._pending_gui_expected_text):
                conversational_done = True
                last_verdict = None
                report_note = ""
                break

            if (self._verify_cmd is None and made_changes
                    and not os.environ.get("ARGOS_NO_VERIFY_STRATEGY")):
                self._verify_cmd = self._pick_strategy_cmd(goal)

            _probe_lane_verdict = False
            if self._pending_l3_strategy is not None and self._verify_cmd is None:
                verdict = await self._run_dom_probe_verdict(
                    self._pending_l3_strategy, attempt=self._fail_count + 1
                )
                self._pending_l3_strategy = None
                self._pending_dom_expected_text = ""
                _probe_lane_verdict = True
            elif self._pending_gui_expected_text and self._verify_cmd is None:
                verdict = await self._run_gui_probe_verdict(
                    self._pending_gui_expected_text, attempt=self._fail_count + 1
                )
                self._pending_gui_expected_text = ""
                _probe_lane_verdict = True
            else:
                # Propagate the current goal so the self-test reviewer proposer gets real context.
                _verifier = self._harness.verifier
                if hasattr(_verifier, "set_goal") and self._current_goal:
                    _verifier.set_goal(self._current_goal)
                verdict = await self._harness.run_verify_gate(
                    self._verify_cmd, attempt=self._fail_count + 1
                )
            last_verdict = verdict
            self._reverified_since_compact = True
            for ev in self._hbus.drain():
                yield ev

            if verdict.status == "failed" and self._verify_cmd:
                try:
                    from argos.memory import auto as _mem_auto
                    from argos.memory.auto import project_id_for as _pid
                    import hashlib as _hl
                    _snip = (verdict.detail or "")[:200]
                    _mem_auto.capture_event(
                        "verify_fail",
                        project_id=_pid(self._workspace),
                        cmd=self._verify_cmd,
                        stderr_hash=_hl.sha1(_snip.encode()).hexdigest()[:16],
                        stderr_snippet=_snip,
                    )
                except Exception:  # noqa: BLE001
                    pass

            from argos.core.honesty import trust_passed_after_compaction
            if (getattr(verdict, "is_user_verified", False)
                    and (self._verify_cmd is not None or _probe_lane_verdict)
                    and trust_passed_after_compaction(
                        compacted=self._compacted,
                        reverified=self._reverified_since_compact)):
                if self._compacted:
                    report_note = _i18n_t("loop.report_note.compacted_reverified")
                break
            if self._harness.is_honest_completion(verdict, verify_cmd=self._verify_cmd):
                if self._compacted:
                    report_note = _i18n_t("loop.report_note.no_test_compacted")
                else:
                    report_note = _i18n_t("loop.report_note.no_test")
                break
            self._fail_count += 1
            if self._fail_count > self._cfg.max_rounds:
                escalated = True
                break
            bounce = _i18n_t(
                "loop.verify_gate.bounce",
                verify_cmd=self._verify_cmd,
                detail=verdict.detail,
            )
            messages.append({"role": "user", "content": bounce})
            step += 1

        from argos.core.harness import PHASE_ORDER
        if self._harness._phase_idx < PHASE_ORDER.index("verify"):
            async for ev in self._enter_phase("verify"):
                yield ev
            from argos.protocol.events import VerifyVerdict as _VV
            _bailout_verdict = self._harness.verifier.verify(
                self._verify_cmd, attempts=self._fail_count + 1,
            )
            await self._harness.bus.emit(_VV(verdict=_bailout_verdict))
            for ev in self._hbus.drain():
                yield ev
            last_verdict = _bailout_verdict
            self._reverified_since_compact = True


        try:
            from argos.memory import auto as _mem_auto
            from argos.memory.auto import project_id_for as _pid
            if escalated:
                _mem_auto.capture_event(
                    "escalation_decision",
                    project_id=_pid(self._workspace),
                    reason=escalation_reason,
                    user_reply="escalated",
                )
            elif (not report_note and step >= 5
                  and last_verdict is not None
                  and getattr(last_verdict, "is_user_verified", False)):
                _mem_auto.capture_event(
                    "run_success",
                    project_id=_pid(self._workspace),
                    goal=(self._user_goal or "")[:120],
                    steps=step,
                    key_cmd=(self._verify_cmd or "")[:120],
                )
        except Exception:  # noqa: BLE001
            pass

        persisted = text.strip()
        if not persisted:
            if escalated:
                persisted = _i18n_t("loop.persisted.escalated")
            elif report_note:
                persisted = _i18n_t("loop.persisted.with_note", report_note=report_note)
            else:
                persisted = _i18n_t("loop.persisted.done")
        self._store.append_message(session_id, role="assistant", content=persisted)

        # ── report ──
        if report_note:
            self._store.append_message(
                session_id, role="system", content=f"[report] {report_note}"
            )
        async for ev in self._enter_phase("report"):
            yield ev
        if conversational_done:
            done = ""
        elif escalated:
            done = _i18n_t("loop.done.escalated")
        elif report_note:
            done = _i18n_t("loop.done.with_note", report_note=report_note)
        elif last_verdict is not None and getattr(last_verdict, "is_user_verified", False):
            done = _i18n_t("loop.done.verified")
        elif (last_verdict is not None
              and getattr(last_verdict, "status", None) == "passed"
              and getattr(last_verdict, "self_verified", False)):
            done = _i18n_t("loop.done.self_verified")
        elif last_verdict is not None and getattr(last_verdict, "status", None) != "passed":
            done = _i18n_t("loop.done.verdict_bad")
        else:
            done = _i18n_t("loop.done.generic")
        # ── Stop hook fire(spec §2.5)───────────────────────
        stop_payload = build_stop_payload(
            session_id=session_id, cwd=str(self._workspace),
            goal=goal, verdict_status=(last_verdict.status
                if last_verdict is not None else "unknown"),
            actions=self._actions, elapsed_s=time.time() - self._started,
            escalated=escalated,
        )
        stop_result = await _hooks.fire(
            "Stop", stop_payload,
            cwd=self._workspace, session_id=session_id,
        )
        for h in stop_result.per_hook:
            yield HookFired(event_name="Stop", command=h.command,
                            success=h.success, returncode=h.returncode,
                            elapsed_ms=h.elapsed_ms, timed_out=h.timed_out,
                            not_found=h.not_found, stop_reason=h.stop_reason,
                            error=h.error)
        if done:
            yield TokenDelta(text=done)

    async def _run_workflow(self, raw_spec: dict, messages: list) -> "AsyncIterator[Event]":
        from argos.protocol.events import WorkflowProposed, WorkflowDone
        from argos.workflow.result import render_preview
        from argos.workflow.spec import WorkflowSpecError, parse_spec
        import uuid as _uuid
        if self._workflow_engine_factory is None:
            messages.append({"role": "user", "content": _i18n_t("loop.workflow.no_engine")})
            return
        try:
            spec = parse_spec(raw_spec)
        except WorkflowSpecError as e:
            messages.append({"role": "user", "content": _i18n_t("loop.workflow.spec_invalid", error=e)})
            return
        preview = render_preview(spec)
        call_id = _uuid.uuid4().hex[:12]
        yield WorkflowProposed(name=spec.name, description=spec.description,
                               preview=preview, call_id=call_id)
        gate = self._broker.gate if self._broker is not None else None
        if gate is not None:
            decision = await gate.request("run_workflow", {"name": spec.name},
                                          description=preview, risk="high",
                                          timeout=120.0, call_id=call_id)
            if not decision.approved:
                messages.append({"role": "user", "content": _i18n_t("loop.workflow.rejected")})
                return
        engine = self._workflow_engine_factory()
        async for ev in engine.run(spec):
            yield ev
        result = engine.last_result
        synth = result.synthesis if result else _i18n_t("loop.workflow.no_result")
        notes = result.notes if result else ()
        yield WorkflowDone(name=spec.name, synthesis=synth, notes=notes)
        summary = _i18n_t("loop.workflow.result_summary", name=spec.name, synthesis=synth)
        if notes:
            summary += _i18n_t("loop.workflow.result_notes", notes=" / ".join(notes))
        messages.append({"role": "user", "content": summary})

    PLAN_DECISION_TIMEOUT_S: float = 300.0

    # ── Plan mode (spec §2.5) ──────────────────────────────────────────
    async def _run_plan_phase_loop(
        self, goal: str, messages: list[dict], system: str,
    ) -> "AsyncIterator[Event]":
        while True:
            async for ev in self._plan_phase_round(goal, messages, system):
                yield ev
            try:
                await asyncio.wait_for(
                    self._plan_decision_event.wait(),
                    timeout=self.PLAN_DECISION_TIMEOUT_S,
                )
            except asyncio.TimeoutError:
                yield Error(
                    message=_i18n_t(
                        "loop.plan.timeout",
                        timeout=self.PLAN_DECISION_TIMEOUT_S,
                    ),
                    chain=["asyncio.TimeoutError: plan_decision_event.wait() timed out"],
                )
                self._plan_call_registry.clear()
                raise asyncio.CancelledError("plan_decision_timeout")
            decision = self._plan_decision
            if decision is None:
                yield Error(
                    message=_i18n_t("loop.plan.decision_none"),
                    chain=["AssertionError: _plan_decision is None after event.wait()"],
                )
                self._plan_call_registry.clear()
                raise asyncio.CancelledError("plan_decision_none")
            if decision.action == "approve_start":
                return
            if decision.action == "keep_planning":
                self._plan_decision = None
                self._plan_decision_event = asyncio.Event()
                continue
            if decision.action == "refine":
                feedback_text = (decision.feedback or "").strip()
                if feedback_text:
                    messages.append({"role": "user", "content": feedback_text})
                self._plan_decision = None
                self._plan_decision_event = asyncio.Event()
                continue
            return

    async def _plan_phase_round(
        self, goal: str, messages: list[dict], system: str,
    ) -> "AsyncIterator[Event]":
        scrubber = StreamingContextScrubber()
        text = ""
        prompt_messages = list(messages)
        async for delta in self._model.stream(messages, system=system):
            text += delta
            clean = scrubber.feed(delta)
            if clean:
                yield TokenDelta(text=clean)
        tail = scrubber.flush()
        if tail:
            yield TokenDelta(text=tail)
        messages.append({"role": "assistant", "content": text})

        new_todos = extract_plan_todos(text)
        if new_todos is not None and new_todos != self._todos:
            self._todos = new_todos
            yield PlanUpdate(todos=new_todos)

        usage = getattr(self._model, "last_usage", None) or {}
        self._tok_in += int(usage.get("input_tokens") or 0)
        self._tok_out += int(usage.get("output_tokens") or 0)
        self._cache_read += int(usage.get("cache_read") or 0)
        from argos.core.observability import PRICING, cost_of
        _tier = getattr(self._model, "tier", None)
        model_name = getattr(_tier, "model", "") if _tier is not None else ""
        _sc = cost_of({"input_tokens": self._tok_in, "output_tokens": self._tok_out}, model=model_name)
        cost = _sc.cost_usd if model_name in PRICING else None
        yield CostUpdate(
            tokens_in=self._tok_in, tokens_out=self._tok_out,
            cost_usd=cost, elapsed_s=time.time() - self._started,
            cache_read=self._cache_read,
            context_used=_context_used_from_usage(
                usage, system=system, messages=prompt_messages,
            ),
            tier_name=self._current_tier,
        )

        plan_md = PlanRenderer.render(
            goal=goal, todos=list(self._todos), tool_calls=[],
        )
        yield PlanRendered(plan_md=plan_md)

        import secrets as _secrets
        _call_id = _secrets.token_hex(6)
        self._plan_call_registry[_call_id] = self._plan_decision_event
        yield PlanDecisionRequest(call_id=_call_id, plan_md=plan_md)

    @staticmethod
    def _feedback(result: Any) -> str:
        from argos.i18n import t as _t_fb
        if not result.ok:
            return _t_fb("loop.exec.exception", exc=result.exc)
        out = result.stdout
        if result.value_repr:
            out += _t_fb("loop.exec.value_repr", value_repr=result.value_repr)
        out = _clamp_feedback(out)
        return _t_fb("loop.exec.result", out=out) if out.strip() else _t_fb("loop.exec.no_output")


from argos.tools.receipts import ReceiptSigner as _ReceiptSigner  # noqa: E402
