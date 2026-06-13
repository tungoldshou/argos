"""兼容层(v6 P0)——新代码请 import argos_agent.protocol.events。

全部 Event dataclass 族 + EventBus + 序列化工具已物理搬至 argos_agent/protocol/events.py；
本模块保留为转发 shim，显式 re-export 所有公共名与测试用私有名，保持既有
import 路径零破坏(v6 P0 收尾:EventBus/_Sentinel/_END 一并搬入协议层 ——
总线是内核基础设施,不属于 TUI)。
"""
from __future__ import annotations

# ── 协议层公共名 re-export ───────────────────────────────────────────────────
from argos_agent.protocol.events import (  # noqa: F401
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
    LedgerEntryEvent,          # ← P3b 新增(§6 行为账本)
    IntentConfirmRequest,      # ← P4 新增(§7 意图引擎)
    IntentConfirmResponse,     # ← P4 新增(§7 意图引擎)
    ProactiveSuggestionEvent,  # ← P5b 新增(§9 自治面:conductor 主动建议)
    ComputerActionEvent,       # ← P6a 新增(§10 computer use:OS 级动作执行结果)
    DreamProgressEvent,        # ← T10 新增(Dream 夜间整合进度)
    DreamReportEvent,          # ← T10 新增(Dream 夜间整合结果汇总)
    Event,
    EventBus,
    _KIND_TO_CLASS,
    _Sentinel,
    _END,
    event_kind,
    serialize_event,
    deserialize_event,
)

# ── 子模块事件类(通过 protocol.events 已 re-import,此处显式暴露) ─────────────
from argos_agent.hooks.events import HookFired  # noqa: F401
from argos_agent.lsp.events import LspServerEvent, LspDiagnosticEvent  # noqa: F401
from argos_agent.skills_runtime.events import SkillRunStart, SkillRunEnd  # noqa: F401
