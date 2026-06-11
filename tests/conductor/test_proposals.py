"""ProactiveSuggestion + propose() 测试。

覆盖：
  - requires_confirmation 契约（构造 False → ValueError）
  - frozen 不变量
  - propose() 正确填充 goal_template 占位符
  - propose() schedule/file_trigger 两种 reason_human
  - 缺失占位符键保持原样（不抛 KeyError）
  - 注入假时钟（0 真实 sleep）
"""
from __future__ import annotations

import dataclasses

import pytest

from argos_agent.conductor.orders import StandingOrder
from argos_agent.conductor.proposals import ProactiveSuggestion, propose


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------

def _make_schedule_order(
    order_id: str = "sched001",
    goal_template: str = "整理 {date} 的日志",
    schedule: str = "09:00",
) -> StandingOrder:
    return StandingOrder(
        id=order_id,
        utterance="每天早上九点整理日志",
        kind="schedule",
        schedule=schedule,
        trigger_glob=None,
        goal_template=goal_template,
        enabled=True,
        created_at=1000.0,
        last_fired_at=None,
    )


def _make_file_trigger_order(
    order_id: str = "file001",
    goal_template: str = "分析 {path} 的依赖变化",
    trigger_glob: str = "*.txt",
) -> StandingOrder:
    return StandingOrder(
        id=order_id,
        utterance="requirements.txt 变化时分析依赖",
        kind="file_trigger",
        schedule=None,
        trigger_glob=trigger_glob,
        goal_template=goal_template,
        enabled=True,
        created_at=2000.0,
        last_fired_at=None,
    )


# ---------------------------------------------------------------------------
# ProactiveSuggestion 契约：requires_confirmation 永远 True
# ---------------------------------------------------------------------------

class TestRequiresConfirmationContract:
    def test_construction_with_true_ok(self):
        s = ProactiveSuggestion(
            id="s1",
            order_id="o1",
            goal="do something",
            reason_human="定时触发",
            suggested_at=1000.0,
            requires_confirmation=True,
        )
        assert s.requires_confirmation is True

    def test_construction_with_false_raises(self):
        """requires_confirmation=False → ValueError（契约级）。"""
        with pytest.raises(ValueError, match="requires_confirmation"):
            ProactiveSuggestion(
                id="s1",
                order_id="o1",
                goal="do something",
                reason_human="定时触发",
                suggested_at=1000.0,
                requires_confirmation=False,  # 违反契约
            )

    def test_propose_always_returns_requires_confirmation_true(self):
        """propose() 产出的 suggestion requires_confirmation 永远为 True。"""
        order = _make_schedule_order()
        s = propose(order, {"date": "2024-01-01"}, clock=lambda: 1000.0)
        assert s.requires_confirmation is True


# ---------------------------------------------------------------------------
# ProactiveSuggestion frozen 不变量
# ---------------------------------------------------------------------------

class TestProactiveSuggestionFrozen:
    def test_frozen(self):
        s = ProactiveSuggestion(
            id="s1", order_id="o1", goal="g",
            reason_human="r", suggested_at=1.0, requires_confirmation=True,
        )
        with pytest.raises((AttributeError, TypeError, dataclasses.FrozenInstanceError)):
            s.goal = "changed"  # type: ignore[misc]

    def test_slots(self):
        s = ProactiveSuggestion(
            id="s1", order_id="o1", goal="g",
            reason_human="r", suggested_at=1.0, requires_confirmation=True,
        )
        assert "__slots__" in type(s).__dict__

    def test_hashable(self):
        s = ProactiveSuggestion(
            id="s1", order_id="o1", goal="g",
            reason_human="r", suggested_at=1.0, requires_confirmation=True,
        )
        assert hash(s) is not None


# ---------------------------------------------------------------------------
# propose() — goal_template 填充
# ---------------------------------------------------------------------------

class TestProposeGoalTemplate:
    def test_fills_date_placeholder(self):
        order = _make_schedule_order(goal_template="整理 {date} 的日志")
        s = propose(order, {"date": "2024-01-15"}, clock=lambda: 9999.0)
        assert "2024-01-15" in s.goal
        assert "{date}" not in s.goal

    def test_fills_path_placeholder(self):
        order = _make_file_trigger_order(goal_template="分析 {path} 的依赖")
        s = propose(order, {"path": "/repo/requirements.txt"}, clock=lambda: 1.0)
        assert "/repo/requirements.txt" in s.goal

    def test_missing_key_kept_as_placeholder(self):
        """缺失占位符键 → 保持 {key} 原样，不抛 KeyError。"""
        order = _make_schedule_order(goal_template="整理 {date} 的 {missing} 日志")
        s = propose(order, {"date": "2024-01-01"}, clock=lambda: 1.0)
        assert "{missing}" in s.goal
        assert "2024-01-01" in s.goal

    def test_empty_context(self):
        """空 context → 模板原样返回。"""
        order = _make_schedule_order(goal_template="每日汇报")
        s = propose(order, {}, clock=lambda: 1.0)
        assert s.goal == "每日汇报"

    def test_no_placeholder_template(self):
        order = _make_schedule_order(goal_template="直接目标无占位符")
        s = propose(order, {"date": "2024-01-01"}, clock=lambda: 1.0)
        assert s.goal == "直接目标无占位符"


# ---------------------------------------------------------------------------
# propose() — order_id 绑定 + 时间戳
# ---------------------------------------------------------------------------

class TestProposeFields:
    def test_order_id_set(self):
        order = _make_schedule_order(order_id="my_order")
        s = propose(order, {}, clock=lambda: 1.0)
        assert s.order_id == "my_order"

    def test_suggested_at_from_clock(self):
        fake_ts = 12345.6789
        order = _make_schedule_order()
        s = propose(order, {}, clock=lambda: fake_ts)
        assert s.suggested_at == fake_ts

    def test_id_is_nonempty_string(self):
        order = _make_schedule_order()
        s = propose(order, {}, clock=lambda: 1.0)
        assert isinstance(s.id, str)
        assert len(s.id) > 0

    def test_two_proposals_have_different_ids(self):
        order = _make_schedule_order()
        s1 = propose(order, {}, clock=lambda: 1.0)
        s2 = propose(order, {}, clock=lambda: 1.0)
        assert s1.id != s2.id  # uuid4 应不同


# ---------------------------------------------------------------------------
# propose() — reason_human 内容
# ---------------------------------------------------------------------------

class TestProposeReasonHuman:
    def test_schedule_reason_contains_schedule(self):
        order = _make_schedule_order(schedule="09:00")
        s = propose(order, {}, clock=lambda: 1.0)
        assert "09:00" in s.reason_human

    def test_schedule_reason_contains_utterance(self):
        order = _make_schedule_order()
        s = propose(order, {}, clock=lambda: 1.0)
        assert order.utterance in s.reason_human

    def test_file_trigger_reason_contains_path(self):
        order = _make_file_trigger_order()
        s = propose(order, {"path": "/repo/requirements.txt"}, clock=lambda: 1.0)
        assert "/repo/requirements.txt" in s.reason_human

    def test_file_trigger_reason_contains_utterance(self):
        order = _make_file_trigger_order()
        s = propose(order, {"path": "/x"}, clock=lambda: 1.0)
        assert order.utterance in s.reason_human
