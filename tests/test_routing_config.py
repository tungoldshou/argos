"""Internal documentation."""
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
    """Internal documentation."""
    monkeypatch.chdir(tmp_path)
    from argos.routing.config import _DEFAULT_BY_CATEGORY
    cfg = load_routing(tmp_path)
    assert cfg.default == "default"
    assert cfg.by_category == _DEFAULT_BY_CATEGORY
    assert cfg.by_tool == {}
    assert cfg.tier_force_confirm == []
    assert cfg.is_active() is True


def test_load_routing_no_routing_section_returns_builtin_default(tmp_path):
    """Internal documentation."""
    _write_config(tmp_path, models={"default": {"protocol": "anthropic", "base_url": "x", "model": "m"}})
    from argos.routing.config import _DEFAULT_BY_CATEGORY
    cfg = load_routing(tmp_path)
    assert cfg.default == "default"
    assert cfg.by_category == _DEFAULT_BY_CATEGORY
    assert cfg.is_active() is True


def test_load_routing_non_object_routing_raises(tmp_path):
    """Malformed routing config must not be silently treated as missing config."""
    (tmp_path / "config.json").write_text(json.dumps({
        "models": {"default": {}},
        "active": "default",
        "routing": [],
    }))

    with pytest.raises(ConfigError, match="routing"):
        load_routing(tmp_path)


def test_load_routing_non_object_by_category_raises(tmp_path):
    _write_config(tmp_path,
                  models={"default": {}, "cheap": {}},
                  routing={"by_category": [["file_edit", "cheap"]]})

    with pytest.raises(ConfigError, match="by_category"):
        load_routing(tmp_path)


def test_load_routing_non_string_default_raises(tmp_path):
    _write_config(tmp_path,
                  models={"default": {}, "strong": {}},
                  routing={"default": False, "by_category": {"verify": "strong"}})

    with pytest.raises(ConfigError, match="default"):
        load_routing(tmp_path)


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


def test_load_routing_unknown_tier_raises(tmp_path):
    _write_config(tmp_path, models={"default": {}, "cheap": {}},
                  routing={"by_category": {"file_edit": "srong"}})
    with pytest.raises(ConfigError, match="srong"):
        load_routing(tmp_path)


def test_load_routing_garbage_json_raises(tmp_path):
    (tmp_path / "config.json").write_text("not json")
    with pytest.raises(ConfigError, match="config.json 解析失败"):
        load_routing(tmp_path)


def test_set_category_non_utf8_config_raises_config_error(tmp_path):
    (tmp_path / "config.json").write_bytes(b"\xff\xfe")

    with pytest.raises(ConfigError, match="config.json"):
        set_category(tmp_path, TaskCategory.VERIFY, "strong")


def test_set_category_writes_to_config_atomically(tmp_path):
    _write_config(tmp_path, models={"default": {}, "cheap": {}, "strong": {}})
    new = set_category(tmp_path, TaskCategory.FILE_EDIT, "cheap")
    assert new.by_category["file_edit"] == "cheap"
    cfg = load_routing(tmp_path)
    assert cfg.by_category["file_edit"] == "cheap"


def test_set_category_uses_active_as_default_when_routing_default_missing(tmp_path):
    (tmp_path / "config.json").write_text(json.dumps({
        "active": "local",
        "models": {"local": {}, "strong": {}},
    }))
    new = set_category(tmp_path, TaskCategory.VERIFY, "strong")
    assert new.default == "local"
    assert new.by_category["verify"] == "strong"


def test_set_category_unknown_tier_raises(tmp_path):
    _write_config(tmp_path, models={"default": {}, "cheap": {}})
    with pytest.raises(ConfigError, match="srong"):
        set_category(tmp_path, TaskCategory.FILE_EDIT, "srong")


def test_set_category_rejects_non_object_existing_routing_without_writing(tmp_path):
    original = {
        "active": "default",
        "models": {"default": {}, "strong": {}},
        "routing": [],
    }
    (tmp_path / "config.json").write_text(json.dumps(original))

    with pytest.raises(ConfigError, match="routing"):
        set_category(tmp_path, TaskCategory.VERIFY, "strong")

    assert json.loads((tmp_path / "config.json").read_text()) == original


def test_set_category_rejects_non_object_existing_by_tool_without_writing(tmp_path):
    original = {
        "active": "default",
        "models": {"default": {}, "cheap": {}, "strong": {}},
        "routing": {"by_tool": [["run_command", "cheap"]]},
    }
    (tmp_path / "config.json").write_text(json.dumps(original))

    with pytest.raises(ConfigError, match="by_tool"):
        set_category(tmp_path, TaskCategory.VERIFY, "strong")

    assert json.loads((tmp_path / "config.json").read_text()) == original


def test_set_category_rejects_non_string_existing_default_without_writing(tmp_path):
    original = {
        "active": "default",
        "models": {"default": {}, "strong": {}},
        "routing": {"default": False},
    }
    (tmp_path / "config.json").write_text(json.dumps(original))

    with pytest.raises(ConfigError, match="default"):
        set_category(tmp_path, TaskCategory.VERIFY, "strong")

    assert json.loads((tmp_path / "config.json").read_text()) == original


def test_set_category_rejects_invalid_existing_routing_without_writing(tmp_path):
    _write_config(tmp_path, models={"default": {}, "strong": {}},
                  routing={"by_tool": {"run_command": "srong"}})
    with pytest.raises(ConfigError, match="srong"):
        set_category(tmp_path, TaskCategory.VERIFY, "strong")
    raw = json.loads((tmp_path / "config.json").read_text())
    assert raw["routing"].get("by_category") is None


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
    """Internal documentation."""
    assert cfg.is_active() is True


def test_load_routing_active_by_default(tmp_path):
    """Internal documentation."""
    cfg = load_routing(tmp_path)
    assert cfg.is_active() is True, "内置默认映射出厂激活,is_active() 应为 True"
    from argos.routing.resolver import resolve
    assert resolve(cfg, category=TaskCategory.SIMPLE_READ, tool=None).tier == "cheap"
    assert resolve(cfg, category=TaskCategory.REFACTOR, tool=None).tier == "strong"
