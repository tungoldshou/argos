import dataclasses

import pytest

from argos.tui import events as E


ALL_EVENT_KINDS = {
    "token_delta", "code_action", "code_result", "file_diff",
    "tool_receipt", "verify_verdict", "phase_change", "cost_update",
    "approval_request", "approval_response", "escalation", "error",
    "plan_update", "workflow_progress", "workflow_proposed", "workflow_done",
    "plan_rendered",
    "hook_fired",
    "lsp_server_event",
    "lsp_diagnostic_event",
    "skill_run_start",
    "skill_run_end",
    "compacted",
    "pruned",
    "plan_decision_request",
    "memory_recall",
    "ledger_entry",
    "proactive_suggestion",
    "computer_action",
    "dream_progress",
    "dream_report",
}


def test_event_kind_literal_matches_contract():
    assert set(E.EventKind.__args__) == ALL_EVENT_KINDS


def test_all_event_classes_frozen_and_slots():
    classes = [
        E.TokenDelta, E.CodeAction, E.CodeResult, E.FileDiff,
        E.ToolReceipt, E.VerifyVerdict, E.PhaseChange, E.CostUpdate,
        E.ApprovalRequest, E.ApprovalResponse, E.Escalation, E.Error,
        E.PlanUpdate, E.WorkflowProgress, E.WorkflowProposed, E.WorkflowDone,
        E.PlanRendered,
    ]
    assert len(classes) == 17
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


def test_serialize_deserialize_workflow_progress_roundtrip():
    ev = E.WorkflowProgress(stage_id="r", agent_id="r#0", phase="act", note="跑起来了")
    back = E.deserialize_event(E.serialize_event(ev))
    assert isinstance(back, E.WorkflowProgress)
    assert (back.stage_id, back.agent_id, back.phase, back.note) == ("r", "r#0", "act", "跑起来了")


def test_serialize_deserialize_workflow_proposed_roundtrip():
    ev = E.WorkflowProposed(name="审计", description="并行审计", preview="阶段 r: fan_out", call_id="abc123def456")
    back = E.deserialize_event(E.serialize_event(ev))
    assert isinstance(back, E.WorkflowProposed)
    assert (back.name, back.description, back.preview, back.call_id) == (
        "审计", "并行审计", "阶段 r: fan_out", "abc123def456")


def test_serialize_deserialize_workflow_done_notes_back_to_tuple():
    ev = E.WorkflowDone(name="审计", synthesis="结论已汇总", notes=("cap 截断", "1 个子任务失败"))
    back = E.deserialize_event(E.serialize_event(ev))
    assert isinstance(back, E.WorkflowDone)
    assert back.name == "审计" and back.synthesis == "结论已汇总"
    assert isinstance(back.notes, tuple)
    assert back.notes == ("cap 截断", "1 个子任务失败")


def test_workflow_done_default_notes_empty_tuple_roundtrip():
    ev = E.WorkflowDone(name="x", synthesis="完成")
    assert ev.notes == ()
    back = E.deserialize_event(E.serialize_event(ev))
    assert back.notes == () and isinstance(back.notes, tuple)


def test_error_default_chain_is_empty_list():
    e = E.Error(message="boom")
    assert e.chain == []
    assert E.Error(message="x").chain is not e.chain


def test_tool_receipt_roundtrip_keeps_receipt_dataclass():
    from argos.tools.receipts import Receipt, ReceiptSigner
    signer = ReceiptSigner(key=b"m7-test")
    rec = signer.sign(action="run_command", args={"command": "echo hi"},
                      result="hi", exit_code=0)
    ev = E.ToolReceipt(receipt=rec)
    back = E.deserialize_event(E.serialize_event(ev))
    assert isinstance(back, E.ToolReceipt)
    assert isinstance(back.receipt, Receipt), "receipt 必须还原成 Receipt dataclass,不是 dict"
    assert back.receipt.action == "run_command"
    assert back.receipt.exit_code == 0
    assert back.receipt.sig == rec.sig
    assert signer.verify(back.receipt) is True


