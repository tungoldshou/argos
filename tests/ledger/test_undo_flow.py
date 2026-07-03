"""Internal documentation."""
from __future__ import annotations

import pytest
from pathlib import Path

from argos.core.snapshot import RunSnapshot, SNAPSHOT_ROOT
from argos.ledger.builder import build_entry
from argos.ledger.entry import LedgerEntry
from argos.ledger.store import LedgerStore


class _FakeReceipt:
    def __init__(self, action: str, ts: float = 1000.0, sig: str = "deadsig0deadsig0") -> None:
        self.action = action
        self.ts = ts
        self.sig = sig


class TestUndoFlowFileRestored:
    """Internal documentation."""

    def test_write_then_undo_restores_file(self, tmp_path: Path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        original = "original content\n"
        (ws / "report.md").write_text(original)

        snap_path = tmp_path / "snap.tar"
        snapshot = RunSnapshot.take(ws, snap_path)

        (ws / "report.md").write_text("modified by agent\n")

        store = LedgerStore(tmp_path / "ledger")
        receipt = _FakeReceipt("write_file")
        entry = build_entry(
            receipt=receipt,
            run_id="run_undo_test",
            seq=1,
            args={"path": str(ws / "report.md")},
            undo_token=str(snap_path),
        )
        store.append(entry)

        assert entry.reversible == "yes"
        assert entry.undo_state == "available"

        result = snapshot.restore(ws)
        assert result.restored, "快照必须还原了至少一个文件"
        store.undo_complete("run_undo_test")

        assert (ws / "report.md").read_text() == original

        entries = store.replay("run_undo_test")
        real = [e for e in entries if e.action != "undo_done"]
        assert all(e.undo_state == "done" for e in real)
        assert store.is_undo_done("run_undo_test")

    def test_new_files_not_deleted_by_undo(self, tmp_path: Path):
        """Internal documentation."""
        ws = tmp_path / "ws"
        ws.mkdir()
        (ws / "existing.py").write_text("v1")
        snap_path = tmp_path / "snap2.tar"
        snapshot = RunSnapshot.take(ws, snap_path)

        (ws / "existing.py").write_text("v2")
        (ws / "new_file.py").write_text("new")

        result = snapshot.restore(ws)
        assert (ws / "new_file.py").exists(), "新建文件不应被删除"
        assert (ws / "existing.py").read_text() == "v1"


class TestUndoIrreversibleRejected:
    """Internal documentation."""

    def test_irreversible_entry_undo_state_impossible(self):
        receipt = _FakeReceipt("web_fetch")
        entry = build_entry(receipt=receipt, run_id="r1", seq=1)
        assert entry.reversible == "no"
        assert entry.undo_state == "impossible"
        assert entry.undo_token is None

    def test_store_undo_complete_returns_false_for_all_impossible(self, tmp_path: Path):
        store = LedgerStore(tmp_path / "ledger")
        receipt = _FakeReceipt("browser_navigate")
        entry = build_entry(receipt=receipt, run_id="net_run", seq=1)
        store.append(entry)

        result = store.undo_complete("net_run")
        assert result is False, "全不可逆的 run 不能 undo_complete"

    def test_store_undo_complete_false_on_empty(self, tmp_path: Path):
        store = LedgerStore(tmp_path / "ledger")
        assert store.undo_complete("empty") is False


class TestUndoOverApproval:
    """Internal documentation."""

    def test_double_undo_rejected_at_store_level(self, tmp_path: Path):
        """Internal documentation."""
        store = LedgerStore(tmp_path / "ledger")
        receipt = _FakeReceipt("write_file")
        snap_path = tmp_path / "s.tar"
        snap_path.touch()
        entry = build_entry(receipt=receipt, run_id="r2", seq=1,
                            undo_token=str(snap_path))
        store.append(entry)

        assert store.is_undo_done("r2") is False
        store.undo_complete("r2")
        assert store.is_undo_done("r2") is True
        result2 = store.undo_complete("r2")
        assert result2 is False, "undo_done 哨兵存在后无 available 条目,返 False"
