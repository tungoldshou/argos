"""permissions.json 配置加载 + 校验 + reload 单元测试(spec §2.5, D3 / D19)。"""
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
    """空 matcher = 全匹配(spec §2.5 锁);"*" 也行。"""
    RuleEntry(tool="x", matcher="")
    RuleEntry(tool="x", matcher="*")


def test_permissions_config_empty():
    """PermissionsConfig.empty() → 无规则,default_level=None(D20 沿用 gate.level)。"""
    cfg = PermissionsConfig.empty()
    assert cfg.version == 1
    assert cfg.default_level is None
    assert cfg.tools == {}
    assert cfg.allow == ()
    assert cfg.deny == ()
    assert cfg.ask == ()


def test_permissions_config_construction():
    """手工构造合法配置。"""
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
    """无 permissions.json → EmptyPermissionsConfig(D20 锁)。"""
    from argos.permissions import config as _cfg
    monkeypatch.setattr(_cfg, "CONFIG_PATH", tmp_path / "permissions.json")
    cfg = _cfg.load()
    assert isinstance(cfg, PermissionsConfig)
    assert cfg.allow == ()


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


def test_load_wrong_version_raises(tmp_path, monkeypatch):
    from argos.permissions import config as _cfg
    p = tmp_path / "permissions.json"
    p.write_text(json.dumps({"version": 99}))
    monkeypatch.setattr(_cfg, "CONFIG_PATH", p)
    with pytest.raises(PermissionsConfigError, match="version"):
        _cfg.load()


def test_load_bad_regex_skipped_not_raises(tmp_path, monkeypatch):
    """坏 regex 不抛,只跳过该 entry(不整体禁用,防"一条 rule 写错 = 全部失效")。"""
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
    cfg = _cfg.load()  # 不抛
    assert len(cfg.allow) == 1  # 只 1 条好的


def test_reload_config_keeps_old_on_failure(tmp_path, monkeypatch):
    """坏配置 reload → 保旧 + 报错。"""
    from argos.permissions.config import reload_config as _reload
    from argos.permissions import config as _cfg
    monkeypatch.setattr(_cfg, "CONFIG_PATH", tmp_path / "permissions.json")
    _cfg._reset_config()
    # 先放一个合法配置
    (tmp_path / "permissions.json").write_text(json.dumps({"version": 1}))
    _reload()
    # 改坏
    (tmp_path / "permissions.json").write_text("not json")
    with pytest.raises(PermissionsConfigError):
        _reload()
    # 旧配置保留:reload 后仍是合法的旧 config
    cfg = _cfg.get_config()
    assert isinstance(cfg, PermissionsConfig)
    assert cfg.allow == ()


def test_reload_config_picks_up_new(tmp_path, monkeypatch):
    """合法新 config → 切换生效。"""
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
