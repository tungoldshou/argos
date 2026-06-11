"""LedgerStore JSONL 追加 + 回放 + undo_complete 测试。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from argos_agent.ledger.entry import LedgerEntry
from argos_agent.ledger.store import LedgerStore


def _make_entry(seq: int, run_id: str = "run001",
                reversible: str = "yes",
                undo_state: str = "available",
                undo_token: str | None = "/tmp/snap.tar") -> LedgerEntry:
    return LedgerEntry(
        ts=1000.0 + seq,
        run_id=run_id,
        seq=seq,
        action="write_file",
        summary_human=f"写入了 file{seq}.py",
        risk="low",
        reversible=reversible,   # type: ignore[arg-type]
        undo_token=undo_token if reversible == "yes" else None,
        receipt_sig="abcd1234abcd1234",
        undo_state=undo_state,   # type: ignore[arg-type]
    )


class TestLedgerStoreAppendReplay:
    def test_append_and_replay_roundtrip(self, tmp_path: Path):
        store = LedgerStore(tmp_path)
        e1 = _make_entry(1)
        e2 = _make_entry(2)
        store.append(e1)
        store.append(e2)

        entries = store.replay("run001")
        assert len(entries) == 2
        assert entries[0].seq == 1
        assert entries[1].seq == 2
        assert entries[0].summary_human == "写入了 file1.py"

    def test_replay_empty_for_unknown_run(self, tmp_path: Path):
        store = LedgerStore(tmp_path)
        assert store.replay("nonexistent") == []

    def test_replay_sorted_by_seq(self, tmp_path: Path):
        """回放结果按 seq 排序(即使落盘顺序不同)。"""
        store = LedgerStore(tmp_path)
        e3 = _make_entry(3)
        e1 = _make_entry(1)
        e2 = _make_entry(2)
        store.append(e3)
        store.append(e1)
        store.append(e2)
        entries = store.replay("run001")
        seqs = [e.seq for e in entries]
        assert seqs == sorted(seqs)

    def test_jsonl_file_created(self, tmp_path: Path):
        store = LedgerStore(tmp_path)
        store.append(_make_entry(1))
        assert (tmp_path / "run001.jsonl").exists()

    def test_jsonl_file_each_line_valid_json(self, tmp_path: Path):
        store = LedgerStore(tmp_path)
        store.append(_make_entry(1))
        store.append(_make_entry(2))
        lines = (tmp_path / "run001.jsonl").read_text().strip().splitlines()
        assert len(lines) == 2
        for line in lines:
            d = json.loads(line)
            assert "seq" in d
            assert "action" in d


class TestLedgerStoreUndoComplete:
    def test_undo_complete_marks_available_as_done(self, tmp_path: Path):
        store = LedgerStore(tmp_path)
        store.append(_make_entry(1, undo_state="available"))
        store.append(_make_entry(2, undo_state="available"))

        result = store.undo_complete("run001")
        assert result is True

        entries = store.replay("run001")
        # 所有 available → done
        real = [e for e in entries if e.action != "undo_done"]
        assert all(e.undo_state == "done" for e in real)

    def test_undo_complete_appends_undo_done_marker(self, tmp_path: Path):
        store = LedgerStore(tmp_path)
        store.append(_make_entry(1))
        store.undo_complete("run001")

        entries = store.replay("run001")
        assert any(e.action == "undo_done" for e in entries)

    def test_undo_complete_returns_false_when_no_available(self, tmp_path: Path):
        store = LedgerStore(tmp_path)
        store.append(_make_entry(1, reversible="no", undo_state="impossible", undo_token=None))
        result = store.undo_complete("run001")
        assert result is False

    def test_undo_complete_returns_false_for_empty_run(self, tmp_path: Path):
        store = LedgerStore(tmp_path)
        result = store.undo_complete("empty_run")
        assert result is False

    def test_is_undo_done_after_complete(self, tmp_path: Path):
        store = LedgerStore(tmp_path)
        store.append(_make_entry(1))
        assert store.is_undo_done("run001") is False
        store.undo_complete("run001")
        assert store.is_undo_done("run001") is True

    def test_impossible_entries_not_affected_by_undo_complete(self, tmp_path: Path):
        """不可逆条目 undo_state=impossible 在 undo_complete 后仍为 impossible。"""
        store = LedgerStore(tmp_path)
        store.append(_make_entry(1, undo_state="available"))
        store.append(_make_entry(2, reversible="no", undo_state="impossible", undo_token=None))
        store.undo_complete("run001")

        entries = store.replay("run001")
        real = [e for e in entries if e.action != "undo_done"]
        seq1 = next(e for e in real if e.seq == 1)
        seq2 = next(e for e in real if e.seq == 2)
        assert seq1.undo_state == "done"
        assert seq2.undo_state == "impossible"
