from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from argos.hooks.config import (
    HookHandler,
    HookMatcherEntry,
    HooksConfig,
    HooksConfigError,
    load,
)
from argos.hooks.matcher import match
from argos.hooks import get_config, reload_config


def test_hook_handler_frozen_dataclass():
    h = HookHandler(type="command", command="echo ok", timeout=5000)
    assert h.type == "command"
    assert h.command == "echo ok"
    assert h.timeout == 5000
    with pytest.raises(FrozenInstanceError):
        h.command = "other"  # type: ignore[misc]


def test_hook_handler_default_timeout():
    h = HookHandler(type="command", command="echo ok")
    assert h.timeout == 60000


def test_hook_handler_invalid_type_raises():
    with pytest.raises(ValueError):
        HookHandler(type="python", command="print(1)")


def test_hook_handler_invalid_timeout_raises():
    with pytest.raises(ValueError):
        HookHandler(type="command", command="echo ok", timeout=0)
    with pytest.raises(ValueError):
        HookHandler(type="command", command="echo ok", timeout=-1)


def test_matcher_entry_construction():
    h1 = HookHandler(type="command", command="echo 1")
    e = HookMatcherEntry(matcher="write_file|edit_file", hooks=(h1,))
    assert e.matcher == "write_file|edit_file"
    assert list(e.hooks) == [h1]


def test_matcher_entry_empty_matcher():
    h = HookHandler(type="command", command="echo")
    e = HookMatcherEntry(matcher=None, hooks=(h,))
    assert e.matcher is None


def test_hooks_config_empty():
    cfg = HooksConfig.empty()
    assert cfg.version == 1
    assert cfg.entries == {}   # dict[event_name, list[HookMatcherEntry]]


def test_hooks_config_construction_with_entries():
    e = HookMatcherEntry(
        matcher="write_file",
        hooks=(HookHandler(type="command", command="echo a"),),
    )
    cfg = HooksConfig(entries={"PreToolUse": [e]})
    assert "PreToolUse" in cfg.entries
    assert len(cfg.entries["PreToolUse"]) == 1


def test_hooks_config_error_is_exception():
    err = HooksConfigError("bad json")
    assert isinstance(err, Exception)
    assert "bad json" in str(err)



def _h(cmd: str) -> HookHandler:
    return HookHandler(type="command", command=cmd)


def _entry(matcher, cmds):
    return HookMatcherEntry(matcher=matcher, hooks=tuple(_h(c) for c in cmds))


def test_match_regex_or():
    cfg = HooksConfig(entries={"PreToolUse": [_entry("write_file|edit_file", ["h1"])]})
    assert len(match("PreToolUse", ["write_file"], cfg)) == 1
    assert len(match("PreToolUse", ["edit_file", "x"], cfg)) == 1
    assert len(match("PreToolUse", ["read_file"], cfg)) == 0


def test_match_star_wildcard():
    cfg = HooksConfig(entries={"PreToolUse": [_entry("*", ["h1"])]})
    assert len(match("PreToolUse", ["write_file"], cfg)) == 1
    assert len(match("PreToolUse", [], cfg)) == 1


def test_match_empty_matcher_means_star():
    cfg = HooksConfig(entries={"PreToolUse": [_entry(None, ["h1"]), _entry("", ["h2"])]})
    assert len(match("PreToolUse", ["x"], cfg)) == 2


def test_match_multi_entry_merge_dedup():
    e1 = _entry("write_file", ["a", "b"])
    e2 = _entry("write_file", ["b", "c"])
    cfg = HooksConfig(entries={"PreToolUse": [e1, e2]})
    result = match("PreToolUse", ["write_file"], cfg)
    assert len(result) == 3
    assert {h.command for h in result} == {"a", "b", "c"}


def test_match_non_pre_post_event_ignores_matcher():
    cfg = HooksConfig(entries={"Stop": [_entry("write_file", ["a"]), _entry(None, ["b"])]})
    result = match("Stop", [], cfg)
    assert len(result) == 2
    assert {h.command for h in result} == {"a", "b"}


def test_match_unknown_event_returns_empty():
    cfg = HooksConfig(entries={"PreToolUse": [_entry("*", ["a"])]})
    assert match("UnknownEvent", ["x"], cfg) == []


