"""LedgerEntryEvent 黄金快照测试 + serialize/deserialize round-trip。

防 ABI 漂移:字段变化必须有意识地更新本测试。
"""
from __future__ import annotations

import json
import pytest

from argos_agent.tui import events as E
from argos_agent.protocol.events import LedgerEntryEvent


class TestLedgerEntryEventContract:
    def test_kind_constant(self):
        assert LedgerEntryEvent.kind == "ledger_entry"

    def test_frozen_and_slots(self):
        params = LedgerEntryEvent.__dataclass_params__
        assert params.frozen, "LedgerEntryEvent 必须 frozen"
        assert "__slots__" in LedgerEntryEvent.__dict__, "LedgerEntryEvent 必须 slots"

    def test_in_event_union(self):
        """LedgerEntryEvent 必须在 Event 联合中(隐式:serialize_event 能处理它)。"""
        ev = LedgerEntryEvent(
            ts=1000.0, run_id="r1", seq=1,
            action="write_file", summary_human="写入了 a.py",
            risk="low", reversible="yes", undo_state="available",
        )
        blob = E.serialize_event(ev)
        assert isinstance(blob, str)

    def test_in_all_event_kinds_literal(self):
        """EventKind 必须包含 ledger_entry(已在 test_events_serialization.py 的 ALL_EVENT_KINDS 里)。"""
        assert "ledger_entry" in E.EventKind.__args__

    def test_shim_re_exports(self):
        """tui/events.py shim 必须 re-export LedgerEntryEvent。"""
        assert hasattr(E, "LedgerEntryEvent")
        assert E.LedgerEntryEvent is LedgerEntryEvent


class TestLedgerEntryEventSerializeDeserialize:
    def _make(self, **kwargs) -> LedgerEntryEvent:
        defaults = dict(
            ts=1234.5,
            run_id="abc123",
            seq=3,
            action="write_file",
            summary_human="写入了 report.md(+42 行)",
            risk="low",
            reversible="yes",
            undo_state="available",
        )
        defaults.update(kwargs)
        return LedgerEntryEvent(**defaults)

    def test_serialize_contains_kind(self):
        ev = self._make()
        blob = E.serialize_event(ev)
        d = json.loads(blob)
        assert d["kind"] == "ledger_entry"

    def test_round_trip(self):
        ev = self._make()
        blob = E.serialize_event(ev)
        back = E.deserialize_event(blob)
        assert isinstance(back, LedgerEntryEvent)
        assert back.run_id == "abc123"
        assert back.seq == 3
        assert back.summary_human == "写入了 report.md(+42 行)"
        assert back.reversible == "yes"
        assert back.undo_state == "available"

    def test_round_trip_impossible(self):
        ev = self._make(action="web_fetch", reversible="no",
                        undo_state="impossible", risk="high",
                        summary_human="发出了 GET 请求: https://api.example.com")
        back = E.deserialize_event(E.serialize_event(ev))
        assert back.reversible == "no"
        assert back.undo_state == "impossible"
        assert back.risk == "high"

    def test_golden_snapshot(self):
        """黄金快照:字段集合不得悄悄漂移。"""
        ev = self._make()
        d = json.loads(E.serialize_event(ev))
        expected_data_keys = {
            "ts", "run_id", "seq", "action", "summary_human",
            "risk", "reversible", "undo_state",
        }
        assert set(d["data"].keys()) == expected_data_keys, (
            f"LedgerEntryEvent 字段漂移!实际: {set(d['data'].keys())}"
        )
