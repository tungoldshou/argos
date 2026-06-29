"""Task 3.2: inline run path emits signed LedgerEntry to LedgerStore.

Verifies that an AgentLoop wired with a LedgerStore produces persisted entries
(ToolReceipt → tool_receipt entry, FileDiff → file_diff entry) without mocks
that bypass the real LedgerStore.append logic.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from argos.core.loop import AgentLoop, LoopConfig
from argos.ledger.store import LedgerStore
from argos.protocol.events import EventBus, ToolReceipt, FileDiff
from argos.sandbox.backend import ExecResult
from argos.tools.receipts import ReceiptSigner


# ---------------------------------------------------------------------------
# Minimal fakes (same pattern as tests/test_loop_stagnation.py)
# ---------------------------------------------------------------------------

class _DoneModel:
    """Emits nothing (no code block) → loop terminates after plan phase."""
    async def stream(self, messages, *, system, system_dynamic=None):
        for ch in "Task complete.":  # no ```python block → no act iteration
            yield ch


class _OkSandbox:
    def spawn(self, *, workspace, namespace, allow_workflow=True, read_only=False): ...
    def exec_code(self, code):
        return ExecResult(stdout="ok", value_repr="", exc="")
    def close(self): ...


class _NullVerifier:
    def verify(self, verify_cmd, *, attempts=1):
        from argos.core.verify_gate import Verdict
        return Verdict.unverifiable(detail="no verifier",
                                    verify_cmd=verify_cmd, attempts=attempts)


class _FakeStore:
    def append_event(self, sid, ev): ...
    def append_message(self, sid, **kw): return "m0"
    def get_messages(self, sid): return []
    def ensure_session(self, *a, **kw): ...
    def compact_messages(self, *a, **kw): ...


def _make_loop(ledger_store: LedgerStore) -> AgentLoop:
    return AgentLoop(
        store=_FakeStore(), bus=EventBus(), sandbox=_OkSandbox(),
        broker=None, model=_DoneModel(), verifier=_NullVerifier(),
        config=LoopConfig(verify_cmd=None, max_rounds=1, max_steps=5),
        ledger_store=ledger_store,
    )


# ---------------------------------------------------------------------------
# Helpers: inject events directly (mirror how loop internals yield them)
# ---------------------------------------------------------------------------

async def _collect(loop: AgentLoop, goal: str = "test goal",
                   session_id: str = "run-inline-01") -> list:
    return [ev async for ev in loop.run(goal, session_id)]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestInlineLedgerToolReceipt:
    """ToolReceipt yielded during inline run → LedgerEntry on disk."""

    def test_tool_receipt_appends_ledger_entry(self, tmp_path: Path):
        """AgentLoop with ledger_store wired: a ToolReceipt event produces a persisted entry."""
        store = LedgerStore(tmp_path)
        loop = _make_loop(store)

        # Inject a ToolReceipt directly via _inline_maybe_append_ledger (unit path)
        signer = ReceiptSigner(key=b"test-inline-key-32bytes-padded!!")
        receipt = signer.sign(action="write_file", args={"path": "x.py"},
                              result="ok", exit_code=0)
        ev = ToolReceipt(receipt=receipt)
        loop._inline_maybe_append_ledger(ev, "run-inline-01")

        entries = store.replay("run-inline-01")
        assert len(entries) == 1, f"expected 1 ledger entry, got {len(entries)}"
        e = entries[0]
        assert e.action == "write_file"
        assert e.run_id == "run-inline-01"
        assert e.seq == 1
        # sig is real (from ReceiptSigner.sign), not faked
        assert e.receipt_sig, "receipt_sig must be non-empty (real HMAC signature)"

    def test_multiple_receipts_increment_seq(self, tmp_path: Path):
        store = LedgerStore(tmp_path)
        loop = _make_loop(store)
        signer = ReceiptSigner(key=b"test-inline-key-32bytes-padded!!")

        for action in ("read_file", "write_file", "run_shell"):
            r = signer.sign(action=action, args={}, result="ok", exit_code=0)
            loop._inline_maybe_append_ledger(ToolReceipt(receipt=r), "run-inline-02")

        entries = store.replay("run-inline-02")
        assert len(entries) == 3
        assert [e.seq for e in entries] == [1, 2, 3]
        assert [e.action for e in entries] == ["read_file", "write_file", "run_shell"]

    def test_entry_has_valid_signature_prefix(self, tmp_path: Path):
        """receipt_sig is truncated real HMAC (first 16 chars of hex sig)."""
        store = LedgerStore(tmp_path)
        loop = _make_loop(store)
        signer = ReceiptSigner(key=b"test-inline-key-32bytes-padded!!")
        receipt = signer.sign(action="web_fetch", args={}, result="ok", exit_code=0)
        loop._inline_maybe_append_ledger(ToolReceipt(receipt=receipt), "run-sig-check")

        entries = store.replay("run-sig-check")
        e = entries[0]
        # Full sig from receipt — entry stores first 16 chars
        full_sig = receipt.sig or ""
        assert e.receipt_sig == full_sig[:16], (
            f"receipt_sig mismatch: entry has {e.receipt_sig!r}, "
            f"expected first 16 of {full_sig!r}"
        )


class TestInlineLedgerFileDiff:
    """FileDiff yielded during inline run → LedgerEntry on disk."""

    def test_file_diff_appends_ledger_entry(self, tmp_path: Path):
        store = LedgerStore(tmp_path)
        loop = _make_loop(store)

        ev = FileDiff(path="src/foo.py", added=10, removed=3, unified="@@...")
        loop._inline_maybe_append_ledger(ev, "run-file-diff")

        entries = store.replay("run-file-diff")
        assert len(entries) == 1
        e = entries[0]
        assert e.action == "file_diff"
        assert e.run_id == "run-file-diff"
        assert "foo.py" in e.summary_human
        assert "+10" in e.summary_human
        assert "-3" in e.summary_human

    def test_file_diff_reversible_unknown_without_snapshot(self, tmp_path: Path):
        """inline path has no snapshot → reversible=unknown, undo_state=impossible."""
        store = LedgerStore(tmp_path)
        loop = _make_loop(store)
        ev = FileDiff(path="a.py", added=1, removed=0, unified="")
        loop._inline_maybe_append_ledger(ev, "run-fd-rev")

        entries = store.replay("run-fd-rev")
        assert entries[0].reversible == "unknown"
        assert entries[0].undo_state == "impossible"

    def test_file_diff_no_entry_on_empty_path(self, tmp_path: Path):
        """FileDiff with empty path is silently skipped (no crash, no entry)."""
        store = LedgerStore(tmp_path)
        loop = _make_loop(store)
        ev = FileDiff(path="", added=0, removed=0, unified="")
        loop._inline_maybe_append_ledger(ev, "run-fd-empty")
        assert store.replay("run-fd-empty") == []


class TestInlineLedgerEndToEnd:
    """Integration: AgentLoop.run() passes events through _inline_maybe_append_ledger."""

    @pytest.mark.asyncio
    async def test_run_wires_ledger_store(self, tmp_path: Path):
        """Full run() call with a ledger_store; check the store receives calls.

        Uses a model that emits no code block (instant completion) so we don't
        need a real sandbox execution. The test verifies the wiring is correct —
        a real ToolReceipt would need a real broker+signer, which is integration-level.
        We confirm: (a) run completes without error, (b) ledger_store is attached.
        """
        store = LedgerStore(tmp_path)
        loop = _make_loop(store)
        events = await _collect(loop, session_id="run-e2e-inline")
        # Run must complete without raising
        assert events, "expected at least one event from run()"
        # ledger_store is attached (no broker → no ToolReceipt → no entries,
        # but the wiring is confirmed by _ledger_store being set)
        assert loop._ledger_store is store

    @pytest.mark.asyncio
    async def test_run_without_ledger_store_no_crash(self):
        """Regression: loop with ledger_store=None must not crash (old inline path)."""
        loop = AgentLoop(
            store=_FakeStore(), bus=EventBus(), sandbox=_OkSandbox(),
            broker=None, model=_DoneModel(), verifier=_NullVerifier(),
            config=LoopConfig(verify_cmd=None, max_rounds=1, max_steps=5),
            # ledger_store omitted → None (default)
        )
        events = await _collect(loop, session_id="run-no-ledger")
        assert events  # no crash

    def test_ledger_store_present_in_build_loop_factory(self, tmp_path: Path):
        """build_loop_factory threads ledger_store from AppComponents into AgentLoop."""
        from argos.app_factory import AppComponents, build_loop_factory
        from argos.core.loop import LoopConfig
        from argos.approval import ApprovalLevel

        ls = LedgerStore(tmp_path)

        # Minimal AppComponents stub (only what build_loop_factory accesses)
        class _StubWorkflow:
            pass

        import dataclasses

        # We can't call build_components (needs API key) so build AppComponents directly.
        # Only ledger_store + the fields accessed by the factory lambda matter.
        comps = AppComponents(
            store=_FakeStore(),  # type: ignore[arg-type]
            broker=None,         # type: ignore[arg-type]
            verifier=_NullVerifier(),  # type: ignore[arg-type]
            model=_DoneModel(),  # type: ignore[arg-type]
            sandbox=_OkSandbox(),  # type: ignore[arg-type]
            gate=None,           # type: ignore[arg-type]
            config=LoopConfig(verify_cmd=None, max_rounds=1, max_steps=5),
            workspace=tmp_path,
            workflow_engine_factory=lambda: _StubWorkflow(),
            ledger_store=ls,
        )
        factory = build_loop_factory(comps)
        loop = factory()
        assert loop._ledger_store is ls, (
            "build_loop_factory must thread ledger_store from AppComponents into AgentLoop"
        )
