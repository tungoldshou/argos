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


class TestInlineLedgerI18n:
    """i18n parity: inline file_diff summary must match daemon path under ARGOS_LANG=en."""

    def test_file_diff_summary_english_when_lang_en(self, tmp_path: Path, monkeypatch):
        """ARGOS_LANG=en → summary_human uses EN locale (same key as daemon/worker.py:635-638)."""
        monkeypatch.setenv("ARGOS_LANG", "en")
        store = LedgerStore(tmp_path)
        loop = _make_loop(store)

        ev = FileDiff(path="src/bar.py", added=5, removed=2, unified="@@...")
        loop._inline_maybe_append_ledger(ev, "run-i18n-en")

        entries = store.replay("run-i18n-en")
        assert len(entries) == 1
        summary = entries[0].summary_human
        # EN locale key "daemon.srv.ledger_modified_diff" → "modified {basename} (+{added}/-{removed})"
        assert "bar.py" in summary
        assert "modified" in summary.lower(), f"expected English 'modified' in {summary!r}"
        assert "修改了" not in summary, f"Chinese leaked into EN summary: {summary!r}"

    def test_file_diff_no_diff_summary_english(self, tmp_path: Path, monkeypatch):
        """ARGOS_LANG=en, no diff counts → EN 'modified {basename}' (not Chinese)."""
        monkeypatch.setenv("ARGOS_LANG", "en")
        store = LedgerStore(tmp_path)
        loop = _make_loop(store)

        ev = FileDiff(path="src/baz.py", added=0, removed=0, unified="")
        loop._inline_maybe_append_ledger(ev, "run-i18n-en-nodiff")

        entries = store.replay("run-i18n-en-nodiff")
        assert len(entries) == 1
        summary = entries[0].summary_human
        assert "修改了" not in summary, f"Chinese leaked into EN summary: {summary!r}"
        assert "baz.py" in summary


class TestInlineLedgerEndToEnd:
    """Integration: AgentLoop.run() passes events through _inline_maybe_append_ledger."""

    @pytest.mark.asyncio
    async def test_run_wires_ledger_store_via_tool_receipt(self, tmp_path: Path):
        """run() routes a real ToolReceipt through _inline_maybe_append_ledger → disk.

        Uses monkeypatched _drive to inject a ToolReceipt event mid-run, then
        asserts store.replay returns a non-empty list with the correct action + signature.
        This closes the unit-vs-integration gap: the prior test only checked
        loop._ledger_store is store, not that run() actually persisted anything.
        """
        import unittest.mock as mock

        store = LedgerStore(tmp_path)
        loop = _make_loop(store)

        signer = ReceiptSigner(key=b"test-inline-key-32bytes-padded!!")
        receipt = signer.sign(action="write_file", args={"path": "x.py"},
                              result="ok", exit_code=0)
        injected_ev = ToolReceipt(receipt=receipt)

        # Patch _drive to yield our ToolReceipt then stop (avoids needing real model/broker)
        original_drive = loop._drive

        async def _fake_drive(goal, session_id, **kwargs):
            yield injected_ev
            # Let original plan phase run so loop terminates cleanly
            async for ev in original_drive(goal, session_id, **kwargs):
                yield ev

        with mock.patch.object(loop, "_drive", _fake_drive):
            events = [ev async for ev in loop.run("test goal", "run-e2e-receipt")]

        assert events, "expected at least one event from run()"
        entries = store.replay("run-e2e-receipt")
        assert len(entries) >= 1, "run() must persist at least one LedgerEntry via ToolReceipt"
        e = entries[0]
        assert e.action == "write_file"
        assert e.run_id == "run-e2e-receipt"
        assert e.receipt_sig, "receipt_sig must be non-empty (real HMAC)"

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