def test_match_invalid_regex_ignored():
    e1 = _entry("[invalid(regex", ["bad"])
    e2 = _entry("write_file", ["good"])
    cfg = HooksConfig(entries={"PreToolUse": [e1, e2]})
    result = match("PreToolUse", ["write_file"], cfg)
    assert len(result) == 1
    assert result[0].command == "good"



def test_load_default_path_honors_argos_config_dir(tmp_path, monkeypatch):
    from argos import config as C
    from argos.hooks import config as HC

    cfg_dir = tmp_path / "cfg"
    hooks_file = cfg_dir / "hooks.json"
    hooks_file.parent.mkdir(parents=True)
    hooks_file.write_text(json.dumps({"version": 1, "hooks": {}}))
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(cfg_dir))
    monkeypatch.setattr(C, "_ENV", {})
    monkeypatch.setattr(HC, "HOOKS_CONFIG_PATH", None)

    assert load().entries == {}


def test_load_missing_file_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "argos.hooks.config.HOOKS_CONFIG_PATH", tmp_path / "hooks.json"
    )
    cfg = load()
    assert cfg.entries == {}


def test_load_valid_minimal(tmp_path, monkeypatch):
    p = tmp_path / "hooks.json"
    p.write_text(json.dumps({"version": 1, "hooks": {}}))
    monkeypatch.setattr("argos.hooks.config.HOOKS_CONFIG_PATH", p)
    cfg = load()
    assert cfg.version == 1
    assert cfg.entries == {}


def test_load_valid_with_event_and_matcher(tmp_path, monkeypatch):
    p = tmp_path / "hooks.json"
    p.write_text(json.dumps({
        "version": 1,
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "write_file|edit_file",
                    "hooks": [
                        {"type": "command", "command": "echo audit", "timeout": 5000},
                    ],
                },
            ],
        },
    }))
    monkeypatch.setattr("argos.hooks.config.HOOKS_CONFIG_PATH", p)
    cfg = load()
    pre = cfg.entries["PreToolUse"]
    assert len(pre) == 1
    assert pre[0].matcher == "write_file|edit_file"
    assert pre[0].hooks[0].command == "echo audit"
    assert pre[0].hooks[0].timeout == 5000


def test_load_invalid_json_raises(tmp_path, monkeypatch):
    p = tmp_path / "hooks.json"
    p.write_text("{not valid json")
    monkeypatch.setattr("argos.hooks.config.HOOKS_CONFIG_PATH", p)
    with pytest.raises(HooksConfigError):
        load()


def test_get_config_invalid_json_raises_not_empty(tmp_path, monkeypatch):
    import argos.hooks as hooks

    p = tmp_path / "hooks.json"
    p.write_text("{not valid json")
    monkeypatch.setattr("argos.hooks.config.HOOKS_CONFIG_PATH", p)
    hooks._reset_config()

    with pytest.raises(HooksConfigError):
        hooks.get_config()


def test_load_missing_version_raises(tmp_path, monkeypatch):
    p = tmp_path / "hooks.json"
    p.write_text(json.dumps({"hooks": {}}))
    monkeypatch.setattr("argos.hooks.config.HOOKS_CONFIG_PATH", p)
    with pytest.raises(HooksConfigError, match="version"):
        load()


def test_load_wrong_version_raises(tmp_path, monkeypatch):
    p = tmp_path / "hooks.json"
    p.write_text(json.dumps({"version": 2, "hooks": {}}))
    monkeypatch.setattr("argos.hooks.config.HOOKS_CONFIG_PATH", p)
    with pytest.raises(HooksConfigError, match="version"):
        load()


def test_load_unknown_event_raises(tmp_path, monkeypatch):
    p = tmp_path / "hooks.json"
    p.write_text(json.dumps({
        "version": 1,
        "hooks": {"NotARealEvent": [{"hooks": [{"type": "command", "command": "x"}]}]},
    }))
    monkeypatch.setattr("argos.hooks.config.HOOKS_CONFIG_PATH", p)
    with pytest.raises(HooksConfigError, match="event"):
        load()


def test_load_matcher_not_string_raises(tmp_path, monkeypatch):
    p = tmp_path / "hooks.json"
    p.write_text(json.dumps({
        "version": 1,
        "hooks": {"PreToolUse": [{"matcher": 123, "hooks": [{"type": "command", "command": "x"}]}]},
    }))
    monkeypatch.setattr("argos.hooks.config.HOOKS_CONFIG_PATH", p)
    with pytest.raises(HooksConfigError, match="matcher"):
        load()


