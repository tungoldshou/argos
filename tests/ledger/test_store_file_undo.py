"""LedgerStore 文件粒度 undo 新接口测试(A3 条目级 undo)。

覆盖:
  - get_entry:按 seq 返回条目 / 不存在返 None
  - mark_entry_done:available → done 覆写 / 非 available 返 False / 不存在返 False
  - mark_entry_done 不影响其他条目
"""
from __future__ import annotations

from pathlib import Path

import pytest

from argos.ledger.entry import LedgerEntry
from argos.ledger.store import LedgerStore


def _entry(seq: int, run_id: str = "r1",
           reversible: str = "yes",
           undo_state: str = "available",
           undo_token: str | None = "file:/ws/foo.py") -> LedgerEntry:
    return LedgerEntry(
        ts=1000.0 + seq,
        run_id=run_id,
        seq=seq,
        action="file_diff",
        summary_human=f"修改了 foo{seq}.py",
        risk="low",
        reversible=reversible,  # type: ignore[arg-type]
        undo_token=undo_token if reversible == "yes" else None,
        receipt_sig="",
        undo_state=undo_state,  # type: ignore[arg-type]
    )


class TestGetEntry:
    def test_returns_entry_by_seq(self, tmp_path: Path):
        store = LedgerStore(tmp_path)
        store.append(_entry(1))
        store.append(_entry(2))
        e = store.get_entry("r1", 2)
        assert e is not None
        assert e.seq == 2

    def test_returns_none_for_missing_seq(self, tmp_path: Path):
        store = LedgerStore(tmp_path)
        store.append(_entry(1))
        assert store.get_entry("r1", 99) is None

    def test_returns_none_for_unknown_run(self, tmp_path: Path):
        store = LedgerStore(tmp_path)
        assert store.get_entry("no_such_run", 1) is None


class TestMarkEntryDone:
    def test_marks_available_entry_done(self, tmp_path: Path):
        store = LedgerStore(tmp_path)
        store.append(_entry(1))
        store.append(_entry(2))

        result = store.mark_entry_done("r1", 1)
        assert result is True

        e1 = store.get_entry("r1", 1)
        assert e1 is not None
        assert e1.undo_state == "done"

    def test_does_not_affect_other_entries(self, tmp_path: Path):
        store = LedgerStore(tmp_path)
        store.append(_entry(1))
        store.append(_entry(2))

        store.mark_entry_done("r1", 1)

        e2 = store.get_entry("r1", 2)
        assert e2 is not None
        assert e2.undo_state == "available", "未被 mark 的条目 undo_state 不应改变"

    def test_returns_false_for_nonexistent_seq(self, tmp_path: Path):
        store = LedgerStore(tmp_path)
        store.append(_entry(1))
        assert store.mark_entry_done("r1", 99) is False

    def test_returns_false_for_already_done_entry(self, tmp_path: Path):
        store = LedgerStore(tmp_path)
        store.append(_entry(1, undo_state="done"))
        assert store.mark_entry_done("r1", 1) is False

    def test_returns_false_for_impossible_entry(self, tmp_path: Path):
        store = LedgerStore(tmp_path)
        store.append(_entry(1, reversible="no", undo_state="impossible", undo_token=None))
        assert store.mark_entry_done("r1", 1) is False

    def test_mark_entry_done_idempotent_check(self, tmp_path: Path):
        """标记后 get_entry 返回 done 且原数据完整保留。"""
        store = LedgerStore(tmp_path)
        e_orig = _entry(1)
        store.append(e_orig)
        store.mark_entry_done("r1", 1)

        e = store.get_entry("r1", 1)
        assert e is not None
        assert e.undo_state == "done"
        assert e.action == e_orig.action
        assert e.summary_human == e_orig.summary_human
        assert e.undo_token == e_orig.undo_token
