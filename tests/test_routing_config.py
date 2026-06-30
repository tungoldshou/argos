"""#11 T2 RoutingConfig 加载 + set_category 原子写 + tier fail-closed 测试。"""
import json
import os
from pathlib import Path

import pytest

from argos.config import ConfigError
from argos.routing.categorizer import TaskCategory
from argos.routing.config import RoutingConfig, load_routing, set_category


def _write_config(dir_: Path, *, models: dict, routing: dict | None = None) -> None:
    raw: dict = {"models": models, "active": "default"}
    if routing is not None:
        raw["routing"] = routing
    (dir_ / "config.json").write_text(json.dumps(raw, indent=2))


def test_load_routing_no_file_returns_builtin_default(tmp_path, monkeypatch):
    """无 config.json → 返内置默认映射(出厂激活):by_category 有 cheap/strong 分组,is_active()=True。"""
    monkeypatch.chdir(tmp_path)
    from argos.routing.config import _DEFAULT_BY_CATEGORY
    cfg = load_routing(tmp_path)
    assert cfg.default == "default"
    assert cfg.by_category == _DEFAULT_BY_CATEGORY
    assert cfg.by_tool == {}
    assert cfg.tier_force_confirm == []
    assert cfg.is_active() is True


def test_load_routing_no_routing_section_returns_builtin_default(tmp_path):
    """config.json 无 routing 段 → 返内置默认映射(出厂激活)。"""
    _write_config(tmp_path, models={"default": {"protocol": "anthropic", "base_url": "x", "model": "m"}})
    from argos.routing.config import _DEFAULT_BY_CATEGORY
    cfg = load_routing(tmp_path)
    assert cfg.default == "default"
    assert cfg.by_category == _DEFAULT_BY_CATEGORY
    assert cfg.is_active() is True


def test_load_routing_parses_all_fields(tmp_path):
    _write_config(tmp_path,
                  models={"cheap": {}, "default": {}, "strong": {}},
                  routing={
                      "default": "default",
                      "by_category": {"file_edit": "cheap", "verify": "strong"},
                      "by_tool": {"run_command": "cheap"},
                      "tier_force_confirm": ["strong"],
                  })
    cfg = load_routing(tmp_path)
    assert cfg.default == "default"
    assert cfg.by_category == {"file_edit": "cheap", "verify": "strong"}
    assert cfg.by_tool == {"run_command": "cheap"}
    assert cfg.tier_force_confirm == ["strong"]


def test_load_routing_invalid_category_raises(tmp_path):
    _write_config(tmp_path, models={"default": {}},
                  routing={"by_category": {"foo_bar": "cheap"}})
    with pytest.raises(ConfigError, match="foo_bar"):
        load_routing(tmp_path)


def test_load_routing_garbage_json_raises(tmp_path):
    (tmp_path / "config.json").write_text("not json")
    with pytest.raises(ConfigError, match="config.json 解析失败"):
        load_routing(tmp_path)


def test_set_category_writes_to_config_atomically(tmp_path):
    _write_config(tmp_path, models={"default": {}, "cheap": {}, "strong": {}})
    new = set_category(tmp_path, TaskCategory.FILE_EDIT, "cheap")
    assert new.by_category["file_edit"] == "cheap"
    # 读回磁盘也一致
    cfg = load_routing(tmp_path)
    assert cfg.by_category["file_edit"] == "cheap"


def test_set_category_unknown_tier_raises(tmp_path):
    _write_config(tmp_path, models={"default": {}, "cheap": {}})
    with pytest.raises(ConfigError, match="srong"):
        set_category(tmp_path, TaskCategory.FILE_EDIT, "srong")


def test_set_category_persists_across_reload(tmp_path):
    _write_config(tmp_path, models={"default": {}, "strong": {}})
    set_category(tmp_path, TaskCategory.VERIFY, "strong")
    cfg = load_routing(tmp_path)
    assert cfg.by_category["verify"] == "strong"


def test_routing_config_is_force_confirm():
    cfg = RoutingConfig(tier_force_confirm=["strong"])
    assert cfg.is_force_confirm("strong") is True
    assert cfg.is_force_confirm("cheap") is False


def test_routing_config_is_active_default_false():
    """bare RoutingConfig() with no by_category/by_tool/tier_force_confirm and default tier
    name is still inactive — the out-of-the-box active config comes from _BUILTIN_DEFAULT via
    load_routing(), not from a bare RoutingConfig().  A hand-constructed bare RoutingConfig()
    is still inactive because all fields are empty and default=="default"."""
    assert RoutingConfig().is_active() is False


@pytest.mark.parametrize("cfg", [
    RoutingConfig(by_category={"file_edit": "cheap"}),
    RoutingConfig(by_tool={"run_command": "strong"}),
    RoutingConfig(tier_force_confirm=["strong"]),
    RoutingConfig(default="strong"),
])
def test_routing_config_is_active_when_configured(cfg):
    """配了 by_category / by_tool / tier_force_confirm / 非默认 default → 活跃。"""
    assert cfg.is_active() is True


def test_load_routing_active_by_default(tmp_path):
    """默认配置(无 config.json)→ load_routing 返内置默认映射且 is_active() True(自主性 flip)。
    原 test_build_components_router_none_when_routing_inactive 的断言取反并移至 load_routing 层,
    避免 build_components 需要真 API key 才能运行。"""
    cfg = load_routing(tmp_path)
    assert cfg.is_active() is True, "内置默认映射出厂激活,is_active() 应为 True"
    from argos.routing.resolver import resolve
    assert resolve(cfg, category=TaskCategory.SIMPLE_READ, tool=None).tier == "cheap"
    assert resolve(cfg, category=TaskCategory.REFACTOR, tool=None).tier == "strong"