def test_load_hooks_not_array_raises(tmp_path, monkeypatch):
    p = tmp_path / "hooks.json"
    p.write_text(json.dumps({"version": 1, "hooks": {"PreToolUse": "not_array"}}))
    monkeypatch.setattr("argos.hooks.config.HOOKS_CONFIG_PATH", p)
    with pytest.raises(HooksConfigError, match="array"):
        load()


def test_load_handler_invalid_type_raises(tmp_path, monkeypatch):
    p = tmp_path / "hooks.json"
    p.write_text(json.dumps({
        "version": 1,
        "hooks": {"PreToolUse": [{"hooks": [{"type": "python", "command": "print(1)"}]}]},
    }))
    monkeypatch.setattr("argos.hooks.config.HOOKS_CONFIG_PATH", p)
    with pytest.raises(HooksConfigError, match="type"):
        load()


def test_reload_replaces_singleton(tmp_path, monkeypatch):
    p = tmp_path / "hooks.json"
    p.write_text(json.dumps({"version": 1, "hooks": {}}))
    monkeypatch.setattr("argos.hooks.config.HOOKS_CONFIG_PATH", p)
    cfg1 = reload_config()
    assert cfg1.entries == {}
    p.write_text(json.dumps({
        "version": 1,
        "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "x"}]}]},
    }))
    cfg2 = reload_config()
    assert "Stop" in cfg2.entries
    assert "Stop" in get_config().entries


def test_reload_invalid_keeps_old(tmp_path, monkeypatch):
    from argos.hooks import _config
    p = tmp_path / "hooks.json"
    p.write_text(json.dumps({
        "version": 1,
        "hooks": {"PreToolUse": [{"hooks": [{"type": "command", "command": "old"}]}]},
    }))
    monkeypatch.setattr("argos.hooks.config.HOOKS_CONFIG_PATH", p)
    cfg_old = reload_config()
    p.write_text("{not json")
    with pytest.raises(HooksConfigError):
        reload_config()
    assert get_config() is cfg_old
    assert get_config().entries["PreToolUse"][0].hooks[0].command == "old"




def test_validate_matcher_rejects_overlong(tmp_path, monkeypatch):
    long_matcher = "a" * 257
    p = tmp_path / "hooks.json"
    p.write_text(json.dumps({
        "version": 1,
        "hooks": {"PreToolUse": [
            {"matcher": long_matcher, "hooks": [{"type": "command", "command": "x"}]},
        ]},
    }))
    monkeypatch.setattr("argos.hooks.config.HOOKS_CONFIG_PATH", p)
    with pytest.raises(HooksConfigError, match="长度"):
        load()


def test_validate_matcher_accepts_exactly_256(tmp_path, monkeypatch):
    matcher_256 = "a" * 256
    p = tmp_path / "hooks.json"
    p.write_text(json.dumps({
        "version": 1,
        "hooks": {"PreToolUse": [
            {"matcher": matcher_256, "hooks": [{"type": "command", "command": "x"}]},
        ]},
    }))
    monkeypatch.setattr("argos.hooks.config.HOOKS_CONFIG_PATH", p)
    cfg = load()
    assert cfg.entries["PreToolUse"][0].matcher == matcher_256


def test_validate_matcher_rejects_nested_quantifier_star_star(tmp_path, monkeypatch):
    p = tmp_path / "hooks.json"
    p.write_text(json.dumps({
        "version": 1,
        "hooks": {"PreToolUse": [
            {"matcher": "(.*)*", "hooks": [{"type": "command", "command": "x"}]},
        ]},
    }))
    monkeypatch.setattr("argos.hooks.config.HOOKS_CONFIG_PATH", p)
    with pytest.raises(HooksConfigError, match="嵌套量词"):
        load()


def test_validate_matcher_rejects_nested_quantifier_plus_plus(tmp_path, monkeypatch):
    p = tmp_path / "hooks.json"
    p.write_text(json.dumps({
        "version": 1,
        "hooks": {"PreToolUse": [
            {"matcher": "(.+)+$", "hooks": [{"type": "command", "command": "x"}]},
        ]},
    }))
    monkeypatch.setattr("argos.hooks.config.HOOKS_CONFIG_PATH", p)
    with pytest.raises(HooksConfigError, match="嵌套量词"):
        load()


