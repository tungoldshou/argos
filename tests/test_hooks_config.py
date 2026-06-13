"""Hooks 配置 dataclass 单元测试(spec §2.2 / §2.4)。"""
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
    HOOKS_CONFIG_PATH,   # 期望:PosixPath('~/.argos/hooks.json')
)
from argos.hooks.matcher import match
from argos.hooks import get_config, reload_config


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


# ── 加载 + 校验 + reload 流程测试(spec §4.1 / §3 错误处理表)────────────

def test_hooks_config_path_is_argos_home():
    """HOOKS_CONFIG_PATH = ~/.argos/hooks.json(spec §2.2)。"""
    assert HOOKS_CONFIG_PATH == Path.home() / ".argos" / "hooks.json"


def test_load_missing_file_returns_empty(tmp_path, monkeypatch):
    """hooks.json 不存在 → 返 HooksConfig.empty()(spec §3 不存在行)。"""
    monkeypatch.setattr(
        "argos.hooks.config.HOOKS_CONFIG_PATH", tmp_path / "hooks.json"
    )
    cfg = load()
    assert cfg.entries == {}


def test_load_valid_minimal(tmp_path, monkeypatch):
    """合法最小配置:仅 version + 空 hooks dict。"""
    p = tmp_path / "hooks.json"
    p.write_text(json.dumps({"version": 1, "hooks": {}}))
    monkeypatch.setattr("argos.hooks.config.HOOKS_CONFIG_PATH", p)
    cfg = load()
    assert cfg.version == 1
    assert cfg.entries == {}


def test_load_valid_with_event_and_matcher(tmp_path, monkeypatch):
    """合法配置:1 事件 + matcher。"""
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
    """JSON 坏字 → HooksConfigError(绝不部分加载,spec D11)。"""
    p = tmp_path / "hooks.json"
    p.write_text("{not valid json")
    monkeypatch.setattr("argos.hooks.config.HOOKS_CONFIG_PATH", p)
    with pytest.raises(HooksConfigError):
        load()


def test_load_missing_version_raises(tmp_path, monkeypatch):
    """version 缺 → HooksConfigError。"""
    p = tmp_path / "hooks.json"
    p.write_text(json.dumps({"hooks": {}}))
    monkeypatch.setattr("argos.hooks.config.HOOKS_CONFIG_PATH", p)
    with pytest.raises(HooksConfigError, match="version"):
        load()


def test_load_wrong_version_raises(tmp_path, monkeypatch):
    """version 不匹配(本机 v1,文件 v2)→ 报错 + 拒载。"""
    p = tmp_path / "hooks.json"
    p.write_text(json.dumps({"version": 2, "hooks": {}}))
    monkeypatch.setattr("argos.hooks.config.HOOKS_CONFIG_PATH", p)
    with pytest.raises(HooksConfigError, match="version"):
        load()


def test_load_unknown_event_raises(tmp_path, monkeypatch):
    """不识别的事件名 → HooksConfigError(spec §2.2)。"""
    p = tmp_path / "hooks.json"
    p.write_text(json.dumps({
        "version": 1,
        "hooks": {"NotARealEvent": [{"hooks": [{"type": "command", "command": "x"}]}]},
    }))
    monkeypatch.setattr("argos.hooks.config.HOOKS_CONFIG_PATH", p)
    with pytest.raises(HooksConfigError, match="event"):
        load()


def test_load_matcher_not_string_raises(tmp_path, monkeypatch):
    """matcher 字段非字符串 → HooksConfigError。"""
    p = tmp_path / "hooks.json"
    p.write_text(json.dumps({
        "version": 1,
        "hooks": {"PreToolUse": [{"matcher": 123, "hooks": [{"type": "command", "command": "x"}]}]},
    }))
    monkeypatch.setattr("argos.hooks.config.HOOKS_CONFIG_PATH", p)
    with pytest.raises(HooksConfigError, match="matcher"):
        load()


def test_load_hooks_not_array_raises(tmp_path, monkeypatch):
    """hooks 字段非 array → HooksConfigError。"""
    p = tmp_path / "hooks.json"
    p.write_text(json.dumps({"version": 1, "hooks": {"PreToolUse": "not_array"}}))
    monkeypatch.setattr("argos.hooks.config.HOOKS_CONFIG_PATH", p)
    with pytest.raises(HooksConfigError, match="array"):
        load()


