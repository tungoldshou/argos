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
