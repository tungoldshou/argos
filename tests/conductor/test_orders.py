"""StandingOrder + OrderStore 测试。

覆盖：
  - StandingOrder frozen 不变量
  - 字段一致性断言（schedule/file_trigger 缺必填 → ValueError）
  - OrderStore round-trip（add → list → get）
  - OrderStore delete / update
  - JSONL 文件格式正确性
  - 空/不存在文件的防御性行为
  - 假时钟全程
"""
from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from argos_agent.conductor.orders import StandingOrder, OrderStore


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------

def _make_schedule_order(
    order_id: str = "ord001",
    schedule: str = "09:00",
    enabled: bool = True,
    created_at: float = 1000.0,
    last_fired_at: float | None = None,
) -> StandingOrder:
    return StandingOrder(
        id=order_id,
        utterance="每天早上九点整理日志",
        kind="schedule",
        schedule=schedule,
        trigger_glob=None,
        goal_template="请将昨天 {date} 的日志整理成摘要",
        enabled=enabled,
        created_at=created_at,
        last_fired_at=last_fired_at,
    )


def _make_file_trigger_order(
    order_id: str = "ord002",
    trigger_glob: str = "**/requirements*.txt",
    enabled: bool = True,
) -> StandingOrder:
    return StandingOrder(
        id=order_id,
        utterance="每次 requirements.txt 变化就分析依赖",
        kind="file_trigger",
        schedule=None,
        trigger_glob=trigger_glob,
        goal_template="分析 {path} 的依赖变化",
        enabled=enabled,
        created_at=2000.0,
        last_fired_at=None,
    )


# ---------------------------------------------------------------------------
# StandingOrder 不变量
# ---------------------------------------------------------------------------

class TestStandingOrderFrozen:
    def test_frozen_cannot_set_field(self):
        o = _make_schedule_order()
        with pytest.raises((AttributeError, TypeError, dataclasses.FrozenInstanceError)):
            o.enabled = False  # type: ignore[misc]

    def test_slots_present(self):
        o = _make_schedule_order()
        assert "__slots__" in type(o).__dict__

    def test_hashable(self):
        o = _make_schedule_order()
        assert hash(o) is not None
        s = {o}
        assert o in s


class TestStandingOrderConstraints:
    def test_schedule_kind_requires_schedule(self):
        with pytest.raises(ValueError, match="schedule"):
            StandingOrder(
                id="x", utterance="u", kind="schedule",
                schedule=None,          # 缺 schedule → 抛
                trigger_glob=None,
                goal_template="g", enabled=True,
                created_at=1.0, last_fired_at=None,
            )

    def test_file_trigger_kind_requires_trigger_glob(self):
        with pytest.raises(ValueError, match="trigger_glob"):
            StandingOrder(
                id="x", utterance="u", kind="file_trigger",
                schedule=None,
                trigger_glob=None,      # 缺 trigger_glob → 抛
                goal_template="g", enabled=True,
                created_at=1.0, last_fired_at=None,
            )

    def test_schedule_empty_string_also_invalid(self):
        """空字符串视为"未提供"，应抛 ValueError。"""
        with pytest.raises(ValueError):
            StandingOrder(
                id="x", utterance="u", kind="schedule",
                schedule="",            # 空串 → falsy → 抛
                trigger_glob=None,
                goal_template="g", enabled=True,
                created_at=1.0, last_fired_at=None,
            )

    def test_valid_schedule_order_ok(self):
        o = _make_schedule_order()
        assert o.kind == "schedule"
        assert o.schedule == "09:00"

    def test_valid_file_trigger_order_ok(self):
        o = _make_file_trigger_order()
        assert o.kind == "file_trigger"
        assert o.trigger_glob == "**/requirements*.txt"


class TestStandingOrderHelpers:
    def test_with_last_fired(self):
        o = _make_schedule_order(last_fired_at=None)
        o2 = o.with_last_fired(9999.0)
        assert o.last_fired_at is None       # 原不变
        assert o2.last_fired_at == 9999.0

    def test_with_enabled(self):
        o = _make_schedule_order(enabled=True)
        o2 = o.with_enabled(False)
        assert o.enabled is True             # 原不变
        assert o2.enabled is False


# ---------------------------------------------------------------------------
# StandingOrder 序列化 round-trip
# ---------------------------------------------------------------------------

class TestStandingOrderSerialization:
    def test_schedule_round_trip(self):
        o = _make_schedule_order(last_fired_at=12345.0)
        d = o.to_dict()
        o2 = StandingOrder.from_dict(d)
        assert o == o2

    def test_file_trigger_round_trip(self):
        o = _make_file_trigger_order()
        d = o.to_dict()
        o2 = StandingOrder.from_dict(d)
        assert o == o2

    def test_none_last_fired_survives_round_trip(self):
        o = _make_schedule_order(last_fired_at=None)
        d = o.to_dict()
        o2 = StandingOrder.from_dict(d)
        assert o2.last_fired_at is None

    def test_to_dict_has_required_keys(self):
        o = _make_schedule_order()
        d = o.to_dict()
        for key in ("id", "utterance", "kind", "schedule", "trigger_glob",
                    "goal_template", "enabled", "created_at", "last_fired_at"):
            assert key in d


# ---------------------------------------------------------------------------
# OrderStore CRUD
# ---------------------------------------------------------------------------

