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


def test_load_routing_no_file_returns_safe_default(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg = load_routing(tmp_path)
    assert cfg.default == "default"
    assert cfg.by_category == {}
    assert cfg.by_tool == {}
    assert cfg.tier_force_confirm == []


def test_load_routing_no_routing_section_returns_safe_default(tmp_path):
    _write_config(tmp_path, models={"default": {"protocol": "anthropic", "base_url": "x", "model": "m"}})
    cfg = load_routing(tmp_path)
    assert cfg.default == "default"
    assert cfg.by_category == {}


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
