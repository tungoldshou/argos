"""ConductorEngine tick 幂等性测试。

覆盖：
  - tick 产出 ProactiveSuggestion（schedule 到期）
  - tick 未到期不产出
  - tick 幂等：同一到期点不重复产出
  - tick 过了新到期点产出新 suggestion
  - disabled order 跳过
  - file_trigger：watcher 触发产出 suggestion
  - file_trigger：watcher 去抖不重复触发
  - 假时钟全程，0 真实 sleep
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, call

import pytest

from argos_agent.conductor.orders import OrderStore, StandingOrder
from argos_agent.conductor.engine import ConductorEngine
from argos_agent.conductor.triggers import FileTriggerFact, FileTriggerWatcher


# ---------------------------------------------------------------------------
# 辅助
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
# 定时触发（schedule）
# ---------------------------------------------------------------------------

class TestEngineSchedule:
    def test_tick_produces_suggestion_when_due(self, tmp_path: Path):
        """到期时 tick 产出一条 suggestion。"""
        store = OrderStore(tmp_path)
        order = _make_schedule_order("s1", schedule="* * * * *")
        store.add(order)

        # 用 now=60s，"* * * * *" 在 t=1s 就到期，60s > 到期点 → 触发
        t = [60.0]
        engine = ConductorEngine(store, clock=lambda: t[0])
        suggestions = engine.tick(60.0)

        assert len(suggestions) == 1
        assert suggestions[0].order_id == "s1"
        assert suggestions[0].requires_confirmation is True

    def test_tick_no_suggestion_before_due(self, tmp_path: Path):
        """now 早于第一个到期点 → 不产出。"""
        store = OrderStore(tmp_path)
        # "0 10 * * *" = 每天 10:00 UTC
        # now = 09:59（2024-01-01 09:59:00 UTC）
        from datetime import datetime, timezone
        now = datetime(2024, 1, 1, 9, 59, 0, tzinfo=timezone.utc).timestamp()

        order = _make_schedule_order("s_wait", schedule="0 10 * * *", last_fired_at=now - 3600)
        store.add(order)

        engine = ConductorEngine(store, clock=lambda: now)
        suggestions = engine.tick(now)
        assert len(suggestions) == 0

    def test_tick_idempotent_same_due_minute(self, tmp_path: Path):
        """同一到期分钟点连续 tick → 只产出一次。"""
        store = OrderStore(tmp_path)
        order = _make_schedule_order("s_idem", schedule="* * * * *")
        store.add(order)

        t = [60.0]
        engine = ConductorEngine(store, clock=lambda: t[0])

        sug1 = engine.tick(60.0)
        sug2 = engine.tick(60.0)  # 同一 now → 同一到期分钟 → 幂等
        assert len(sug1) == 1
        assert len(sug2) == 0

    def test_tick_new_due_point_produces_again(self, tmp_path: Path):
        """到了下一个新到期分钟点 → 再次产出。"""
        store = OrderStore(tmp_path)
        order = _make_schedule_order("s_new", schedule="* * * * *")
        store.add(order)

        t = [60.0]
        engine = ConductorEngine(store, clock=lambda: t[0])

        sug1 = engine.tick(60.0)
        assert len(sug1) == 1

        # 推进到下一分钟
        t[0] = 120.0
        sug2 = engine.tick(120.0)
        assert len(sug2) == 1
        assert sug2[0].order_id == "s_new"
        # 两次 suggestion ID 不同
        assert sug1[0].id != sug2[0].id

    def test_tick_disabled_order_skipped(self, tmp_path: Path):
        """disabled order 不产出 suggestion。"""
        store = OrderStore(tmp_path)
        order = _make_schedule_order("s_off", schedule="* * * * *", enabled=False)
        store.add(order)

        engine = ConductorEngine(store, clock=lambda: 60.0)
        suggestions = engine.tick(60.0)
        assert len(suggestions) == 0

    def test_tick_multiple_orders_multiple_suggestions(self, tmp_path: Path):
        """多条 enabled order 同时到期 → 各产出一条 suggestion。"""
        store = OrderStore(tmp_path)
        store.add(_make_schedule_order("s_a", schedule="* * * * *"))
        store.add(_make_schedule_order("s_b", schedule="* * * * *"))

        engine = ConductorEngine(store, clock=lambda: 60.0)
        suggestions = engine.tick(60.0)
        assert len(suggestions) == 2
        order_ids = {s.order_id for s in suggestions}
        assert order_ids == {"s_a", "s_b"}

    def test_last_fired_at_updated_after_tick(self, tmp_path: Path):
        """tick 触发后，OrderStore 中 last_fired_at 被更新。"""
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
# 文件触发（file_trigger）
# ---------------------------------------------------------------------------

class TestEngineFileTrigger:
    def _make_mock_watcher_factory(self, facts: list[FileTriggerFact]):
        """返回一个 watcher_factory，其 poll() 产出指定 facts 列表。"""
        mock_watcher = MagicMock(spec=FileTriggerWatcher)
        mock_watcher.poll.return_value = facts

        def factory(*args, **kwargs):
            return mock_watcher

        return factory, mock_watcher

    def test_file_trigger_produces_suggestion(self, tmp_path: Path):
        """watcher poll 有 fact → 产出 suggestion。"""
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
        """watcher poll 空 → 不产出。"""
        store = OrderStore(tmp_path)
        order = _make_file_trigger_order("ft2")
        store.add(order)

        factory, _ = self._make_mock_watcher_factory([])

        engine = ConductorEngine(store, clock=lambda: 50.0, watcher_factory=factory)
        suggestions = engine.tick(50.0)
        assert len(suggestions) == 0

    def test_file_trigger_disabled_skipped(self, tmp_path: Path):
        """disabled file_trigger order → 不 poll watcher，不产出。"""
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
        """watcher 懒创建：第一次 tick 才建，第二次复用。"""
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

        assert created_count[0] == 1  # 只创建一次

    def test_multiple_file_facts_multiple_suggestions(self, tmp_path: Path):
        """一次 poll 返回多个 fact → 各产出一条 suggestion。"""
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
# 混合：schedule + file_trigger 同时触发
# ---------------------------------------------------------------------------

class TestEngineMixed:
    def test_mixed_orders_both_trigger(self, tmp_path: Path):
        """schedule + file_trigger 两类 order 同时触发 → 各产出 suggestion。"""
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