def test_verify_verdict_roundtrip_keeps_verdict_dataclass():
    from argos.core.verify_gate import Verdict
    v = Verdict.failed(detail="[exit_code=1]\nboom", verify_cmd="pytest -q", attempts=2)
    ev = E.VerifyVerdict(verdict=v)
    back = E.deserialize_event(E.serialize_event(ev))
    assert isinstance(back, E.VerifyVerdict)
    assert isinstance(back.verdict, Verdict), "verdict 必须还原成 Verdict dataclass,不是 dict"
    assert back.verdict.status == "failed"
    assert back.verdict.verify_cmd == "pytest -q"
    assert back.verdict.attempts == 2


def test_verify_verdict_unverifiable_roundtrip_with_tampered():
    from argos.core.verify_gate import Verdict
    v = Verdict.unverifiable(detail="受保护文件被改", tampered=["a.py", "b.py"], attempts=1)
    back = E.deserialize_event(E.serialize_event(E.VerifyVerdict(verdict=v)))
    assert isinstance(back.verdict, Verdict)
    assert back.verdict.status == "unverifiable"
    assert back.verdict.tampered == ["a.py", "b.py"]


def test_hook_fired_in_kind_to_class():
    from argos.hooks.events import HookFired
    assert E._KIND_TO_CLASS.get("hook_fired") is HookFired


def test_hook_fired_serialize_roundtrip():
    from argos.hooks.events import HookFired
    ev = HookFired(
        event_name="PreToolUse", command="echo ok",
        success=True, returncode=0, elapsed_ms=130,
    )
    blob = E.serialize_event(ev)
    ev2 = E.deserialize_event(blob)
    assert isinstance(ev2, HookFired)
    assert ev2.event_name == "PreToolUse"
    assert ev2.command == "echo ok"
    assert ev2.success is True
    assert ev2.returncode == 0
    assert ev2.elapsed_ms == 130


# ── LSP(spec 2026-06-06 §10.1):LspServerEvent / LspDiagnosticEvent ─────────
def test_lsp_server_event_in_kind_to_class():
    from argos.lsp.events import LspServerEvent
    assert E._KIND_TO_CLASS.get("lsp_server_event") is LspServerEvent


def test_lsp_diagnostic_event_in_kind_to_class():
    from argos.lsp.events import LspDiagnosticEvent
    assert E._KIND_TO_CLASS.get("lsp_diagnostic_event") is LspDiagnosticEvent


def test_lsp_server_event_serialize_roundtrip():
    from argos.lsp.events import LspServerEvent
    ev = LspServerEvent(
        server_name="python", status="ready", command="pyright-langserver --stdio",
        exit_code=None, elapsed_ms=820, error=None, cwd="/ws", timestamp_ms=1234567,
    )
    blob = E.serialize_event(ev)
    ev2 = E.deserialize_event(blob)
    assert isinstance(ev2, LspServerEvent)
    assert ev2.server_name == "python"
    assert ev2.status == "ready"
    assert ev2.command == "pyright-langserver --stdio"
    assert ev2.elapsed_ms == 820
    assert ev2.exit_code is None
    assert ev2.error is None
    assert ev2.cwd == "/ws"
    assert ev2.timestamp_ms == 1234567


def test_lsp_diagnostic_event_serialize_roundtrip():
    from argos.lsp.events import LspDiagnosticEvent
    ev = LspDiagnosticEvent(
        server_name="python", uri="file:///a.py", count=3,
        severity_counts={"error": 2, "warning": 1},
        cached=False, cwd="/ws",
    )
    blob = E.serialize_event(ev)
    ev2 = E.deserialize_event(blob)
    assert isinstance(ev2, LspDiagnosticEvent)
    assert ev2.server_name == "python"
    assert ev2.uri == "file:///a.py"
    assert ev2.count == 3
    assert ev2.severity_counts == {"error": 2, "warning": 1}
    assert ev2.cached is False
    assert ev2.cwd == "/ws"


def test_lsp_event_kinds_in_event_kind_literal():
    args = set(E.EventKind.__args__)
    assert "lsp_server_event" in args
    assert "lsp_diagnostic_event" in args
