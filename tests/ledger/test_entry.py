"""LedgerEntry 三态、frozen 不变量、序列化 round-trip 测试。"""
from __future__ import annotations

import dataclasses
import pytest
from argos_agent.ledger.entry import LedgerEntry, UndoState, Reversible


def _make_entry(**kwargs) -> LedgerEntry:
    defaults = dict(
        ts=1000.0,
        run_id="abc123",
        seq=1,
        action="write_file",
        summary_human="写入了 report.md(+10 行)",
        risk="low",
        reversible="yes",
        undo_token="/tmp/snap.tar",
        receipt_sig="abcd1234abcd1234",
        undo_state="available",
    )
    defaults.update(kwargs)
    return LedgerEntry(**defaults)


class TestLedgerEntryFrozen:
    def test_frozen(self):
        e = _make_entry()
        with pytest.raises((AttributeError, TypeError, dataclasses.FrozenInstanceError)):
            e.seq = 99  # type: ignore[misc]

    def test_slots(self):
        e = _make_entry()
        assert "__slots__" in type(e).__dict__


class TestLedgerEntryTriState:
    @pytest.mark.parametrize("reversible", ["yes", "no", "unknown"])
    def test_reversible_values(self, reversible):
        e = _make_entry(reversible=reversible)
        assert e.reversible == reversible

    @pytest.mark.parametrize("undo_state", ["available", "done", "impossible"])
    def test_undo_state_values(self, undo_state):
        e = _make_entry(undo_state=undo_state)
        assert e.undo_state == undo_state

    def test_reversible_no_undo_token_none(self):
        """reversible=no 的条目 undo_token 应为 None(不可逆无快照路径意义)。"""
        e = _make_entry(reversible="no", undo_token=None, undo_state="impossible")
        assert e.undo_token is None
        assert e.undo_state == "impossible"


class TestLedgerEntryWithUndoState:
    def test_with_undo_state_returns_new_instance(self):
        e = _make_entry(undo_state="available")
        e2 = e.with_undo_state("done")
        assert e.undo_state == "available"  # 原不变
        assert e2.undo_state == "done"

    def test_with_undo_state_preserves_other_fields(self):
        e = _make_entry(seq=5, action="bash", undo_state="available")
        e2 = e.with_undo_state("impossible")
        assert e2.seq == 5
        assert e2.action == "bash"


class TestLedgerEntrySerialization:
    def test_to_dict_round_trip(self):
        e = _make_entry()
        d = e.to_dict()
        e2 = LedgerEntry.from_dict(d)
        assert e == e2

    def test_to_dict_contains_required_keys(self):
        e = _make_entry()
        d = e.to_dict()
        required = {"ts", "run_id", "seq", "action", "summary_human",
                    "risk", "reversible", "undo_token", "receipt_sig", "undo_state"}
        assert required <= set(d.keys())

    def test_from_dict_none_undo_token(self):
        e = _make_entry(undo_token=None, reversible="no", undo_state="impossible")
        d = e.to_dict()
        e2 = LedgerEntry.from_dict(d)
        assert e2.undo_token is None
