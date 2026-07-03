from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field, asdict
from typing import TYPE_CHECKING, Any, AsyncIterator, Literal

from argos.core.types import Phase, RiskLevel, DecisionKind
from argos.i18n import t

if TYPE_CHECKING:
    from argos.core.types import Verdict, Receipt  # noqa: F401
    from argos.hooks.events import HookFired  # noqa: F401
    from argos.skills_runtime.events import SkillRunStart, SkillRunEnd  # noqa: F401

EventKind = Literal[
    "token_delta", "code_action", "code_result", "file_diff",
    "tool_receipt", "verify_verdict", "phase_change", "cost_update",
    "approval_request", "approval_response", "escalation", "error",
    "plan_update", "workflow_progress", "workflow_proposed", "workflow_done",
    "plan_rendered",
    "plan_decision_request",
    "memory_recall",
    "hook_fired",
    "lsp_server_event",
    "lsp_diagnostic_event",
    "skill_run_start",
    "skill_run_end",
    "compacted",
    "pruned",
    "ledger_entry",
    "proactive_suggestion",
    "computer_action",
    "dream_progress",
    "dream_report",
]


@dataclass(frozen=True, slots=True)
class TokenDelta:
    kind = "token_delta"
    text: str


@dataclass(frozen=True, slots=True)
class CodeAction:
    kind = "code_action"
    code: str
    step: int


@dataclass(frozen=True, slots=True)
class CodeResult:
    kind = "code_result"
    step: int
    stdout: str
    value_repr: str
    exc: str
    ok: bool


@dataclass(frozen=True, slots=True)
class FileDiff:
    kind = "file_diff"
    path: str
    added: int
    removed: int
    unified: str


@dataclass(frozen=True, slots=True)
class ToolReceipt:
    kind = "tool_receipt"
    receipt: "Receipt"


@dataclass(frozen=True, slots=True)
class VerifyVerdict:
    kind = "verify_verdict"
    verdict: "Verdict"


@dataclass(frozen=True, slots=True)
class PhaseChange:
    kind = "phase_change"
    phase: Phase                     # plan|act|verify|report
    actions: int
    max_steps: int | None = None     # loopmaxxing budget; None = unknown (safe default)


@dataclass(frozen=True, slots=True)
class CostUpdate:
    kind = "cost_update"
    tokens_in: int
    tokens_out: int
    cost_usd: float | None
    elapsed_s: float
    cache_read: int = 0
    context_used: int = 0
    tier_name: str = ""


@dataclass(frozen=True, slots=True)
class ApprovalRequest:
    kind = "approval_request"
    call_id: str
    action: str
    args: dict[str, Any]
    description: str
    risk: RiskLevel
    trigger: str = ""
    secret_pattern: str | None = None


@dataclass(frozen=True, slots=True)
class ApprovalResponse:
    kind = "approval_response"
    call_id: str
    decision: DecisionKind           # deny|once|session|always


@dataclass(frozen=True, slots=True)
class Escalation:
    kind = "escalation"
    reason: str
    attempts: int
    last_failure: str


@dataclass(frozen=True, slots=True)
class Error:
    kind = "error"
    message: str
    chain: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class PlanUpdate:
    kind = "plan_update"
    todos: list[dict] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class WorkflowProgress:
    kind = "workflow_progress"
    stage_id: str
    agent_id: str
    phase: str
    note: str = ""


@dataclass(frozen=True, slots=True)
class WorkflowProposed:
    kind = "workflow_proposed"
    name: str
    description: str
    preview: str
    call_id: str


@dataclass(frozen=True, slots=True)
class CompactedEvent:
    kind = "compacted"
    before: int
    after: int
    reduction_pct: float
    triggered_by: str                # "proactive" | "error"
    session_id: str = ""


@dataclass(frozen=True, slots=True)
class LedgerEntryEvent:
    kind = "ledger_entry"
    ts: float
    run_id: str
    seq: int
    action: str
    summary_human: str
    risk: str                 # "low" | "medium" | "high"
    reversible: str           # "yes" | "no" | "unknown"
    undo_state: str           # "available" | "done" | "impossible"


@dataclass(frozen=True, slots=True)
class PrunedEvent:
    kind = "pruned"
    before: int
    after: int
    removed: int
    reduction_pct: float
    aggressiveness: float
    session_id: str = ""


@dataclass(frozen=True, slots=True)
class WorkflowDone:
    kind = "workflow_done"
    name: str
    synthesis: str
    notes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PlanRendered:
    kind = "plan_rendered"
    plan_md: str


@dataclass(frozen=True, slots=True)
class ProactiveSuggestionEvent:
    kind = "proactive_suggestion"
    suggestion_id: str      # ProactiveSuggestion.id
    order_id: str
    goal: str
    reason_human: str
    suggested_at: float
    requires_confirmation: bool = True
    action: Literal["run", "dream"] = "run"

    def __post_init__(self) -> None:
        if self.action not in ("run", "dream"):
            raise ValueError(
                t("core2.events.proactive_action_invalid", action=self.action)
            )


