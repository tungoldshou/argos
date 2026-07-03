from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from argos.permissions.config import (
    PermissionsConfig,
    RuleEntry,
    ToolLevelOverride,
    PermissionsConfigError,
)


def test_rule_entry_frozen():
    e = RuleEntry(tool="run_command", matcher=r"^ls ")
    assert e.tool == "run_command"
    assert e.matcher == r"^ls "
    with pytest.raises(FrozenInstanceError):
        e.tool = "x"  # type: ignore[misc]


def test_rule_entry_empty_matcher_allowed():
    RuleEntry(tool="x", matcher="")
    RuleEntry(tool="x", matcher="*")


def test_permissions_config_empty():
    cfg = PermissionsConfig.empty()
    assert cfg.version == 1
    assert cfg.default_level is None
    assert cfg.tools == {}
    assert cfg.allow == ()
    assert cfg.deny == ()
    assert cfg.ask == ()


def test_permissions_config_construction():
    cfg = PermissionsConfig(
        version=1,
        default_level="confirm",
        tools={"read_file": "auto"},
        allow=(RuleEntry(tool="run_command", matcher=r"^ls "),),
        deny=(),
        ask=(),
    )
    assert cfg.default_level == "confirm"
    assert cfg.tools == {"read_file": "auto"}
    assert len(cfg.allow) == 1


def test_invalid_default_level_raises():
    with pytest.raises(ValueError, match="default_level"):
        PermissionsConfig(version=1, default_level="YOLO")


def test_invalid_tool_level_raises():
    with pytest.raises(ValueError, match="tool level"):
        PermissionsConfig(version=1, tools={"x": "yolo"})


def test_load_nonexistent_returns_empty(tmp_path, monkeypatch):
    from argos.permissions import config as _cfg
    monkeypatch.setattr(_cfg, "CONFIG_PATH", tmp_path / "permissions.json")
    cfg = _cfg.load()
    assert isinstance(cfg, PermissionsConfig)
    assert cfg.allow == ()


def test_default_path_honors_argos_config_dir(tmp_path, monkeypatch):
    from argos import config as C
    from argos.permissions import config as _cfg

    cfg_dir = tmp_path / "cfg"
    p = cfg_dir / "permissions.json"
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps({"version": 1}))
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(cfg_dir))
    monkeypatch.setattr(C, "_ENV", {})
    monkeypatch.setattr(_cfg, "CONFIG_PATH", None)

    assert _cfg.load().version == 1


def test_save_allow_rule_default_path_honors_argos_config_dir(tmp_path, monkeypatch):
    from argos import config as C
    from argos.permissions import config as _cfg

    cfg_dir = tmp_path / "cfg"
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(cfg_dir))
    monkeypatch.setattr(C, "_ENV", {})
    monkeypatch.setattr(_cfg, "CONFIG_PATH", None)
    _cfg._reset_config()

    assert _cfg.save_allow_rule("run_command", r"^pytest")
    assert (cfg_dir / "permissions.json").exists()
    assert _cfg.get_config().match_allow("run_command", "pytest -q") is not None


def test_load_valid_json(tmp_path, monkeypatch):
    from argos.permissions import config as _cfg
    p = tmp_path / "permissions.json"
    p.write_text(json.dumps({
        "version": 1,
        "default_level": "auto",
        "tools": {"read_file": "auto"},
        "allow": [{"tool": "run_command", "matcher": r"^ls "}],
        "deny": [],
        "ask": [],
    }))
    monkeypatch.setattr(_cfg, "CONFIG_PATH", p)
    cfg = _cfg.load()
    assert cfg.default_level == "auto"
    assert cfg.tools == {"read_file": "auto"}
    assert len(cfg.allow) == 1


def test_load_bad_json_raises(tmp_path, monkeypatch):
    from argos.permissions import config as _cfg
    p = tmp_path / "permissions.json"
    p.write_text("{not json")
    monkeypatch.setattr(_cfg, "CONFIG_PATH", p)
    with pytest.raises(PermissionsConfigError, match="JSON"):
        _cfg.load()


