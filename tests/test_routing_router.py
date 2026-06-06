"""#11 T4 ModelRouter 懒构造 + history + EffortLevel 映射 测试。"""
import pytest

from argos_agent.approval import ApprovalLevel
from argos_agent.routing.categorizer import TaskCategory
from argos_agent.routing.config import RoutingConfig
from argos_agent.routing.effort import (
    EFFORT_PRESETS, EffortLevel, effort_settings,
)
from argos_agent.routing.router import ModelRouter


class _FakeModel:
    def __init__(self, name: str) -> None:
        self.name = name
        self.stream_calls = 0
        self.last_usage = {"input_tokens": 0, "output_tokens": 0,
                           "cache_read": 0, "cache_creation": 0}

    async def stream(self, messages, *, system):
        self.stream_calls += 1
        if False:
            yield ""

    async def complete(self, messages, *, system) -> str:
        return ""


def test_router_lazy_constructs_clients():
    factory_calls: list[str] = []

    def factory(name: str) -> _FakeModel:
        factory_calls.append(name)
        return _FakeModel(name)

    cfg = RoutingConfig(default="default")
    router = ModelRouter(routing=cfg, client_factory=factory)
    assert factory_calls == []  # 构造时未调
    router.select(category=TaskCategory.FILE_EDIT, tool=None)
    assert factory_calls == ["default"]


def test_router_caches_client_across_selects():
    factory_calls: list[str] = []

    def factory(name: str) -> _FakeModel:
        factory_calls.append(name)
        return _FakeModel(name)

    cfg = RoutingConfig(default="default")
    router = ModelRouter(routing=cfg, client_factory=factory)
    router.select(category=TaskCategory.FILE_EDIT, tool=None)
    router.select(category=TaskCategory.SIMPLE_READ, tool=None)
    # 第二次也走 default tier,工厂只调一次
    assert factory_calls == ["default"]


def test_router_select_returns_decision_with_step():
    def factory(name: str) -> _FakeModel:
        return _FakeModel(name)
    cfg = RoutingConfig(default="default")
    router = ModelRouter(routing=cfg, client_factory=factory)
    client, decision = router.select(
        category=TaskCategory.FILE_EDIT, tool="edit_file", step=3,
    )
    assert isinstance(client, _FakeModel)
    assert decision.step == 3
    assert decision.category == TaskCategory.FILE_EDIT
    assert decision.tool == "edit_file"


def test_router_history_appends_and_caps_at_10():
    def factory(name: str) -> _FakeModel:
        return _FakeModel(name)
    cfg = RoutingConfig(default="default")
    router = ModelRouter(routing=cfg, client_factory=factory)
    for i in range(15):
        router.select(category=TaskCategory.SIMPLE_READ, tool=None, step=i)
    hist = router.history()
    assert len(hist) == 10
    # 最早的 5 个被裁掉;第 6 步应是 step=5
    assert hist[0].step == 5
    assert hist[-1].step == 14


def test_router_history_returns_snapshot_not_deque():
    def factory(name: str) -> _FakeModel:
        return _FakeModel(name)
    cfg = RoutingConfig(default="default")
    router = ModelRouter(routing=cfg, client_factory=factory)
    router.select(category=TaskCategory.SIMPLE_READ, tool=None)
    hist = router.history()
    assert isinstance(hist, list)


def test_effort_settings_low_medium_high_mapped():
    assert EFFORT_PRESETS[EffortLevel.LOW].max_steps == 8
    assert EFFORT_PRESETS[EffortLevel.MEDIUM].max_steps == 40
    assert EFFORT_PRESETS[EffortLevel.HIGH].max_steps == 80


def test_effort_low_uses_auto_approval():
    s = effort_settings(EffortLevel.LOW)
    assert s.approval_level == ApprovalLevel.AUTO


def test_effort_medium_high_use_confirm():
    assert effort_settings(EffortLevel.MEDIUM).approval_level == ApprovalLevel.CONFIRM
    assert effort_settings(EffortLevel.HIGH).approval_level == ApprovalLevel.CONFIRM


def test_router_force_confirm_via_routing_config():
    def factory(name: str) -> _FakeModel:
        return _FakeModel(name)
    cfg = RoutingConfig(default="default", by_category={"file_edit": "strong"},
                        tier_force_confirm=["strong"])
    router = ModelRouter(routing=cfg, client_factory=factory)
    assert router.routing.is_force_confirm("strong") is True
    assert router.routing.is_force_confirm("default") is False


def test_router_routing_property_returns_config():
    def factory(name: str) -> _FakeModel:
        return _FakeModel(name)
    cfg = RoutingConfig(default="default", by_category={"file_edit": "cheap"})
    router = ModelRouter(routing=cfg, client_factory=factory)
    assert router.routing is cfg