@dataclass(frozen=True, slots=True)
class ComputerActionEvent:
    kind = "computer_action"
    kind_action: str
    x: int | None
    y: int | None
    text_preview: str
    ok: bool
    detail: str
    artifact_path: str | None = None


@dataclass(frozen=True, slots=True)
class DreamProgressEvent:
    kind = "dream_progress"
    stage: str        # scan | cluster | synthesize | promote | memory | done
    detail: str
    ts: float


@dataclass(frozen=True, slots=True)
class DreamReportEvent:
    kind = "dream_report"
    units_total: int
    promoted: int
    rejected: int
    skipped: int
    memory_merged: int
    memory_archived: int
    report_path: str
    ts: float


@dataclass(frozen=True, slots=True)
class PlanDecisionRequest:
    kind = "plan_decision_request"
    call_id: str
    plan_md: str


@dataclass(frozen=True, slots=True)
class MemoryRecallEvent:
    kind = "memory_recall"
    hits: list[str] = field(default_factory=list)  # ["goal → verdict（reason）", ...]


from argos.hooks.events import HookFired  # noqa: E402


from argos.lsp.events import LspServerEvent, LspDiagnosticEvent  # noqa: E402


from argos.skills_runtime.events import SkillRunStart, SkillRunEnd  # noqa: E402


Event = (
    TokenDelta | CodeAction | CodeResult | FileDiff | ToolReceipt
    | VerifyVerdict | PhaseChange | CostUpdate | ApprovalRequest
    | ApprovalResponse | Escalation | Error | PlanUpdate | WorkflowProgress
    | WorkflowProposed | WorkflowDone | PlanRendered
    | PlanDecisionRequest | MemoryRecallEvent
    | HookFired
    | LspServerEvent | LspDiagnosticEvent
    | SkillRunStart | SkillRunEnd
    | CompactedEvent | PrunedEvent  # ← context rot(spec 2026-06-07)
    | LedgerEntryEvent
    | ProactiveSuggestionEvent
    | ComputerActionEvent
    | DreamProgressEvent | DreamReportEvent
)

_KIND_TO_CLASS: dict[str, type] = {
    c.kind: c
    for c in (
        TokenDelta, CodeAction, CodeResult, FileDiff, ToolReceipt,
        VerifyVerdict, PhaseChange, CostUpdate, ApprovalRequest,
        ApprovalResponse, Escalation, Error, PlanUpdate, WorkflowProgress,
        WorkflowProposed, WorkflowDone, PlanRendered,
        PlanDecisionRequest, MemoryRecallEvent,
        HookFired,
        LspServerEvent, LspDiagnosticEvent,
        SkillRunStart, SkillRunEnd,
        CompactedEvent, PrunedEvent,
        LedgerEntryEvent,
        ProactiveSuggestionEvent,
        ComputerActionEvent,
        DreamProgressEvent, DreamReportEvent,
    )
}


def event_kind(ev: "Event") -> str:
    return type(ev).kind  # type: ignore[attr-defined]


def serialize_event(ev: "Event") -> str:
    payload = asdict(ev)  # type: ignore[arg-type]
    return json.dumps({"kind": event_kind(ev), "data": payload}, ensure_ascii=False)


def _decode_receipt(data: dict[str, Any]) -> "Receipt":
    from argos.tools.receipts import Receipt as _Receipt
    return _Receipt(**data)


def _decode_verdict(data: dict[str, Any]) -> "Verdict":
    from argos.core.verify_gate import Verdict as _Verdict
    return _Verdict(**data)


def deserialize_event(blob: str) -> "Event":
    obj = json.loads(blob)
    kind = obj.get("kind")
    cls = _KIND_TO_CLASS.get(kind)
    if cls is None:
        raise ValueError(f"unknown event kind: {kind!r}")
    data = dict(obj["data"])
    if kind == "tool_receipt" and isinstance(data.get("receipt"), dict):
        data["receipt"] = _decode_receipt(data["receipt"])
    elif kind == "verify_verdict" and isinstance(data.get("verdict"), dict):
        data["verdict"] = _decode_verdict(data["verdict"])
    elif kind == "workflow_done" and isinstance(data.get("notes"), list):
        data["notes"] = tuple(data["notes"])
    return cls(**data)



class _Sentinel:
    pass


_END = _Sentinel()


class EventBus:

    def __init__(self) -> None:
        self._q: "asyncio.Queue[Event | _Sentinel]" = asyncio.Queue()

    async def emit(self, ev: Event) -> None:
        await self._q.put(ev)

    async def close(self) -> None:
        await self._q.put(_END)

    async def __aiter__(self) -> AsyncIterator[Event]:
        while True:
            item = await self._q.get()
            if isinstance(item, _Sentinel):
                return
            yield item
