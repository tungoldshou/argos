"""undo 流铁证:写文件 → ledger 落盘 → undo → 文件回原样 + 不可逆拒绝测试。"""
from __future__ import annotations

import pytest
from pathlib import Path

from argos_agent.core.snapshot import RunSnapshot, SNAPSHOT_ROOT
from argos_agent.ledger.builder import build_entry
from argos_agent.ledger.entry import LedgerEntry
from argos_agent.ledger.store import LedgerStore


class _FakeReceipt:
    def __init__(self, action: str, ts: float = 1000.0, sig: str = "deadsig0deadsig0") -> None:
        self.action = action
        self.ts = ts
        self.sig = sig


class TestUndoFlowFileRestored:
    """铁证:写文件 → ledger → undo → 文件回原样。"""

    def test_write_then_undo_restores_file(self, tmp_path: Path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        original = "original content\n"
        (ws / "report.md").write_text(original)

        # 1. run 起点拍快照
        snap_path = tmp_path / "snap.tar"
        snapshot = RunSnapshot.take(ws, snap_path)

        # 2. "agent 写入了新内容"
        (ws / "report.md").write_text("modified by agent\n")

        # 3. build_entry + 落账本
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

        # 4. 执行 undo:还原快照
        result = snapshot.restore(ws)
        assert result.restored, "快照必须还原了至少一个文件"
        store.undo_complete("run_undo_test")

        # 5. 铁证:文件内容回到 original
        assert (ws / "report.md").read_text() == original

        # 6. ledger 状态更新
        entries = store.replay("run_undo_test")
        real = [e for e in entries if e.action != "undo_done"]
        assert all(e.undo_state == "done" for e in real)
        assert store.is_undo_done("run_undo_test")

    def test_new_files_not_deleted_by_undo(self, tmp_path: Path):
        """spec §2.1.2:快照还原不删 run 中新建的文件。"""
        ws = tmp_path / "ws"
        ws.mkdir()
        (ws / "existing.py").write_text("v1")
        snap_path = tmp_path / "snap2.tar"
        snapshot = RunSnapshot.take(ws, snap_path)

        # agent 改了既有文件,也新建了一个文件
        (ws / "existing.py").write_text("v2")
        (ws / "new_file.py").write_text("new")

        result = snapshot.restore(ws)
        assert (ws / "new_file.py").exists(), "新建文件不应被删除"
        assert (ws / "existing.py").read_text() == "v1"


class TestUndoIrreversibleRejected:
    """不可逆动作的 undo_complete 拒绝语义。"""

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
    """undo 的 approval 语义验证(隔离测试:只测 LedgerStore 拒绝已撤销的情况)。"""

    def test_double_undo_rejected_at_store_level(self, tmp_path: Path):
        """is_undo_done 在第一次 undo_complete 后为 True;第二次应被调用方拒绝(409)。"""
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
        # 调用方应在 is_undo_done=True 时拒绝;再调 undo_complete 幂等返 False
        result2 = store.undo_complete("r2")
        assert result2 is False, "undo_done 哨兵存在后无 available 条目,返 False"