def test_get_config_bad_json_fails_closed_observe(tmp_path, monkeypatch):
    from argos.permissions import config as _cfg
    from argos.permissions.evaluator import evaluate

    p = tmp_path / "permissions.json"
    p.write_text("{not json")
    monkeypatch.setattr(_cfg, "CONFIG_PATH", p)
    _cfg._reset_config()

    cfg = _cfg.get_config()
    assert cfg.default_level == "observe"
    meta = evaluate(
        "run_command",
        {"command": "pytest -q"},
        gate_level="confirm",
        config=cfg,
        low_risk_auto=True,
        risk="medium",
    )
    assert meta.decision == "deny"


def test_load_wrong_version_raises(tmp_path, monkeypatch):
    from argos.permissions import config as _cfg
    p = tmp_path / "permissions.json"
    p.write_text(json.dumps({"version": 99}))
    monkeypatch.setattr(_cfg, "CONFIG_PATH", p)
    with pytest.raises(PermissionsConfigError, match="version"):
        _cfg.load()


def test_load_bad_regex_skipped_not_raises(tmp_path, monkeypatch):
    from argos.permissions import config as _cfg
    p = tmp_path / "permissions.json"
    p.write_text(json.dumps({
        "version": 1,
        "allow": [
            {"tool": "run_command", "matcher": r"^ls "},     # good
            {"tool": "run_command", "matcher": "(unclosed"},   # bad
        ],
    }))
    monkeypatch.setattr(_cfg, "CONFIG_PATH", p)
    cfg = _cfg.load()
    assert len(cfg.allow) == 1


def test_wildcard_matcher_loads_and_matches(tmp_path, monkeypatch):
    from argos.permissions import config as _cfg
    p = tmp_path / "permissions.json"
    p.write_text(json.dumps({
        "version": 1,
        "allow": [
            {"tool": "web_search", "matcher": "*"},
            {"tool": "run_workflow", "matcher": ""},
        ],
    }))
    monkeypatch.setattr(_cfg, "CONFIG_PATH", p)
    cfg = _cfg.load()
    assert len(cfg.allow) == 2, "'*' / '' 全匹配哨兵不应被当坏 regex 丢弃"
    assert cfg.match_allow("web_search", "任意 query") is not None
    assert cfg.match_allow("run_workflow", "anything") is not None
    assert _cfg._is_safe_regex("(unclosed") is False
    assert _cfg._is_safe_regex("a" * 300) is False


def test_reload_config_keeps_old_on_failure(tmp_path, monkeypatch):
    from argos.permissions.config import reload_config as _reload
    from argos.permissions import config as _cfg
    monkeypatch.setattr(_cfg, "CONFIG_PATH", tmp_path / "permissions.json")
    _cfg._reset_config()
    (tmp_path / "permissions.json").write_text(json.dumps({"version": 1}))
    _reload()
    (tmp_path / "permissions.json").write_text("not json")
    with pytest.raises(PermissionsConfigError):
        _reload()
    cfg = _cfg.get_config()
    assert isinstance(cfg, PermissionsConfig)
    assert cfg.allow == ()


def test_reload_config_first_failure_caches_observe_fail_closed(tmp_path, monkeypatch):
    from argos.permissions.config import reload_config as _reload
    from argos.permissions import config as _cfg
    monkeypatch.setattr(_cfg, "CONFIG_PATH", tmp_path / "permissions.json")
    _cfg._reset_config()
    (tmp_path / "permissions.json").write_text("not json")

    with pytest.raises(PermissionsConfigError):
        _reload()

    assert _cfg.get_config().default_level == "observe"


def test_reload_config_picks_up_new(tmp_path, monkeypatch):
    from argos.permissions.config import reload_config as _reload
    from argos.permissions import config as _cfg
    monkeypatch.setattr(_cfg, "CONFIG_PATH", tmp_path / "permissions.json")
    _cfg._reset_config()
    (tmp_path / "permissions.json").write_text(json.dumps({
        "version": 1,
        "allow": [{"tool": "run_command", "matcher": r"^pytest"}],
    }))
    cfg = _reload()
    assert len(cfg.allow) == 1
