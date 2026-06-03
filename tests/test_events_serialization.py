"""Phase 2:§1 事件类冻结性 + serialize/deserialize round-trip。

events.py 是「一份事件三用」(spec §12.6)的源:UI 渲染 = events 表持久化 = replay 重建。
本测试锁死:① 12 个事件类齐全且 frozen+slots;② kind 常量 = 类名 snake_case;
③ 不含 Receipt/Verdict 的简单事件 round-trip 无损。
"""
import dataclasses

import pytest

from argos_agent.tui import events as E


ALL_EVENT_KINDS = {
    "token_delta", "code_action", "code_result", "file_diff",
    "tool_receipt", "verify_verdict", "phase_change", "cost_update",
    "approval_request", "approval_response", "escalation", "error",
}


def test_event_kind_literal_matches_contract():
    assert set(E.EventKind.__args__) == ALL_EVENT_KINDS


def test_all_event_classes_frozen_and_slots():
    classes = [
        E.TokenDelta, E.CodeAction, E.CodeResult, E.FileDiff,
        E.ToolReceipt, E.VerifyVerdict, E.PhaseChange, E.CostUpdate,
        E.ApprovalRequest, E.ApprovalResponse, E.Escalation, E.Error,
    ]
    assert len(classes) == 12
    for c in classes:
        params = c.__dataclass_params__
        assert params.frozen, f"{c.__name__} 必须 frozen"
        assert "__slots__" in c.__dict__, f"{c.__name__} 必须 slots"


def test_kind_constant_is_snake_case_classname():
    assert E.TokenDelta.kind == "token_delta"
    assert E.CodeResult.kind == "code_result"
    assert E.PhaseChange.kind == "phase_change"
    assert E.ApprovalRequest.kind == "approval_request"


def test_serialize_deserialize_token_delta_roundtrip():
    ev = E.TokenDelta(text="你好world")
    blob = E.serialize_event(ev)
    assert isinstance(blob, str)
    back = E.deserialize_event(blob)
    assert isinstance(back, E.TokenDelta)
    assert back.text == "你好world"


def test_serialize_deserialize_code_result_roundtrip():
    ev = E.CodeResult(step=3, stdout="ok", value_repr="42", exc="", ok=True)
    back = E.deserialize_event(E.serialize_event(ev))
    assert isinstance(back, E.CodeResult)
    assert (back.step, back.value_repr, back.ok) == (3, "42", True)


def test_serialize_deserialize_phase_change_and_cost():
    pc = E.PhaseChange(phase="verify", actions=7)
    assert E.deserialize_event(E.serialize_event(pc)).phase == "verify"
    cu = E.CostUpdate(tokens_in=100, tokens_out=50, cost_usd=0.001, elapsed_s=2.5)
    back = E.deserialize_event(E.serialize_event(cu))
    assert isinstance(back, E.CostUpdate) and back.tokens_out == 50


def test_error_default_chain_is_empty_list():
    e = E.Error(message="boom")
    assert e.chain == []
    # frozen:默认工厂不共享同一引用
    assert E.Error(message="x").chain is not e.chain
