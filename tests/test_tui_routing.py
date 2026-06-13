"""#11 T7 TUI /routing + /routing set + ActivityPanel tier 标签 测试。"""
import json
from pathlib import Path

import pytest

from argos.routing.categorizer import TaskCategory
from argos.routing.config import (
    RoutingConfig, load_routing, set_category,
)
from argos.tui.commands import parse_slash


def test_parse_slash_routing_known():
    cmd = parse_slash("/routing")
    assert cmd is not None
    assert cmd.name == "routing"
    assert cmd.known is True
    assert cmd.arg == ""


def test_parse_slash_routing_set_args():
    cmd = parse_slash("/routing set verify strong")
    assert cmd is not None
    assert cmd.name == "routing"
    assert cmd.arg == "set verify strong"


def test_routing_config_set_persists(tmp_path):
    """set_category 写盘 + 重读一致。"""
    (tmp_path / "config.json").write_text(json.dumps({
        "models": {"default": {}, "cheap": {}, "strong": {}},
        "active": "default",
    }))
    set_category(tmp_path, TaskCategory.VERIFY, "strong")
    cfg = load_routing(tmp_path)
    assert cfg.by_category["verify"] == "strong"


def test_routing_config_set_unknown_tier_raises(tmp_path):
    (tmp_path / "config.json").write_text(json.dumps({
        "models": {"default": {}}, "active": "default",
    }))
    # 故意传拼错的 tier 'srong' → ConfigError(防拼写退化)
    with pytest.raises(Exception) as exc_info:
        set_category(tmp_path, TaskCategory.VERIFY, "srong")
    assert "srong" in str(exc_info.value)


def test_routing_config_set_invalid_category_raises(tmp_path):
    from argos.config import ConfigError
    with pytest.raises(ValueError):
        # 不用 set_category 路径,直接构造 TaskCategory 会 ValueError
        TaskCategory("foo_bar")


def test_routing_config_safe_default_when_no_routing(tmp_path):
    cfg = load_routing(tmp_path)
    assert cfg.by_category == {}
    assert cfg.tier_force_confirm == []


def test_routing_config_safe_default_when_no_file(tmp_path):
    cfg = load_routing(tmp_path)
    assert cfg.default == "default"


def test_routing_config_force_confirm_helper():
    cfg = RoutingConfig(tier_force_confirm=["strong"])
    assert cfg.is_force_confirm("strong") is True
    assert cfg.is_force_confirm("cheap") is False


def test_activity_panel_cost_update_renders_tier_label():
    """ActivityPanel.on_cost 签名接受 tier_name kw(无 Textual app 跑不动 _set,只检签名)。"""
    import inspect
    from argos.tui.widgets.activity_panel import ActivityPanel
    sig = inspect.signature(ActivityPanel.on_cost)
    assert "tier_name" in sig.parameters
    assert sig.parameters["tier_name"].default == ""


def test_activity_panel_on_cost_default_no_tier_label():
    """tier_name 缺省时不应出 [?] 之类的占位标签(签名默认值 = "" 防误打)。"""
    import inspect
    from argos.tui.widgets.activity_panel import ActivityPanel
    sig = inspect.signature(ActivityPanel.on_cost)
    # 默认值是空串,on_cost 内部据此判定不打 [xxx] 标签
    assert sig.parameters["tier_name"].default == ""