def test_validate_matcher_rejects_nested_quantifier_star_plus(tmp_path, monkeypatch):
    p = tmp_path / "hooks.json"
    p.write_text(json.dumps({
        "version": 1,
        "hooks": {"PreToolUse": [
            {"matcher": "(.*)+", "hooks": [{"type": "command", "command": "x"}]},
        ]},
    }))
    monkeypatch.setattr("argos.hooks.config.HOOKS_CONFIG_PATH", p)
    with pytest.raises(HooksConfigError, match="嵌套量词"):
        load()


def test_validate_matcher_rejects_unclosed_group(tmp_path, monkeypatch):
    p = tmp_path / "hooks.json"
    p.write_text(json.dumps({
        "version": 1,
        "hooks": {"PreToolUse": [
            {"matcher": "(unclosed", "hooks": [{"type": "command", "command": "x"}]},
        ]},
    }))
    monkeypatch.setattr("argos.hooks.config.HOOKS_CONFIG_PATH", p)
    with pytest.raises(HooksConfigError, match="编译失败"):
        load()


def test_validate_matcher_accepts_simple_or(tmp_path, monkeypatch):
    p = tmp_path / "hooks.json"
    p.write_text(json.dumps({
        "version": 1,
        "hooks": {"PreToolUse": [
            {"matcher": "write_file|edit_file",
             "hooks": [{"type": "command", "command": "x"}]},
        ]},
    }))
    monkeypatch.setattr("argos.hooks.config.HOOKS_CONFIG_PATH", p)
    cfg = load()
    assert cfg.entries["PreToolUse"][0].matcher == "write_file|edit_file"


def test_validate_matcher_accepts_star_wildcard(tmp_path, monkeypatch):
    p = tmp_path / "hooks.json"
    p.write_text(json.dumps({
        "version": 1,
        "hooks": {"PreToolUse": [
            {"matcher": "*", "hooks": [{"type": "command", "command": "x"}]},
        ]},
    }))
    monkeypatch.setattr("argos.hooks.config.HOOKS_CONFIG_PATH", p)
    cfg = load()
    assert cfg.entries["PreToolUse"][0].matcher == "*"


def test_validate_matcher_accepts_none_omitted(tmp_path, monkeypatch):
    p = tmp_path / "hooks.json"
    p.write_text(json.dumps({
        "version": 1,
        "hooks": {"PreToolUse": [
            {"hooks": [{"type": "command", "command": "x"}]},
        ]},
    }))
    monkeypatch.setattr("argos.hooks.config.HOOKS_CONFIG_PATH", p)
    cfg = load()
    assert cfg.entries["PreToolUse"][0].matcher is None


def test_validate_matcher_rejects_empty_string(tmp_path, monkeypatch):
    p = tmp_path / "hooks.json"
    p.write_text(json.dumps({
        "version": 1,
        "hooks": {"PreToolUse": [
            {"matcher": "", "hooks": [{"type": "command", "command": "x"}]},
        ]},
    }))
    monkeypatch.setattr("argos.hooks.config.HOOKS_CONFIG_PATH", p)
    cfg = load()
    assert cfg.entries["PreToolUse"][0].matcher == ""


def test_validate_matcher_rejects_single_quantifier_no_nesting(tmp_path, monkeypatch):
    p = tmp_path / "hooks.json"
    p.write_text(json.dumps({
        "version": 1,
        "hooks": {"PreToolUse": [
            {"matcher": "(a+)", "hooks": [{"type": "command", "command": "x"}]},
        ]},
    }))
    monkeypatch.setattr("argos.hooks.config.HOOKS_CONFIG_PATH", p)
    cfg = load()
    assert cfg.entries["PreToolUse"][0].matcher == "(a+)"


def test_validate_matcher_rejects_whole_config_bad_entry_doesnt_load_others(tmp_path, monkeypatch):
    p = tmp_path / "hooks.json"
    p.write_text(json.dumps({
        "version": 1,
        "hooks": {
            "PreToolUse": [
                {"matcher": "write_file", "hooks": [{"type": "command", "command": "good"}]},
                {"matcher": "(.*)*", "hooks": [{"type": "command", "command": "bad"}]},
            ],
            "PostToolUse": [
                {"matcher": "read_file", "hooks": [{"type": "command", "command": "post"}]},
            ],
        },
    }))
    monkeypatch.setattr("argos.hooks.config.HOOKS_CONFIG_PATH", p)
    with pytest.raises(HooksConfigError, match="嵌套量词"):
        load()
