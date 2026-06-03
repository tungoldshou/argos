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

EventKind = Literal[
    "token_delta", "code_action", "code_result", "file_diff",
    "tool_receipt", "verify_verdict", "phase_change", "cost_update",
    "approval_request", "approval_response", "escalation", "error",
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
    cost_usd: float
    elapsed_s: float


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


Event = (
    TokenDelta | CodeAction | CodeResult | FileDiff | ToolReceipt
    | VerifyVerdict | PhaseChange | CostUpdate | ApprovalRequest
    | ApprovalResponse | Escalation | Error
)

# kind 常量 → 类,用于反序列化派发
_KIND_TO_CLASS: dict[str, type] = {
    c.kind: c
    for c in (
        TokenDelta, CodeAction, CodeResult, FileDiff, ToolReceipt,
        VerifyVerdict, PhaseChange, CostUpdate, ApprovalRequest,
        ApprovalResponse, Escalation, Error,
    )
}


class EventBus:
    """loop 与 TUI 的唯一交汇点(契约 §1)。Phase 3(loop)落地。"""

    def __init__(self) -> None:
        self._q: asyncio.Queue[Event] = asyncio.Queue()

    async def emit(self, ev: Event) -> None:
        """loop 侧投递事件。"""
        await self._q.put(ev)

    async def __aiter__(self) -> AsyncIterator[Event]:
        """TUI Worker 消费侧。"""
        while True:
            yield await self._q.get()


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


def deserialize_event(blob: str) -> Event:
    """JSON 串 → 事件。未知 kind → ValueError(fail-loud,坏数据不静默吞)。"""
    obj = json.loads(blob)
    kind = obj.get("kind")
    cls = _KIND_TO_CLASS.get(kind)
    if cls is None:
        raise ValueError(f"unknown event kind: {kind!r}")
    return cls(**obj["data"])
