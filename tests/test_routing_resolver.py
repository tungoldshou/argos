"""#11 T3 RoutingResolver 3 层优先级 测试。"""
from argos.routing.categorizer import TaskCategory
from argos.routing.config import RoutingConfig
from argos.routing.resolver import resolve


def test_resolve_by_tool_wins_over_category():
    cfg = RoutingConfig(
        default="default",
        by_category={"file_edit": "strong"},
        by_tool={"edit_file": "cheap"},
    )
    d = resolve(cfg, category=TaskCategory.FILE_EDIT, tool="edit_file")
    assert d.tier == "cheap"
    assert d.source == "by_tool"


def test_resolve_by_category_used_when_no_tool_match():
    cfg = RoutingConfig(
        default="default",
        by_category={"file_edit": "cheap"},
        by_tool={"edit_file": "strong"},
    )
    d = resolve(cfg, category=TaskCategory.FILE_EDIT, tool="read_file")
    assert d.tier == "cheap"
    assert d.source == "by_category"


def test_resolve_default_when_no_match():
    cfg = RoutingConfig(default="default", by_category={}, by_tool={})
    d = resolve(cfg, category=TaskCategory.FILE_EDIT, tool="edit_file")
    assert d.tier == "default"
    assert d.source == "default"


def test_resolve_none_tool_skips_by_tool_layer():
    cfg = RoutingConfig(
        default="default",
        by_category={"file_edit": "cheap"},
        by_tool={"edit_file": "strong"},
    )
    d = resolve(cfg, category=TaskCategory.FILE_EDIT, tool=None)
    assert d.tier == "cheap"
    assert d.source == "by_category"


def test_resolve_decision_carries_source_label():
    cfg = RoutingConfig(default="default", by_tool={"edit_file": "strong"})
    d = resolve(cfg, category=TaskCategory.FILE_EDIT, tool="edit_file")
    assert d.source in ("by_tool", "by_category", "default")


def test_resolve_decision_carries_category_and_tool():
    cfg = RoutingConfig(default="default", by_tool={"edit_file": "strong"})
    d = resolve(cfg, category=TaskCategory.FILE_EDIT, tool="edit_file")
    assert d.category == TaskCategory.FILE_EDIT
    assert d.tool == "edit_file"
    assert d.tier == "strong"


def test_resolve_decision_step_default_zero():
    cfg = RoutingConfig(default="default")
    d = resolve(cfg, category=TaskCategory.SIMPLE_READ, tool=None)
    assert d.step == 0
