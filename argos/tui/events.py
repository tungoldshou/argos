"""Internal documentation."""
from __future__ import annotations

from argos.protocol.events import (  # noqa: F401
    EventKind,
    TokenDelta,
    CodeAction,
    CodeResult,
    FileDiff,
    ToolReceipt,
    VerifyVerdict,
    PhaseChange,
    CostUpdate,
    ApprovalRequest,
    ApprovalResponse,
    Escalation,
    Error,
    PlanUpdate,
    WorkflowProgress,
    WorkflowProposed,
    CompactedEvent,
    PrunedEvent,
    WorkflowDone,
    PlanRendered,
    PlanDecisionRequest,
    MemoryRecallEvent,
    LedgerEntryEvent,
    ProactiveSuggestionEvent,
    ComputerActionEvent,
    DreamProgressEvent,
    DreamReportEvent,
    Event,
    EventBus,
    _KIND_TO_CLASS,
    _Sentinel,
    _END,
    event_kind,
    serialize_event,
    deserialize_event,
)

from argos.hooks.events import HookFired  # noqa: F401
from argos.lsp.events import LspServerEvent, LspDiagnosticEvent  # noqa: F401
from argos.skills_runtime.events import SkillRunStart, SkillRunEnd  # noqa: F401