class TestOrderStoreAdd:
    def test_add_creates_file(self, tmp_path: Path):
        store = OrderStore(tmp_path)
        store.add(_make_schedule_order())
        assert store.path.exists()

    def test_add_single_order_list(self, tmp_path: Path):
        store = OrderStore(tmp_path)
        o = _make_schedule_order()
        store.add(o)
        orders = store.list()
        assert len(orders) == 1
        assert orders[0].id == "ord001"

    def test_add_multiple_orders(self, tmp_path: Path):
        store = OrderStore(tmp_path)
        store.add(_make_schedule_order("a"))
        store.add(_make_schedule_order("b"))
        store.add(_make_file_trigger_order("c"))
        orders = store.list()
        assert len(orders) == 3
        ids = {o.id for o in orders}
        assert ids == {"a", "b", "c"}

    def test_jsonl_each_line_valid_json(self, tmp_path: Path):
        store = OrderStore(tmp_path)
        store.add(_make_schedule_order("x"))
        store.add(_make_file_trigger_order("y"))
        lines = store.path.read_text().strip().splitlines()
        assert len(lines) == 2
        for line in lines:
            d = json.loads(line)
            assert "id" in d and "kind" in d


class TestOrderStoreGet:
    def test_get_existing(self, tmp_path: Path):
        store = OrderStore(tmp_path)
        store.add(_make_schedule_order("get_me"))
        o = store.get("get_me")
        assert o is not None
        assert o.id == "get_me"

    def test_get_nonexistent_returns_none(self, tmp_path: Path):
        store = OrderStore(tmp_path)
        assert store.get("nope") is None

    def test_list_empty_for_no_file(self, tmp_path: Path):
        store = OrderStore(tmp_path)
        assert store.list() == []


class TestOrderStoreDelete:
    def test_delete_existing(self, tmp_path: Path):
        store = OrderStore(tmp_path)
        store.add(_make_schedule_order("del_me"))
        result = store.delete("del_me")
        assert result is True
        assert store.get("del_me") is None

    def test_delete_nonexistent_returns_false(self, tmp_path: Path):
        store = OrderStore(tmp_path)
        result = store.delete("ghost")
        assert result is False

    def test_delete_leaves_others(self, tmp_path: Path):
        store = OrderStore(tmp_path)
        store.add(_make_schedule_order("a"))
        store.add(_make_schedule_order("b"))
        store.delete("a")
        orders = store.list()
        assert len(orders) == 1
        assert orders[0].id == "b"


class TestOrderStoreUpdate:
    def test_update_existing(self, tmp_path: Path):
        store = OrderStore(tmp_path)
        o = _make_schedule_order("upd", enabled=True)
        store.add(o)
        updated = o.with_enabled(False)
        result = store.update(updated)
        assert result is True
        o2 = store.get("upd")
        assert o2 is not None
        assert o2.enabled is False

    def test_update_nonexistent_returns_false(self, tmp_path: Path):
        store = OrderStore(tmp_path)
        o = _make_schedule_order("ghost")
        result = store.update(o)
        assert result is False

    def test_update_preserves_others(self, tmp_path: Path):
        store = OrderStore(tmp_path)
        store.add(_make_schedule_order("a", created_at=1.0))
        store.add(_make_schedule_order("b", created_at=2.0))
        o_a = store.get("a")
        assert o_a is not None
        store.update(o_a.with_enabled(False))
        # b 不受影响
        o_b = store.get("b")
        assert o_b is not None
        assert o_b.enabled is True


class TestOrderStoreSortOrder:
    def test_list_sorted_by_created_at(self, tmp_path: Path):
        store = OrderStore(tmp_path)
        # 故意倒序添加
        store.add(_make_schedule_order("c", created_at=3.0))
        store.add(_make_schedule_order("a", created_at=1.0))
        store.add(_make_schedule_order("b", created_at=2.0))
        orders = store.list()
        created_ats = [o.created_at for o in orders]
        assert created_ats == sorted(created_ats)


# ---------------------------------------------------------------------------
# action 字段
# ---------------------------------------------------------------------------

def test_order_action_default_run_and_roundtrip():
    """action 默认 'run';to_dict/from_dict 往返;旧落盘数据(无 action 键)兼容。"""
    import time
    o = StandingOrder(
        id="x1", utterance="u", kind="schedule", schedule="03:00",
        trigger_glob=None, goal_template="g", enabled=True,
        created_at=time.time(), last_fired_at=None,
    )
    assert o.action == "run"
    d = o.to_dict()
    assert d["action"] == "run"
    d.pop("action")  # 模拟旧数据
    assert StandingOrder.from_dict(d).action == "run"


def test_order_action_dream_roundtrip():
    import time
    o = StandingOrder(
        id="x2", utterance="夜间整合", kind="schedule", schedule="03:00",
        trigger_glob=None, goal_template="__dream__", enabled=True,
        created_at=time.time(), last_fired_at=None, action="dream",
    )
    assert StandingOrder.from_dict(o.to_dict()).action == "dream"


def test_order_action_invalid_rejected():
    import time
    with pytest.raises(ValueError):
        StandingOrder(
            id="x3", utterance="u", kind="schedule", schedule="03:00",
            trigger_glob=None, goal_template="g", enabled=True,
            created_at=time.time(), last_fired_at=None, action="hack",
        )
