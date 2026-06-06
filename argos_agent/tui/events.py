"""类型化事件(SHARED INTERFACE CONTRACT §1)——asyncio.Queue 事件桥。

一份事件三用(spec §12.6):自建 loop 投这些冻结事件 → ① TUI 渲染源
② ArgosStore.events 持久化记录 ③ replay() 重建源。事件名 = dataclass 类名的
snake_case,由 Event.kind 类属性常量携带,便于持久化与 replay。

Phase 3(loop)落地:EventBus 的 async 投递/消费。
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field, asdict
from typing import TYPE_CHECKING, Any, AsyncIterator, Literal

from argos_agent.core.types import Phase, RiskLevel, DecisionKind

if TYPE_CHECKING:  # Phase 3 落地;Phase 2 只序列化其 dict 形态
    from argos_agent.core.types import Verdict, Receipt  # noqa: F401
    from argos_agent.hooks.events import HookFired  # noqa: F401
    from argos_agent.skills_runtime.events import SkillRunStart, SkillRunEnd  # noqa: F401

EventKind = Literal[
    "token_delta", "code_action", "code_result", "file_diff",
    "tool_receipt", "verify_verdict", "phase_change", "cost_update",
    "approval_request", "approval_response", "escalation", "error",
    "plan_update", "workflow_progress", "workflow_proposed", "workflow_done",
    "plan_rendered",
    "hook_fired",
    "lsp_server_event",
    "lsp_diagnostic_event",
    "skill_run_start",   # ← 新增
    "skill_run_end",     # ← 新增
]


@dataclass(frozen=True, slots=True)
class TokenDelta:
    kind = "token_delta"
    text: str                        # 仅 text 增量,thinking 已剥离


@dataclass(frozen=True, slots=True)
class CodeAction:
    kind = "code_action"
    code: str
    step: int                        # loop 步序号,从 0 起


@dataclass(frozen=True, slots=True)
class CodeResult:
    kind = "code_result"
    step: int
    stdout: str
    value_repr: str                  # 末尾表达式 repr(),无则 ""
    exc: str                         # 异常文本(含类型),无则 ""
    ok: bool                         # exc == "" 即 True


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
    receipt: "Receipt"               # §6 Receipt(host broker 已签);Phase 3 落地


@dataclass(frozen=True, slots=True)
class VerifyVerdict:
    kind = "verify_verdict"
    verdict: "Verdict"               # §6 三态 Verdict;Phase 3 落地


@dataclass(frozen=True, slots=True)
class PhaseChange:
    kind = "phase_change"
    phase: Phase                     # plan|act|verify|report
    actions: int


@dataclass(frozen=True, slots=True)
class CostUpdate:
    kind = "cost_update"
    tokens_in: int
    tokens_out: int
    cost_usd: float | None    # 单价未知诚实置 None(不编造成本);渲染为 $(N/A)
    elapsed_s: float
    cache_read: int = 0
    context_used: int = 0     # 当前窗口占用 token(输入侧 input+cache),供上下文用量条;非会话累计


@dataclass(frozen=True, slots=True)
class ApprovalRequest:
    kind = "approval_request"
    call_id: str                     # 与 ApprovalResponse.call_id 对应(12 hex)
    action: str
    args: dict[str, Any]
    description: str
    risk: RiskLevel


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
    chain: list[str] = field(default_factory=list)  # 异常链(挖 4 层真因)


@dataclass(frozen=True, slots=True)
class PlanUpdate:
    kind = "plan_update"
    # [{content, status: pending|in_progress|completed, activeForm}] —— 真 TODO 拆解
    # (借 Claude Code TodoWrite),活动栏据此渲染子任务进度。
    todos: list[dict] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class WorkflowProgress:
    kind = "workflow_progress"
    # Dynamic Workflows:子 agent 阶段流转汇进活动栏(stage 内第 N 个 agent 的 phase)。
    stage_id: str
    agent_id: str
    phase: str
    note: str = ""


@dataclass(frozen=True, slots=True)
class WorkflowProposed:
    kind = "workflow_proposed"
    # Dynamic Workflows:agent 在 act 段调 propose_workflow({...}) → loop 校验出 spec 后投此事件。
    # call_id 与 ApprovalGate 的待批项对应(TUI 据它调 gate.respond 放行/拒绝)。
    name: str
    description: str
    preview: str                     # render_preview(spec) —— 人类可读的工作流编排预览
    call_id: str


@dataclass(frozen=True, slots=True)
class WorkflowDone:
    kind = "workflow_done"
    # 工作流引擎跑完:综合结论 + 诚实注记(cap 截断/部分失败/表决结果等)。
    # notes 是 tuple(不可变);序列化走 JSON 会摊成 list,deserialize 时还原回 tuple。
    name: str
    synthesis: str
    notes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PlanRendered:
    """Plan mode spec §2.5:plan 阶段产出 → host 拼 markdown → 投此事件 → TUI 弹 PlanModal。
    loop 在投事件后挂起(asyncio.Event)等用户决策,决策经 `ExitPlanMode` 落 `loop._plan_decision`
    后 set event 唤醒 loop,4 分支按 spec §2.5 处理。"""
    kind = "plan_rendered"
    plan_md: str                     # PlanRenderer.render() 产出的 user-facing markdown


# ── Hooks(spec 2026-06-06 §2.4):HookFired 在 hooks/events.py 定义(spec 强制在
#  hooks 子模块独立 dataclass,不让 tui 反向依赖 hooks 配置);TUI Event 联合
# 通过 `from argos_agent.hooks.events import HookFired` 接进来。───────────────
from argos_agent.hooks.events import HookFired  # noqa: E402


# ── LSP(spec 2026-06-06 §10.1):LspServerEvent / LspDiagnosticEvent 在
# lsp/events.py 定义(同 hooks 模式:spec 强制 lsp 子模块独立 dataclass,不让
# tui 反向依赖 lsp 配置 / manager);TUI Event 联合通过 `from argos_agent.lsp.events
# import ...` 接进来。
from argos_agent.lsp.events import LspServerEvent, LspDiagnosticEvent  # noqa: E402


# ── Skills runtime(spec 2026-06-06 §2.2):SkillRunStart / SkillRunEnd 在
# skills_runtime/events.py 定义(同 hooks/lsp 模式:spec 强制 skills 子模块独立
# dataclass,不让 tui 反向依赖 skills_runtime 配置 / registry)。
from argos_agent.skills_runtime.events import SkillRunStart, SkillRunEnd  # noqa: E402


Event = (
    TokenDelta | CodeAction | CodeResult | FileDiff | ToolReceipt
    | VerifyVerdict | PhaseChange | CostUpdate | ApprovalRequest
    | ApprovalResponse | Escalation | Error | PlanUpdate | WorkflowProgress
    | WorkflowProposed | WorkflowDone | PlanRendered | HookFired
    | LspServerEvent | LspDiagnosticEvent
    | SkillRunStart | SkillRunEnd   # ← 新增
)

# kind 常量 → 类,用于反序列化派发
_KIND_TO_CLASS: dict[str, type] = {
    c.kind: c
    for c in (
        TokenDelta, CodeAction, CodeResult, FileDiff, ToolReceipt,
        VerifyVerdict, PhaseChange, CostUpdate, ApprovalRequest,
        ApprovalResponse, Escalation, Error, PlanUpdate, WorkflowProgress,
        WorkflowProposed, WorkflowDone, PlanRendered, HookFired,
        LspServerEvent, LspDiagnosticEvent,
        SkillRunStart, SkillRunEnd,   # ← 新增
    )
}


class _Sentinel:
    """流结束哨兵(内部用,不入 Event 联合)。"""


_END = _Sentinel()


class EventBus:
    """loop 与 TUI 的唯一交汇点(契约 §1)。Phase 3(loop)落地。
    close() 投哨兵令消费侧 async-for 自然结束(TUI start_run 收尾用)。"""

    def __init__(self) -> None:
        self._q: "asyncio.Queue[Event | _Sentinel]" = asyncio.Queue()

    async def emit(self, ev: Event) -> None:
        """loop 侧投递事件。"""
        await self._q.put(ev)

    async def close(self) -> None:
        """投哨兵,令 __aiter__ 自然结束(loop/start_run 收尾时调)。"""
        await self._q.put(_END)

    async def __aiter__(self) -> AsyncIterator[Event]:
        """TUI Worker 消费侧。遇哨兵自然结束。"""
        while True:
            item = await self._q.get()
            if isinstance(item, _Sentinel):
                return
            yield item


def event_kind(ev: Event) -> str:
    """取事件的 kind 常量(= 类名 snake_case)。"""
    return type(ev).kind  # type: ignore[attr-defined]


def serialize_event(ev: Event) -> str:
    """事件 → JSON 串(存进 events 表)。kind 随 payload 一起写,便于反序列化派发。

    ToolReceipt/VerifyVerdict 含嵌套 dataclass(Receipt/Verdict),asdict 递归展开;
    Phase 2 这两类只走持久化(loop 未接),round-trip 在 Phase 3 接 Receipt/Verdict 后补测。
    """
    payload = asdict(ev)  # type: ignore[arg-type]
    return json.dumps({"kind": event_kind(ev), "data": payload}, ensure_ascii=False)


def _decode_receipt(data: dict[str, Any]) -> "Receipt":
    """M7:把持久化的 receipt dict 还原成 Receipt dataclass(replay §5.8 要真对象,非 dict)。"""
    from argos_agent.tools.receipts import Receipt as _Receipt
    return _Receipt(**data)


def _decode_verdict(data: dict[str, Any]) -> "Verdict":
    """M7:把持久化的 verdict dict 还原成 Verdict dataclass(replay §5.8 要真对象,非 dict)。"""
    from argos_agent.core.verify_gate import Verdict as _Verdict
    return _Verdict(**data)


def deserialize_event(blob: str) -> Event:
    """JSON 串 → 事件。未知 kind → ValueError(fail-loud,坏数据不静默吞)。

    M7:ToolReceipt.receipt / VerifyVerdict.verdict 是嵌套 dataclass —— serialize 时 asdict
    把它们摊成 dict,deserialize 必须显式还原成 Receipt/Verdict,否则 replay 会拿到 dict
    而非 dataclass(下游 .action/.status 等属性访问会炸)。已是 dataclass(直接构造)则原样保留。
    """
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
        # JSON 不分 tuple/list:WorkflowDone.notes 声明为 tuple,还原回 tuple 保持精确相等。
        data["notes"] = tuple(data["notes"])
    return cls(**data)
