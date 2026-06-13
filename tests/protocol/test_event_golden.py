"""ABI 冻结测试:为每种 Event kind 构造代表实例,serialize_event 输出与
写死的期望 JSON dict 逐字段比对(防协议漂移)。

这不是 round-trip 测试 — 专门锁死序列化输出格式。

同时验证:
1. round-trip:serialize → deserialize 等值
2. 架构契约:argos/core/ 与 argos/protocol/ 源文件中不含 'tui.events' 字样
   (用文本扫描实现,防回归)
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

import argos
import argos.protocol.events as PE


# ── 辅助 ──────────────────────────────────────────────────────────────────────

def _round(ev):
    """serialize → deserialize 并断言类型相同、值相等。"""
    blob = PE.serialize_event(ev)
    back = PE.deserialize_event(blob)
    assert type(back) is type(ev), f"类型不匹配:{type(back)} != {type(ev)}"
    return back


def _golden(ev, expected_data: dict) -> None:
    """serialize 输出的 data 字段必须逐字段匹配 expected_data(ABI 冻结)。"""
    obj = json.loads(PE.serialize_event(ev))
    assert obj["kind"] == expected_data.get("_kind") or obj["kind"] == type(ev).kind
    actual_data = obj["data"]
    for key, val in expected_data.items():
        if key == "_kind":
            continue
        assert key in actual_data, f"字段 {key!r} 不在序列化输出中"
        assert actual_data[key] == val, (
            f"字段 {key!r} 值漂移: 期望 {val!r}, 实得 {actual_data[key]!r}"
        )


# ── TokenDelta ─────────────────────────────────────────────────────────────────

def test_token_delta_golden():
    ev = PE.TokenDelta(text="你好")
    _golden(ev, {"text": "你好"})


def test_token_delta_roundtrip():
    ev = PE.TokenDelta(text="hello world")
    back = _round(ev)
    assert back.text == ev.text


# ── CodeAction ────────────────────────────────────────────────────────────────

def test_code_action_golden():
    ev = PE.CodeAction(code="print(1)", step=0)
    _golden(ev, {"code": "print(1)", "step": 0})


def test_code_action_roundtrip():
    ev = PE.CodeAction(code="x=1+1", step=3)
    back = _round(ev)
    assert back.code == ev.code and back.step == ev.step


# ── CodeResult ────────────────────────────────────────────────────────────────

def test_code_result_golden():
    ev = PE.CodeResult(step=1, stdout="ok\n", value_repr="42", exc="", ok=True)
    _golden(ev, {"step": 1, "stdout": "ok\n", "value_repr": "42", "exc": "", "ok": True})


def test_code_result_roundtrip():
    ev = PE.CodeResult(step=2, stdout="", value_repr="", exc="ZeroDivisionError: /0", ok=False)
    back = _round(ev)
    assert back.ok is False and back.exc == "ZeroDivisionError: /0"


# ── FileDiff ──────────────────────────────────────────────────────────────────

def test_file_diff_golden():
    ev = PE.FileDiff(path="/a.py", added=3, removed=1, unified="@@ -1,1 +1,3 @@\n+x\n+y\n")
    _golden(ev, {"path": "/a.py", "added": 3, "removed": 1})


def test_file_diff_roundtrip():
    ev = PE.FileDiff(path="/b.py", added=0, removed=5, unified="")
    back = _round(ev)
    assert back.path == "/b.py" and back.removed == 5


# ── PhaseChange ───────────────────────────────────────────────────────────────

def test_phase_change_golden():
    ev = PE.PhaseChange(phase="act", actions=2)
    _golden(ev, {"phase": "act", "actions": 2})


def test_phase_change_roundtrip():
    for phase in ("plan", "act", "verify", "report"):
        ev = PE.PhaseChange(phase=phase, actions=0)
        back = _round(ev)
        assert back.phase == phase


# ── CostUpdate ────────────────────────────────────────────────────────────────

def test_cost_update_golden():
    ev = PE.CostUpdate(
        tokens_in=100, tokens_out=50, cost_usd=0.001,
        elapsed_s=2.5, cache_read=10, context_used=200, tier_name="sonnet",
    )
    _golden(ev, {
        "tokens_in": 100, "tokens_out": 50, "cost_usd": 0.001,
        "elapsed_s": 2.5, "cache_read": 10, "context_used": 200, "tier_name": "sonnet",
    })


def test_cost_update_none_cost_usd_golden():
    """cost_usd=None 诚实序列化为 null,不编造成本。"""
    ev = PE.CostUpdate(tokens_in=5, tokens_out=3, cost_usd=None, elapsed_s=1.0)
    obj = json.loads(PE.serialize_event(ev))
    assert obj["data"]["cost_usd"] is None


def test_cost_update_roundtrip():
    ev = PE.CostUpdate(tokens_in=0, tokens_out=0, cost_usd=None, elapsed_s=0.0)
    back = _round(ev)
    assert back.cost_usd is None


# ── ApprovalRequest ───────────────────────────────────────────────────────────

def test_approval_request_golden():
    ev = PE.ApprovalRequest(
        call_id="abc123def456", action="run_command",
        args={"command": "rm -rf /tmp/x"}, description="删除临时目录",
        risk="high", trigger="", secret_pattern=None,
    )
    _golden(ev, {
        "call_id": "abc123def456", "action": "run_command",
        "description": "删除临时目录", "risk": "high",
        "trigger": "", "secret_pattern": None,
    })


def test_approval_request_roundtrip():
    ev = PE.ApprovalRequest(
        call_id="deadbeef0011", action="write_file",
        args={"path": "/etc/hosts"}, description="改 hosts",
        risk="critical", trigger="hard rule: write /etc", secret_pattern=None,
    )
    back = _round(ev)
    assert back.call_id == ev.call_id and back.trigger == ev.trigger


# ── ApprovalResponse ──────────────────────────────────────────────────────────

def test_approval_response_golden():
    ev = PE.ApprovalResponse(call_id="abc123def456", decision="once")
    _golden(ev, {"call_id": "abc123def456", "decision": "once"})


def test_approval_response_roundtrip():
    for decision in ("deny", "once", "session", "always"):
        ev = PE.ApprovalResponse(call_id="x" * 12, decision=decision)
        back = _round(ev)
        assert back.decision == decision


# ── Escalation ────────────────────────────────────────────────────────────────

def test_escalation_golden():
    ev = PE.Escalation(reason="verify 三次失败", attempts=3, last_failure="exit 1")
    _golden(ev, {"reason": "verify 三次失败", "attempts": 3, "last_failure": "exit 1"})


def test_escalation_roundtrip():
    ev = PE.Escalation(reason="boom", attempts=1, last_failure="err")
    back = _round(ev)
    assert back.attempts == 1


# ── Error ─────────────────────────────────────────────────────────────────────

def test_error_golden():
    ev = PE.Error(message="something went wrong", chain=["ValueError: x", "RuntimeError: y"])
    _golden(ev, {"message": "something went wrong", "chain": ["ValueError: x", "RuntimeError: y"]})


def test_error_empty_chain_golden():
    ev = PE.Error(message="boom")
    _golden(ev, {"message": "boom", "chain": []})


def test_error_roundtrip():
    ev = PE.Error(message="oops", chain=["A", "B"])
    back = _round(ev)
    assert back.chain == ["A", "B"]


# ── PlanUpdate ────────────────────────────────────────────────────────────────

def test_plan_update_golden():
    todos = [{"content": "写测试", "status": "pending"}]
    ev = PE.PlanUpdate(todos=todos)
    _golden(ev, {"todos": todos})


def test_plan_update_roundtrip():
    ev = PE.PlanUpdate(todos=[])
    back = _round(ev)
    assert back.todos == []


# ── WorkflowProgress ──────────────────────────────────────────────────────────

def test_workflow_progress_golden():
    ev = PE.WorkflowProgress(stage_id="s1", agent_id="s1#0", phase="act", note="运行中")
    _golden(ev, {"stage_id": "s1", "agent_id": "s1#0", "phase": "act", "note": "运行中"})


def test_workflow_progress_roundtrip():
    ev = PE.WorkflowProgress(stage_id="r", agent_id="r#2", phase="verify")
    back = _round(ev)
    assert back.note == ""


# ── WorkflowProposed ──────────────────────────────────────────────────────────

def test_workflow_proposed_golden():
    ev = PE.WorkflowProposed(
        name="审计", description="并行审计", preview="阶段 r: fan_out", call_id="a" * 12,
    )
    _golden(ev, {"name": "审计", "description": "并行审计", "call_id": "a" * 12})


def test_workflow_proposed_roundtrip():
    ev = PE.WorkflowProposed(name="x", description="d", preview="p", call_id="b" * 12)
    back = _round(ev)
    assert back.name == "x"


# ── WorkflowDone ──────────────────────────────────────────────────────────────

def test_workflow_done_golden():
    ev = PE.WorkflowDone(name="审计", synthesis="结论", notes=("cap 截断",))
    _golden(ev, {"name": "审计", "synthesis": "结论"})


def test_workflow_done_notes_tuple_roundtrip():
    """JSON 不分 tuple/list:round-trip 必须还原回 tuple。"""
    ev = PE.WorkflowDone(name="x", synthesis="y", notes=("a", "b"))
    back = _round(ev)
    assert isinstance(back.notes, tuple)
    assert back.notes == ("a", "b")


def test_workflow_done_empty_notes_roundtrip():
    ev = PE.WorkflowDone(name="x", synthesis="y")
    back = _round(ev)
    assert back.notes == () and isinstance(back.notes, tuple)


# ── PlanRendered ──────────────────────────────────────────────────────────────

def test_plan_rendered_golden():
    ev = PE.PlanRendered(plan_md="# 计划\n- 步骤 1")
    _golden(ev, {"plan_md": "# 计划\n- 步骤 1"})


def test_plan_rendered_roundtrip():
    ev = PE.PlanRendered(plan_md="**bold**")
    back = _round(ev)
    assert back.plan_md == "**bold**"


# ── PlanDecisionRequest ───────────────────────────────────────────────────────

def test_plan_decision_request_golden():
    ev = PE.PlanDecisionRequest(call_id="aabbcc112233", plan_md="# Plan\n- step 1")
    _golden(ev, {"call_id": "aabbcc112233", "plan_md": "# Plan\n- step 1"})


def test_plan_decision_request_roundtrip():
    ev = PE.PlanDecisionRequest(call_id="deadbeef0011", plan_md="**plan**")
    back = _round(ev)
    assert back.call_id == ev.call_id and back.plan_md == ev.plan_md


# ── MemoryRecallEvent ─────────────────────────────────────────────────────────

def test_memory_recall_golden():
    hits = ["写测试 → passed（goal 相似度 0.9）", "修 bug → failed（goal 相似度 0.8）"]
    ev = PE.MemoryRecallEvent(hits=hits)
    _golden(ev, {"hits": hits})


def test_memory_recall_empty_golden():
    """hits=[] 诚实序列化为空列表(无命中不编造)。"""
    ev = PE.MemoryRecallEvent()
    obj = json.loads(PE.serialize_event(ev))
    assert obj["data"]["hits"] == []


def test_memory_recall_roundtrip():
    ev = PE.MemoryRecallEvent(hits=["goal1 → passed（reason）"])
    back = _round(ev)
    assert back.hits == ev.hits


# ── CompactedEvent ────────────────────────────────────────────────────────────

def test_compacted_event_golden():
    ev = PE.CompactedEvent(before=8000, after=3000, reduction_pct=0.625,
                           triggered_by="proactive", session_id="s1")
    _golden(ev, {
        "before": 8000, "after": 3000, "reduction_pct": 0.625,
        "triggered_by": "proactive", "session_id": "s1",
    })


def test_compacted_event_roundtrip():
    ev = PE.CompactedEvent(before=100, after=50, reduction_pct=0.5,
                           triggered_by="error", session_id="")
    back = _round(ev)
    assert back.triggered_by == "error"


# ── PrunedEvent ───────────────────────────────────────────────────────────────

def test_pruned_event_golden():
    ev = PE.PrunedEvent(before=5000, after=4000, removed=3,
                        reduction_pct=0.2, aggressiveness=0.5, session_id="sess1")
    _golden(ev, {
        "before": 5000, "after": 4000, "removed": 3,
        "reduction_pct": 0.2, "aggressiveness": 0.5, "session_id": "sess1",
    })


def test_pruned_event_roundtrip():
    ev = PE.PrunedEvent(before=200, after=180, removed=1,
                        reduction_pct=0.1, aggressiveness=0.3)
    back = _round(ev)
    assert back.session_id == ""


# ── HookFired ─────────────────────────────────────────────────────────────────

def test_hook_fired_golden():
    from argos.hooks.events import HookFired
    ev = HookFired(
        event_name="PreToolUse", command="echo ok",
        success=True, returncode=0, elapsed_ms=42,
    )
    _golden(ev, {
        "event_name": "PreToolUse", "command": "echo ok",
        "success": True, "returncode": 0, "elapsed_ms": 42,
    })


def test_hook_fired_roundtrip():
    from argos.hooks.events import HookFired
    ev = HookFired(
        event_name="PostToolUse", command="black .",
        success=False, returncode=1, elapsed_ms=100,
        timed_out=False, not_found=False,
    )
    back = _round(ev)
    assert back.returncode == 1


# ── LspServerEvent ────────────────────────────────────────────────────────────

def test_lsp_server_event_golden():
    from argos.lsp.events import LspServerEvent
    ev = LspServerEvent(
        server_name="python", status="ready",
        command="pyright --stdio", exit_code=None,
        elapsed_ms=500, cwd="/ws", timestamp_ms=999,
    )
    _golden(ev, {
        "server_name": "python", "status": "ready",
        "elapsed_ms": 500, "cwd": "/ws",
    })


def test_lsp_server_event_roundtrip():
    from argos.lsp.events import LspServerEvent
    ev = LspServerEvent(server_name="ts", status="crash", exit_code=1, elapsed_ms=0)
    back = _round(ev)
    assert back.status == "crash" and back.exit_code == 1


# ── LspDiagnosticEvent ────────────────────────────────────────────────────────

def test_lsp_diagnostic_event_golden():
    from argos.lsp.events import LspDiagnosticEvent
    ev = LspDiagnosticEvent(
        server_name="python", uri="file:///a.py", count=2,
        severity_counts={"error": 1, "warning": 1}, cached=False, cwd="/ws",
    )
    _golden(ev, {
        "server_name": "python", "uri": "file:///a.py",
        "count": 2, "cached": False,
    })


def test_lsp_diagnostic_event_roundtrip():
    from argos.lsp.events import LspDiagnosticEvent
    ev = LspDiagnosticEvent(server_name="ts", uri="file:///b.ts", count=0,
                            severity_counts={}, cached=True)
    back = _round(ev)
    assert back.cached is True


# ── SkillRunStart ─────────────────────────────────────────────────────────────

def test_skill_run_start_golden():
    from argos.skills_runtime.events import SkillRunStart
    ev = SkillRunStart(skill_name="security-review", args={"path": "."}, cwd="/ws")
    _golden(ev, {"skill_name": "security-review", "cwd": "/ws"})


def test_skill_run_start_roundtrip():
    from argos.skills_runtime.events import SkillRunStart
    ev = SkillRunStart(skill_name="simplify", args={}, cwd="", timestamp_ms=0)
    back = _round(ev)
    assert back.skill_name == "simplify"


# ── SkillRunEnd ───────────────────────────────────────────────────────────────

def test_skill_run_end_golden():
    from argos.skills_runtime.events import SkillRunEnd
    ev = SkillRunEnd(
        skill_name="security-review", verdict="passed",
        duration_ms=1234, finding_count=0, error_count=0, cwd="/ws",
    )
    _golden(ev, {
        "skill_name": "security-review", "verdict": "passed",
        "duration_ms": 1234, "finding_count": 0, "error_count": 0,
    })


def test_skill_run_end_roundtrip():
    from argos.skills_runtime.events import SkillRunEnd
    ev = SkillRunEnd(skill_name="x", verdict="failed",
                     duration_ms=50, finding_count=3, error_count=1)
    back = _round(ev)
    assert back.verdict == "failed" and back.finding_count == 3


# ── ToolReceipt (嵌套 dataclass) ──────────────────────────────────────────────

def test_tool_receipt_roundtrip_keeps_receipt_dataclass():
    from argos.tools.receipts import Receipt, ReceiptSigner
    signer = ReceiptSigner(key=b"golden-test")
    rec = signer.sign(action="write_file", args={"path": "/x.py"}, result="ok", exit_code=0)
    ev = PE.ToolReceipt(receipt=rec)
    back = _round(ev)
    assert isinstance(back.receipt, Receipt)
    assert back.receipt.action == "write_file"
    assert signer.verify(back.receipt) is True


# ── VerifyVerdict (嵌套 dataclass) ────────────────────────────────────────────

def test_verify_verdict_passed_roundtrip():
    from argos.core.verify_gate import Verdict
    v = Verdict.passed(detail="all green", verify_cmd="pytest -q", attempts=1)
    ev = PE.VerifyVerdict(verdict=v)
    back = _round(ev)
    from argos.core.verify_gate import Verdict as _V
    assert isinstance(back.verdict, _V)
    assert back.verdict.status == "passed"


def test_verify_verdict_unverifiable_roundtrip():
    from argos.core.verify_gate import Verdict
    v = Verdict.unverifiable(detail="no cmd", tampered=[], attempts=0)
    ev = PE.VerifyVerdict(verdict=v)
    back = _round(ev)
    assert back.verdict.status == "unverifiable"


# ── ProactiveSuggestionEvent ─────────────────────────────────────────────────

def test_proactive_suggestion_golden():
    """P5b §9:conductor 主动建议事件黄金测试(ABI 冻结)。"""
    ev = PE.ProactiveSuggestionEvent(
        suggestion_id="abc123def456",
        order_id="order001",
        goal="检查昨天的日志",
        reason_human="定时触发（09:00）：每天早上检查日志",
        suggested_at=1700000000.0,
        requires_confirmation=True,
    )
    _golden(ev, {
        "suggestion_id": "abc123def456",
        "order_id": "order001",
        "goal": "检查昨天的日志",
        "reason_human": "定时触发（09:00）：每天早上检查日志",
        "suggested_at": 1700000000.0,
        "requires_confirmation": True,
        "action": "run",
    })


def test_proactive_suggestion_roundtrip():
    """ProactiveSuggestionEvent 序列化 → 反序列化等值。"""
    ev = PE.ProactiveSuggestionEvent(
        suggestion_id="deadbeef0011",
        order_id="ord_x",
        goal="整理日志",
        reason_human="文件变化触发（requirements.txt）：依赖更新时检查",
        suggested_at=1700001234.5,
        requires_confirmation=True,
    )
    back = _round(ev)
    assert back.suggestion_id == ev.suggestion_id
    assert back.order_id == ev.order_id
    assert back.requires_confirmation is True
    assert back.action == "run"


def test_proactive_suggestion_action_dream_roundtrip():
    """ProactiveSuggestionEvent action='dream' 序列化 → 反序列化往返。"""
    ev = PE.ProactiveSuggestionEvent(
        suggestion_id="deadbeef0022",
        order_id="ord_dream",
        goal="夜间整合记忆",
        reason_human="定时触发（03:00）：夜间整合",
        suggested_at=1700002000.0,
        requires_confirmation=True,
        action="dream",
    )
    back = _round(ev)
    assert back.action == "dream"
    assert back.suggestion_id == ev.suggestion_id


def test_proactive_suggestion_requires_confirmation_always_true():
    """requires_confirmation 序列化输出必须是 True（协议级不可覆盖）。"""
    ev = PE.ProactiveSuggestionEvent(
        suggestion_id="s1",
        order_id="o1",
        goal="g",
        reason_human="r",
        suggested_at=1.0,
        requires_confirmation=True,
    )
    obj = __import__("json").loads(PE.serialize_event(ev))
    assert obj["data"]["requires_confirmation"] is True


# ── DreamProgressEvent ────────────────────────────────────────────────────────

def test_dream_progress_golden():
    """Dream 夜间整合进度事件黄金测试(ABI 冻结)。"""
    ev = PE.DreamProgressEvent(stage="cluster", detail="3 units", ts=1700000000.0)
    _golden(ev, {"stage": "cluster", "detail": "3 units", "ts": 1700000000.0})


def test_dream_progress_roundtrip():
    """DreamProgressEvent 序列化 → 反序列化等值。"""
    ev = PE.DreamProgressEvent(stage="scan", detail="", ts=1700001234.5)
    back = _round(ev)
    assert back.stage == "scan" and back.detail == "" and back.ts == 1700001234.5


# ── DreamReportEvent ──────────────────────────────────────────────────────────

def test_dream_report_golden():
    """Dream 整合结果汇总事件黄金测试(诚实计数,ABI 冻结)。"""
    ev = PE.DreamReportEvent(
        units_total=3, promoted=1, rejected=1, skipped=1,
        memory_merged=2, memory_archived=5,
        report_path="/home/u/.argos/dreams/2026-06-13.jsonl", ts=1700000000.0,
    )
    _golden(ev, {
        "units_total": 3, "promoted": 1, "rejected": 1, "skipped": 1,
        "memory_merged": 2, "memory_archived": 5,
        "report_path": "/home/u/.argos/dreams/2026-06-13.jsonl", "ts": 1700000000.0,
    })


def test_dream_report_roundtrip():
    """DreamReportEvent 序列化 → 反序列化等值。"""
    ev = PE.DreamReportEvent(
        units_total=0, promoted=0, rejected=0, skipped=0,
        memory_merged=0, memory_archived=0, report_path="", ts=0.0,
    )
    back = _round(ev)
    assert back.units_total == 0 and back.report_path == ""


# ── _KIND_TO_CLASS 完整性 ────────────────────────────────────────────────────

def test_all_kinds_in_kind_to_class():
    """所有 EventKind 值都必须注册在 _KIND_TO_CLASS 中。"""
    all_kinds = set(PE.EventKind.__args__)
    registered = set(PE._KIND_TO_CLASS.keys())
    missing = all_kinds - registered
    assert not missing, f"未注册的 kind:{missing}"


# ── 架构契约:core/ 与 protocol/ 中不含 tui.events 字样 ──────────────────────

def _scan_for_tui_events_import(dirpath: str, *, skip_dirs: tuple[str, ...] = ()) -> list[tuple[str, int, str]]:
    """扫描目录下所有 .py 文件,收集包含 'tui.events' 字样的非注释行。

    v6 P0 收尾后 EventBus 已搬入 protocol/events.py,生产代码(tui/ 之外)
    不再有任何从 tui.events import 的正当理由 —— 零豁免。
    """
    hits: list[tuple[str, int, str]] = []
    for root, _dirs, files in os.walk(dirpath):
        if "__pycache__" in root:
            continue
        if any(os.sep + d in root or root.endswith(os.sep + d) for d in skip_dirs):
            continue
        for fn in files:
            if not fn.endswith(".py"):
                continue
            p = os.path.join(root, fn)
            try:
                lines = Path(p).read_text(encoding="utf-8").splitlines()
            except (OSError, UnicodeDecodeError):
                continue
            for lineno, line in enumerate(lines, 1):
                stripped = line.strip()
                # 跳过注释行
                if stripped.startswith("#"):
                    continue
                if "tui.events" not in line:
                    continue
                hits.append((p, lineno, line.rstrip()))
    return hits


def test_production_no_tui_events_import():
    """argos/ 全树(tui/ 自身除外)零 tui.events 引用(防回归,零豁免)。

    tui/ 包内部(app.py/fakeloop.py 等)允许走自家 shim;其余一切生产代码
    必须 import argos.protocol.events。
    """
    root = Path(argos.__file__).parent
    hits = _scan_for_tui_events_import(str(root), skip_dirs=("tui",))
    assert not hits, (
        "生产代码中发现 tui.events 引用(应改用 protocol.events):\n"
        + "\n".join(f"  {p}:{n}  {line}" for p, n, line in hits)
    )


def test_protocol_no_tui_events_import():
    """argos/protocol/ 中不应有 tui.events import(防循环依赖)。"""
    root = Path(argos.__file__).parent / "protocol"
    hits = _scan_for_tui_events_import(str(root))
    assert not hits, (
        "protocol/ 中发现 tui.events import(循环依赖风险):\n"
        + "\n".join(f"  {p}:{n}  {line}" for p, n, line in hits)
    )