def test_load_handler_invalid_type_raises(tmp_path, monkeypatch):
    """type 非 'command' → HooksConfigError。"""
    p = tmp_path / "hooks.json"
    p.write_text(json.dumps({
        "version": 1,
        "hooks": {"PreToolUse": [{"hooks": [{"type": "python", "command": "print(1)"}]}]},
    }))
    monkeypatch.setattr("argos.hooks.config.HOOKS_CONFIG_PATH", p)
    with pytest.raises(HooksConfigError, match="type"):
        load()


def test_reload_replaces_singleton(tmp_path, monkeypatch):
    """reload 改 ~/.argos/hooks.json 后,get_config() 返新配置。"""
    p = tmp_path / "hooks.json"
    p.write_text(json.dumps({"version": 1, "hooks": {}}))
    monkeypatch.setattr("argos.hooks.config.HOOKS_CONFIG_PATH", p)
    # 旧配置
    cfg1 = reload_config()
    assert cfg1.entries == {}
    # 改文件
    p.write_text(json.dumps({
        "version": 1,
        "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "x"}]}]},
    }))
    cfg2 = reload_config()
    assert "Stop" in cfg2.entries
    # get_config 应返新
    assert "Stop" in get_config().entries


def test_reload_invalid_keeps_old(tmp_path, monkeypatch):
    """reload 时新配置不合规 → 保旧 + 报错(spec §3 reload 行)。"""
    from argos.hooks import _config
    p = tmp_path / "hooks.json"
    p.write_text(json.dumps({
        "version": 1,
        "hooks": {"PreToolUse": [{"hooks": [{"type": "command", "command": "old"}]}]},
    }))
    monkeypatch.setattr("argos.hooks.config.HOOKS_CONFIG_PATH", p)
    cfg_old = reload_config()
    # 改坏
    p.write_text("{not json")
    with pytest.raises(HooksConfigError):
        reload_config()
    # 单例仍是旧的
    assert get_config() is cfg_old
    assert get_config().entries["PreToolUse"][0].hooks[0].command == "old"


# ── D14 matcher 编译期校验(spec D14)────────────────────────────────────
# 三拒:长度 > 256 / 嵌套量词(ReDoS)/ re.error;三过:普通字符 / '*' / 'write_file|edit_file'。
# 整配拒载(D11 一致):同 config 里其他 event 的 entry 也不会加载。


def test_validate_matcher_rejects_overlong(tmp_path, monkeypatch):
    """matcher 长度 > 256 → HooksConfigError(spec D14 第一条)。"""
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
    """matcher 长度恰好 256 → 通过(边界值,不等号 = 256 OK)。"""
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
    """matcher `(.*)*` → HooksConfigError(ReDoS 经典模式,spec D14 第二条)。"""
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
    """matcher `(.+)+$` → HooksConfigError(ReDoS 经典模式,带锚点也拦)。"""
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
    """matcher `(.*)+` → HooksConfigError(混合嵌套也算,spec D14 第二条)。"""
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
    """matcher `(unclosed` → HooksConfigError(re.error,spec D14 第三条)。"""
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
    """合法 matcher 'write_file|edit_file' → 通过。"""
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
    """合法 matcher '*' → 通过(全匹配通配符,语义化由 match() 处理)。"""
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
    """matcher 字段省略 → 通过(语义为 None = 全匹配,spec §2.2)。"""
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
    """matcher 为空串 "" → 仍按"全匹配语义"放行(匹配 match() 的语义:空 == '*')。

    注:这里没把空串列为"非法",因 match() 已把空串当 '*' 处理;若改用
    `len(matcher) == 0` 单独拒,会破坏"空 = 全匹配"的现有契约(spec §2.2)。
    """
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
    """非嵌套量词(`a+` / `(a+)`)→ 通过。
    启发式只拦"组内已有量词且组外再加量词"的真嵌套,单层不算。"""
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
    """D11 一致:坏 matcher → 整配拒载,同 config 里其他 event 的合法 entry 也不进。

    验证点:PreToolUse 里有合法 matcher + PostToolUse 里有合法配置;
    PreToolUse 里**另一条 entry** matcher 是嵌套量词 → 整 load() 抛,
    后续 PostToolUse 也不会被加载(单条 entry 失败 ≠ 跳过该 entry 继续)。
    """
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
    # reload_config 应保留旧单例(本测试前 reload_config 未调,_config 为 None,
    # 走 _load_or_empty → empty),但关键断言是 load() 抛了 HooksConfigError
    # —— 整配拒载,绝不返回"部分加载"的 HooksConfig。
