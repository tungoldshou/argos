"""Internal documentation."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, call

import pytest

from argos.conductor.orders import OrderStore, StandingOrder
from argos.conductor.engine import ConductorEngine
from argos.conductor.triggers import FileTriggerFact, FileTriggerWatcher


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------

def _make_schedule_order(
    order_id: str,
    schedule: str = "* * * * *",
    enabled: bool = True,
    created_at: float = 0.0,
    last_fired_at: float | None = None,
) -> StandingOrder:
    return StandingOrder(
        id=order_id,
        utterance="每分钟任务",
        kind="schedule",
        schedule=schedule,
        trigger_glob=None,
        goal_template="执行定时任务（{date}）",
        enabled=enabled,
        created_at=created_at,
        last_fired_at=last_fired_at,
    )


def _make_file_trigger_order(
    order_id: str,
    trigger_glob: str = "*.txt",
    enabled: bool = True,
) -> StandingOrder:
    return StandingOrder(
        id=order_id,
        utterance="文件变化任务",
        kind="file_trigger",
        schedule=None,
        trigger_glob=trigger_glob,
        goal_template="处理文件 {path}",
        enabled=enabled,
        created_at=0.0,
        last_fired_at=None,
    )


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------

class TestEngineSchedule:
    def test_tick_produces_suggestion_when_due(self, tmp_path: Path):
        """Internal documentation."""
        store = OrderStore(tmp_path)
        order = _make_schedule_order("s1", schedule="* * * * *")
        store.add(order)

        t = [60.0]
        engine = ConductorEngine(store, clock=lambda: t[0])
        suggestions = engine.tick(60.0)

        assert len(suggestions) == 1
        assert suggestions[0].order_id == "s1"
        assert suggestions[0].requires_confirmation is True

    def test_tick_no_suggestion_before_due(self, tmp_path: Path):
        """Internal documentation."""
        store = OrderStore(tmp_path)
        # now = 09:59（2024-01-01 09:59:00 UTC）
        from datetime import datetime, timezone
        now = datetime(2024, 1, 1, 9, 59, 0, tzinfo=timezone.utc).timestamp()

        order = _make_schedule_order("s_wait", schedule="0 10 * * *", last_fired_at=now - 3600)
        store.add(order)

        engine = ConductorEngine(store, clock=lambda: now)
        suggestions = engine.tick(now)
        assert len(suggestions) == 0

    def test_tick_idempotent_same_due_minute(self, tmp_path: Path):
        """Internal documentation."""
        store = OrderStore(tmp_path)
        order = _make_schedule_order("s_idem", schedule="* * * * *")
        store.add(order)

        t = [60.0]
        engine = ConductorEngine(store, clock=lambda: t[0])

        sug1 = engine.tick(60.0)
        sug2 = engine.tick(60.0)
        assert len(sug1) == 1
        assert len(sug2) == 0

    def test_tick_new_due_point_produces_again(self, tmp_path: Path):
        """Internal documentation."""
        store = OrderStore(tmp_path)
        order = _make_schedule_order("s_new", schedule="* * * * *")
        store.add(order)

        t = [60.0]
        engine = ConductorEngine(store, clock=lambda: t[0])

        sug1 = engine.tick(60.0)
        assert len(sug1) == 1

        t[0] = 120.0
        sug2 = engine.tick(120.0)
        assert len(sug2) == 1
        assert sug2[0].order_id == "s_new"
        assert sug1[0].id != sug2[0].id

    def test_tick_disabled_order_skipped(self, tmp_path: Path):
        """Internal documentation."""
        store = OrderStore(tmp_path)
        order = _make_schedule_order("s_off", schedule="* * * * *", enabled=False)
        store.add(order)

        engine = ConductorEngine(store, clock=lambda: 60.0)
        suggestions = engine.tick(60.0)
        assert len(suggestions) == 0

    def test_tick_multiple_orders_multiple_suggestions(self, tmp_path: Path):
        """Internal documentation."""
        store = OrderStore(tmp_path)
        store.add(_make_schedule_order("s_a", schedule="* * * * *"))
        store.add(_make_schedule_order("s_b", schedule="* * * * *"))

        engine = ConductorEngine(store, clock=lambda: 60.0)
        suggestions = engine.tick(60.0)
        assert len(suggestions) == 2
        order_ids = {s.order_id for s in suggestions}
        assert order_ids == {"s_a", "s_b"}

    def test_last_fired_at_updated_after_tick(self, tmp_path: Path):
        """Internal documentation."""
        store = OrderStore(tmp_path)
        order = _make_schedule_order("s_lf", schedule="* * * * *")
        store.add(order)

        engine = ConductorEngine(store, clock=lambda: 60.0)
        engine.tick(60.0)

        updated = store.get("s_lf")
        assert updated is not None
        assert updated.last_fired_at is not None
        assert updated.last_fired_at > 0


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------

class TestEngineFileTrigger:
    def _make_mock_watcher_factory(self, facts: list[FileTriggerFact]):
        """Internal documentation."""
        mock_watcher = MagicMock(spec=FileTriggerWatcher)
        mock_watcher.poll.return_value = facts

        def factory(*args, **kwargs):
            return mock_watcher

        return factory, mock_watcher

    def test_file_trigger_produces_suggestion(self, tmp_path: Path):
        """Internal documentation."""
        store = OrderStore(tmp_path)
        order = _make_file_trigger_order("ft1")
        store.add(order)

        fact = FileTriggerFact(
            path="/repo/requirements.txt",
            mtime=100.0,
            glob="*.txt",
            detected_at=50.0,
        )
        factory, _ = self._make_mock_watcher_factory([fact])

        engine = ConductorEngine(store, clock=lambda: 50.0, watcher_factory=factory)
        suggestions = engine.tick(50.0)

        assert len(suggestions) == 1
        s = suggestions[0]
        assert s.order_id == "ft1"
        assert "/repo/requirements.txt" in s.goal
        assert s.requires_confirmation is True

    def test_file_trigger_no_suggestion_when_no_facts(self, tmp_path: Path):
        """Internal documentation."""
        store = OrderStore(tmp_path)
        order = _make_file_trigger_order("ft2")
        store.add(order)

        factory, _ = self._make_mock_watcher_factory([])

        engine = ConductorEngine(store, clock=lambda: 50.0, watcher_factory=factory)
        suggestions = engine.tick(50.0)
        assert len(suggestions) == 0

    def test_file_trigger_disabled_skipped(self, tmp_path: Path):
        """Internal documentation."""
        store = OrderStore(tmp_path)
        order = _make_file_trigger_order("ft3", enabled=False)
        store.add(order)

        factory, mock_w = self._make_mock_watcher_factory([
            FileTriggerFact("/x.txt", 1.0, "*.txt", 50.0)
        ])

        engine = ConductorEngine(store, clock=lambda: 50.0, watcher_factory=factory)
        suggestions = engine.tick(50.0)
        assert len(suggestions) == 0
        mock_w.poll.assert_not_called()

    def test_file_trigger_watcher_created_lazily(self, tmp_path: Path):
        """Internal documentation."""
        store = OrderStore(tmp_path)
        order = _make_file_trigger_order("ft4")
        store.add(order)

        created_count = [0]
        mock_watcher = MagicMock(spec=FileTriggerWatcher)
        mock_watcher.poll.return_value = []

        def factory(*args, **kwargs):
            created_count[0] += 1
            return mock_watcher

        engine = ConductorEngine(store, clock=lambda: 50.0, watcher_factory=factory)
        engine.tick(50.0)
        engine.tick(50.0)

        assert created_count[0] == 1

    def test_multiple_file_facts_multiple_suggestions(self, tmp_path: Path):
        """Internal documentation."""
        store = OrderStore(tmp_path)
        order = _make_file_trigger_order("ft5")
        store.add(order)

        facts = [
            FileTriggerFact("/a.txt", 10.0, "*.txt", 50.0),
            FileTriggerFact("/b.txt", 20.0, "*.txt", 50.0),
        ]
        factory, _ = self._make_mock_watcher_factory(facts)

        engine = ConductorEngine(store, clock=lambda: 50.0, watcher_factory=factory)
        suggestions = engine.tick(50.0)
        assert len(suggestions) == 2


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------

class TestEngineMixed:
    def test_mixed_orders_both_trigger(self, tmp_path: Path):
        """Internal documentation."""
        store = OrderStore(tmp_path)
        s_order = _make_schedule_order("s_mix", schedule="* * * * *")
        f_order = _make_file_trigger_order("f_mix")
        store.add(s_order)
        store.add(f_order)

        mock_watcher = MagicMock(spec=FileTriggerWatcher)
        mock_watcher.poll.return_value = [
            FileTriggerFact("/repo/x.txt", 10.0, "*.txt", 60.0)
        ]

        def factory(*a, **k):
            return mock_watcher

        engine = ConductorEngine(store, clock=lambda: 60.0, watcher_factory=factory)
        suggestions = engine.tick(60.0)

        assert len(suggestions) == 2
        order_ids = {s.order_id for s in suggestions}
        assert "s_mix" in order_ids
        assert "f_mix" in order_ids
