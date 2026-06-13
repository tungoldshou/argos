#!/usr/bin/env python3
"""Export golden test vectors for the TypeScript ACP SDK.

Mirrors (but does NOT import from) tests/protocol/test_event_golden.py — the two
literal sets are hand-maintained in parallel and can drift independently.  The
serialized bytes are genuine Python serialize_event() output; re-running this
script against the same events produces a zero-diff regeneration, but single-
sourcing from the test module is not implemented.  When protocol/events.py has a
breaking change, update BOTH this file and test_event_golden.py.

Writes desktop/sdk/test/vectors.json — a JSON array of objects with shape:

  {
    "kind":         "<EventKind>",
    "serialized":   "<JSON string from serialize_event()>",
    "expected_data": { <field: value, ...> }
  }

The vectors.json file is committed to the repo so the TS test suite can run
without Python.  This script only needs to be re-run when the Python event
dataclasses change.

Usage (from repo root):
  uv run --no-sync python desktop/sdk/scripts/export_vectors.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Ensure argos is importable when running from repo root.
repo_root = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(repo_root))

import argos.protocol.events as PE  # noqa: E402


def _build_vectors() -> list[dict]:
    vectors: list[dict] = []

    def _v(ev, expected_data: dict) -> None:
        serialized = PE.serialize_event(ev)
        obj = json.loads(serialized)
        vectors.append({
            "kind": obj["kind"],
            "serialized": serialized,
            "expected_data": expected_data,
        })

    # ── TokenDelta ─────────────────────────────────────────────────────────
    _v(PE.TokenDelta(text="你好"), {"text": "你好"})

    # ── CodeAction ─────────────────────────────────────────────────────────
    _v(PE.CodeAction(code="print(1)", step=0), {"code": "print(1)", "step": 0})

    # ── CodeResult ─────────────────────────────────────────────────────────
    _v(
        PE.CodeResult(step=1, stdout="ok\n", value_repr="42", exc="", ok=True),
        {"step": 1, "stdout": "ok\n", "value_repr": "42", "exc": "", "ok": True},
    )

    # ── FileDiff ────────────────────────────────────────────────────────────
    _v(
        PE.FileDiff(path="/a.py", added=3, removed=1, unified="@@ -1 +1,3 @@\n"),
        {"path": "/a.py", "added": 3, "removed": 1},
    )

    # ── PhaseChange ────────────────────────────────────────────────────────
    _v(PE.PhaseChange(phase="act", actions=2), {"phase": "act", "actions": 2})

    # ── CostUpdate ─────────────────────────────────────────────────────────
    _v(
        PE.CostUpdate(
            tokens_in=100, tokens_out=50, cost_usd=0.001,
            elapsed_s=2.5, cache_read=10, context_used=200, tier_name="sonnet",
        ),
        {
            "tokens_in": 100, "tokens_out": 50, "cost_usd": 0.001,
            "elapsed_s": 2.5, "cache_read": 10, "context_used": 200, "tier_name": "sonnet",
        },
    )

    # CostUpdate with cost_usd=None (honest null, not fabricated)
    _v(
        PE.CostUpdate(tokens_in=5, tokens_out=3, cost_usd=None, elapsed_s=1.0),
        {"tokens_in": 5, "tokens_out": 3, "cost_usd": None, "elapsed_s": 1.0},
    )

    # ── ApprovalRequest ────────────────────────────────────────────────────
    _v(
        PE.ApprovalRequest(
            call_id="abc123def456", action="run_command",
            args={"command": "rm -rf /tmp/x"}, description="删除临时目录",
            risk="high", trigger="", secret_pattern=None,
        ),
        {
            "call_id": "abc123def456", "action": "run_command",
            "description": "删除临时目录", "risk": "high",
            "trigger": "", "secret_pattern": None,
        },
    )

    # ── ApprovalResponse ────────────────────────────────────────────────────
    _v(
        PE.ApprovalResponse(call_id="abc123def456", decision="once"),
        {"call_id": "abc123def456", "decision": "once"},
    )

    # ── Escalation ─────────────────────────────────────────────────────────
    _v(
        PE.Escalation(reason="verify 三次失败", attempts=3, last_failure="exit 1"),
        {"reason": "verify 三次失败", "attempts": 3, "last_failure": "exit 1"},
    )

    # ── Error ──────────────────────────────────────────────────────────────
    _v(
        PE.Error(message="something went wrong", chain=["ValueError: x", "RuntimeError: y"]),
        {"message": "something went wrong", "chain": ["ValueError: x", "RuntimeError: y"]},
    )

    # ── PlanUpdate ─────────────────────────────────────────────────────────
    todos = [{"content": "写测试", "status": "pending"}]
    _v(PE.PlanUpdate(todos=todos), {"todos": todos})

    # ── WorkflowProgress ───────────────────────────────────────────────────
    _v(
        PE.WorkflowProgress(stage_id="s1", agent_id="s1#0", phase="act", note="运行中"),
        {"stage_id": "s1", "agent_id": "s1#0", "phase": "act", "note": "运行中"},
    )

    # ── WorkflowProposed ───────────────────────────────────────────────────
    _v(
        PE.WorkflowProposed(
            name="审计", description="并行审计", preview="阶段 r: fan_out",
            call_id="a" * 12,
        ),
        {"name": "审计", "description": "并行审计", "call_id": "a" * 12},
    )

    # ── WorkflowDone ────────────────────────────────────────────────────────
    _v(
        PE.WorkflowDone(name="审计", synthesis="结论", notes=("cap 截断",)),
        {"name": "审计", "synthesis": "结论"},
    )

    # ── PlanRendered ────────────────────────────────────────────────────────
    _v(
        PE.PlanRendered(plan_md="# 计划\n- 步骤 1"),
        {"plan_md": "# 计划\n- 步骤 1"},
    )

    # ── PlanDecisionRequest ────────────────────────────────────────────────
    _v(
        PE.PlanDecisionRequest(call_id="aabbcc112233", plan_md="# Plan\n- step 1"),
        {"call_id": "aabbcc112233", "plan_md": "# Plan\n- step 1"},
    )

    # ── MemoryRecallEvent ──────────────────────────────────────────────────
    hits = ["写测试 → passed（goal 相似度 0.9）"]
    _v(PE.MemoryRecallEvent(hits=hits), {"hits": hits})

    # ── CompactedEvent ─────────────────────────────────────────────────────
    _v(
        PE.CompactedEvent(
            before=8000, after=3000, reduction_pct=0.625,
            triggered_by="proactive", session_id="s1",
        ),
        {"before": 8000, "after": 3000, "reduction_pct": 0.625,
         "triggered_by": "proactive", "session_id": "s1"},
    )

    # ── PrunedEvent ────────────────────────────────────────────────────────
    _v(
        PE.PrunedEvent(
            before=5000, after=4000, removed=3,
            reduction_pct=0.2, aggressiveness=0.5, session_id="sess1",
        ),
        {"before": 5000, "after": 4000, "removed": 3,
         "reduction_pct": 0.2, "aggressiveness": 0.5, "session_id": "sess1"},
    )

    # ── HookFired ──────────────────────────────────────────────────────────
    from argos.hooks.events import HookFired
    _v(
        HookFired(
            event_name="PreToolUse", command="echo ok",
            success=True, returncode=0, elapsed_ms=42,
        ),
        {"event_name": "PreToolUse", "command": "echo ok",
         "success": True, "returncode": 0, "elapsed_ms": 42},
    )

    # ── LspServerEvent ─────────────────────────────────────────────────────
    from argos.lsp.events import LspServerEvent
    _v(
        LspServerEvent(
            server_name="python", status="ready",
            command="pyright --stdio", exit_code=None,
            elapsed_ms=500, cwd="/ws", timestamp_ms=999,
        ),
        {"server_name": "python", "status": "ready", "elapsed_ms": 500, "cwd": "/ws"},
    )

    # ── LspDiagnosticEvent ─────────────────────────────────────────────────
    from argos.lsp.events import LspDiagnosticEvent
    _v(
        LspDiagnosticEvent(
            server_name="python", uri="file:///a.py", count=2,
            severity_counts={"error": 1, "warning": 1}, cached=False, cwd="/ws",
        ),
        {"server_name": "python", "uri": "file:///a.py", "count": 2, "cached": False},
    )

    # ── SkillRunStart ──────────────────────────────────────────────────────
    from argos.skills_runtime.events import SkillRunStart
    _v(
        SkillRunStart(skill_name="security-review", args={"path": "."}, cwd="/ws"),
        {"skill_name": "security-review", "cwd": "/ws"},
    )

    # ── SkillRunEnd ────────────────────────────────────────────────────────
    from argos.skills_runtime.events import SkillRunEnd
    _v(
        SkillRunEnd(
            skill_name="security-review", verdict="passed",
            duration_ms=1234, finding_count=0, error_count=0, cwd="/ws",
        ),
        {"skill_name": "security-review", "verdict": "passed",
         "duration_ms": 1234, "finding_count": 0, "error_count": 0},
    )

    # ── LedgerEntryEvent ───────────────────────────────────────────────────
    _v(
        PE.LedgerEntryEvent(
            ts=1700000000.0, run_id="run123", seq=1,
            action="write_file", summary_human="创建了 README.md",
            risk="low", reversible="yes", undo_state="available",
        ),
        {
            "ts": 1700000000.0, "run_id": "run123", "seq": 1,
            "action": "write_file", "summary_human": "创建了 README.md",
            "risk": "low", "reversible": "yes", "undo_state": "available",
        },
    )

    # ── ToolReceipt ────────────────────────────────────────────────────────
    # Pins the nested Receipt dataclass wire shape (§6.2 HMAC receipt).
    from argos.tools.receipts import Receipt as _Receipt
    _receipt = _Receipt(
        action="write_file",
        args_hash="a" * 64,
        result_hash="b" * 64,
        exit_code=0,
        ts=1700000000.0,
        nonce="c" * 32,
        sig="d" * 64,
    )
    _v(
        PE.ToolReceipt(receipt=_receipt),
        {
            "receipt": {
                "action": "write_file",
                "args_hash": "a" * 64,
                "result_hash": "b" * 64,
                "exit_code": 0,
                "ts": 1700000000.0,
                "nonce": "c" * 32,
                "sig": "d" * 64,
            },
        },
    )

    # ── VerifyVerdict (all three states) ───────────────────────────────────
    # Pins the nested Verdict dataclass wire shape and the three-state ABI.
    # "unverifiable" must round-trip as "unverifiable" — never "passed"/"failed".
    from argos.core.types import Verdict as _Verdict
    _v(
        PE.VerifyVerdict(verdict=_Verdict.passed(
            detail="exit 0", verify_cmd="pytest -x tests/", attempts=1,
        )),
        {
            "verdict": {
                "status": "passed",
                "detail": "exit 0",
                "verify_cmd": "pytest -x tests/",
                "attempts": 1,
                "tampered": [],
                "self_verified": False,
            },
        },
    )
    _v(
        PE.VerifyVerdict(verdict=_Verdict.failed(
            detail="exit 1", verify_cmd="pytest -x tests/", attempts=2,
        )),
        {
            "verdict": {
                "status": "failed",
                "detail": "exit 1",
                "verify_cmd": "pytest -x tests/",
                "attempts": 2,
                "tampered": [],
                "self_verified": False,
            },
        },
    )
    _v(
        PE.VerifyVerdict(verdict=_Verdict.unverifiable(
            detail="trivial cmd rejected", tampered=[], attempts=1,
        )),
        {
            "verdict": {
                "status": "unverifiable",
                "detail": "trivial cmd rejected",
                "verify_cmd": None,
                "attempts": 1,
                "tampered": [],
                "self_verified": False,
            },
        },
    )

    # ── IntentConfirmRequest ────────────────────────────────────────────────
    _v(
        PE.IntentConfirmRequest(
            call_id="aabbcc112233",
            confirmation_text="我理解你要删除 build 文件夹，对吗？",
            risk_flags=("irreversible",),
            card_json={"goal": "删除 build 文件夹", "risk_flags": ["irreversible"]},
        ),
        {
            "call_id": "aabbcc112233",
            "confirmation_text": "我理解你要删除 build 文件夹，对吗？",
            "risk_flags": ["irreversible"],
        },
    )

    # ── IntentConfirmResponse ──────────────────────────────────────────────
    _v(
        PE.IntentConfirmResponse(call_id="aabbcc112233", confirmed=True, revised_goal=None),
        {"call_id": "aabbcc112233", "confirmed": True, "revised_goal": None},
    )

    # ── ProactiveSuggestionEvent ────────────────────────────────────────────
    _v(
        PE.ProactiveSuggestionEvent(
            suggestion_id="abc123def456",
            order_id="order001",
            goal="检查昨天的日志",
            reason_human="定时触发（09:00）：每天早上检查日志",
            suggested_at=1700000000.0,
            requires_confirmation=True,
        ),
        {
            "suggestion_id": "abc123def456",
            "order_id": "order001",
            "goal": "检查昨天的日志",
            "reason_human": "定时触发（09:00）：每天早上检查日志",
            "suggested_at": 1700000000.0,
            "requires_confirmation": True,
            "action": "run",
        },
    )

    # ── ComputerActionEvent ─────────────────────────────────────────────────
    _v(
        PE.ComputerActionEvent(
            kind_action="click",
            x=100,
            y=200,
            text_preview="",
            ok=True,
            detail="点击成功",
            artifact_path=None,
        ),
        {
            "kind_action": "click",
            "x": 100,
            "y": 200,
            "text_preview": "",
            "ok": True,
            "detail": "点击成功",
            "artifact_path": None,
        },
    )

    return vectors


def main() -> None:
    vectors = _build_vectors()
    out = Path(__file__).resolve().parents[1] / "test" / "vectors.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(vectors, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {len(vectors)} vectors → {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
