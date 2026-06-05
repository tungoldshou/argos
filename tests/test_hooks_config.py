"""Hooks 配置 dataclass 单元测试(spec §2.2 / §2.4)。"""
from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from argos_agent.hooks.config import (
    HookHandler,
    HookMatcherEntry,
    HooksConfig,
    HooksConfigError,
)
from argos_agent.hooks.matcher import match


def test_hook_handler_frozen_dataclass():
    """HookHandler 是 frozen dataclass;含 type/command/timeout 字段。"""
    h = HookHandler(type="command", command="echo ok", timeout=5000)
    assert h.type == "command"
    assert h.command == "echo ok"
    assert h.timeout == 5000
    with pytest.raises(FrozenInstanceError):
        h.command = "other"  # type: ignore[misc]


def test_hook_handler_default_timeout():
    """timeout 不传 → 默认 60000 ms(60s,spec §2.2)。"""
    h = HookHandler(type="command", command="echo ok")
    assert h.timeout == 60000


def test_hook_handler_invalid_type_raises():
    """type 必须是 'command'(MVP only,spec D 不上 prompt/agent)。"""
    with pytest.raises(ValueError):
        HookHandler(type="python", command="print(1)")


def test_hook_handler_invalid_timeout_raises():
    """timeout 必须 > 0。"""
    with pytest.raises(ValueError):
        HookHandler(type="command", command="echo ok", timeout=0)
    with pytest.raises(ValueError):
        HookHandler(type="command", command="echo ok", timeout=-1)


def test_matcher_entry_construction():
    """HookMatcherEntry 含 matcher(可空)+ hooks 列表。"""
    h1 = HookHandler(type="command", command="echo 1")
    e = HookMatcherEntry(matcher="write_file|edit_file", hooks=(h1,))
    assert e.matcher == "write_file|edit_file"
    assert list(e.hooks) == [h1]


def test_matcher_entry_empty_matcher():
    """matcher 可省略(None)→ 视同 '*' 全匹配(spec §2.2)。"""
    h = HookHandler(type="command", command="echo")
    e = HookMatcherEntry(matcher=None, hooks=(h,))
    assert e.matcher is None


def test_hooks_config_empty():
    """HooksConfig.empty() → 全等 fire no-op 的配置(0 event / 0 hook)。"""
    cfg = HooksConfig.empty()
    assert cfg.version == 1
    assert cfg.entries == {}   # dict[event_name, list[HookMatcherEntry]]


def test_hooks_config_construction_with_entries():
    """HooksConfig 接受 entries dict。"""
    e = HookMatcherEntry(
        matcher="write_file",
        hooks=(HookHandler(type="command", command="echo a"),),
    )
    cfg = HooksConfig(entries={"PreToolUse": [e]})
    assert "PreToolUse" in cfg.entries
    assert len(cfg.entries["PreToolUse"]) == 1


def test_hooks_config_error_is_exception():
    """HooksConfigError 是 Exception 子类,带 message。"""
    err = HooksConfigError("bad json")
    assert isinstance(err, Exception)
    assert "bad json" in str(err)


# ── matcher 单元测试(spec §4.2)────────────────────────────────────

def _h(cmd: str) -> HookHandler:
    return HookHandler(type="command", command=cmd)


def _entry(matcher, cmds):
    return HookMatcherEntry(matcher=matcher, hooks=tuple(_h(c) for c in cmds))


def test_match_regex_or():
    """matcher='write_file|edit_file' 命中 ['write_file'] / ['edit_file','x'];不命中 ['read_file']。"""
    cfg = HooksConfig(entries={"PreToolUse": [_entry("write_file|edit_file", ["h1"])]})
    assert len(match("PreToolUse", ["write_file"], cfg)) == 1
    assert len(match("PreToolUse", ["edit_file", "x"], cfg)) == 1
    assert len(match("PreToolUse", ["read_file"], cfg)) == 0


def test_match_star_wildcard():
    """matcher='*' 全匹配任何 tool_names(空 list 也算全匹配)。"""
    cfg = HooksConfig(entries={"PreToolUse": [_entry("*", ["h1"])]})
    assert len(match("PreToolUse", ["write_file"], cfg)) == 1
    assert len(match("PreToolUse", [], cfg)) == 1


def test_match_empty_matcher_means_star():
    """matcher 为 None / '' → 视同 '*' 全匹配(spec §2.2)。"""
    cfg = HooksConfig(entries={"PreToolUse": [_entry(None, ["h1"]), _entry("", ["h2"])]})
    assert len(match("PreToolUse", ["x"], cfg)) == 2


def test_match_multi_entry_merge_dedup():
    """同事件多 entry 命中 → hooks 列表拼接,command 重复的要去重。"""
    e1 = _entry("write_file", ["a", "b"])
    e2 = _entry("write_file", ["b", "c"])   # b 重复
    cfg = HooksConfig(entries={"PreToolUse": [e1, e2]})
    result = match("PreToolUse", ["write_file"], cfg)
    assert len(result) == 3
    assert {h.command for h in result} == {"a", "b", "c"}


def test_match_non_pre_post_event_ignores_matcher():
    """Stop / UserPromptSubmit / SessionStart 等事件忽略 matcher(spec §2.2)。
    matcher 字段被忽略,所有 entry 的 hooks 都返回。"""
    cfg = HooksConfig(entries={"Stop": [_entry("write_file", ["a"]), _entry(None, ["b"])]})
    result = match("Stop", [], cfg)  # tool_names 空,但 Stop 不看 matcher
    assert len(result) == 2
    assert {h.command for h in result} == {"a", "b"}


def test_match_unknown_event_returns_empty():
    """未知 event 名(不应到这一步,但兜底)→ 空列表。"""
    cfg = HooksConfig(entries={"PreToolUse": [_entry("*", ["a"])]})
    assert match("UnknownEvent", ["x"], cfg) == []


def test_match_invalid_regex_ignored():
    """matcher 正则非法(用户写错)→ 该 entry 跳过,不抛(诚实:不因坏 matcher 卡 agent)。"""
    e1 = _entry("[invalid(regex", ["bad"])
    e2 = _entry("write_file", ["good"])
    cfg = HooksConfig(entries={"PreToolUse": [e1, e2]})
    result = match("PreToolUse", ["write_file"], cfg)
    assert len(result) == 1
    assert result[0].command == "good"
