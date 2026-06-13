"""Phase 5 事件桥:12 个类型化 Event 可投递/消费,且全部不可变(契约 §1)。"""
from __future__ import annotations

import asyncio
import dataclasses

import pytest

from argos.tui.events import (
    EventBus,
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
)
from argos.core.types import Verdict


def test_all_events_are_frozen_dataclasses():
    cls_list = [
        TokenDelta, CodeAction, CodeResult, FileDiff, ToolReceipt,
        VerifyVerdict, PhaseChange, CostUpdate, ApprovalRequest,
        ApprovalResponse, Escalation, Error,
    ]
    for cls in cls_list:
        assert dataclasses.is_dataclass(cls)
        params = cls.__dataclass_params__
        assert params.frozen is True, f"{cls.__name__} 必须 frozen"


def test_event_kind_is_snake_case_classname():
    assert TokenDelta.kind == "token_delta"
    assert CodeAction.kind == "code_action"
    assert CodeResult.kind == "code_result"
    assert FileDiff.kind == "file_diff"
    assert ToolReceipt.kind == "tool_receipt"
    assert VerifyVerdict.kind == "verify_verdict"
    assert PhaseChange.kind == "phase_change"
    assert CostUpdate.kind == "cost_update"
    assert ApprovalRequest.kind == "approval_request"
    assert ApprovalResponse.kind == "approval_response"
    assert Escalation.kind == "escalation"
    assert Error.kind == "error"


def test_token_delta_is_immutable():
    ev = TokenDelta(text="hi")
    with pytest.raises(dataclasses.FrozenInstanceError):
        ev.text = "bye"  # type: ignore[misc]


@pytest.mark.asyncio
async def test_eventbus_emit_then_iterate():
    bus = EventBus()
    await bus.emit(TokenDelta(text="a"))
    await bus.emit(PhaseChange(phase="act", actions=1))
    await bus.close()  # 投哨兵,让 __aiter__ 自然结束
    got = [ev async for ev in bus]
    assert [e.kind for e in got] == ["token_delta", "phase_change"]
    assert got[0].text == "a"
    assert got[1].phase == "act" and got[1].actions == 1


@pytest.mark.asyncio
async def test_verify_verdict_carries_three_state_verdict():
    v = Verdict.unverifiable(detail="tampered", tampered=["test_x.py"], attempts=2)
    ev = VerifyVerdict(verdict=v)
    assert ev.verdict.status == "unverifiable"
    assert ev.verdict.tampered == ["test_x.py"]
