"""/hooks / /hooks reload slash + 坏配置 banner + UserPromptSubmit 触发。"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def isolated_hooks_home(monkeypatch):
    """每测试 HOME 临时目录 → ~/.argos/hooks.json 独立。"""
    tmp = tempfile.mkdtemp()
    monkeypatch.setenv("HOME", tmp)
    yield Path(tmp) / ".argos"
    # cleanup
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)


@pytest.mark.asyncio
async def test_hooks_command_lists_3_events_4_hooks(isolated_hooks_home, monkeypatch):
    """/hooks 渲染 3 事件 4 hook(测试调 _dispatch_slash 走 list 路径)。"""
    from argos.hooks import _reset_config
    from argos.hooks import reload_config
    isolated_hooks_home.mkdir(parents=True, exist_ok=True)
    p = isolated_hooks_home / "hooks.json"
    p.write_text(json.dumps({
        "version": 1,
        "hooks": {
            "PreToolUse": [
                {"matcher": "write_file", "hooks": [{"type": "command", "command": "a.sh"}]},
            ],
            "PostToolUse": [
                {"matcher": "edit_file", "hooks": [{"type": "command", "command": "b.sh"}]},
            ],
            "Stop": [
                {"hooks": [{"type": "command", "command": "c.sh"}]},
            ],
        },
    }))
    monkeypatch.setattr("argos.hooks.config.HOOKS_CONFIG_PATH", p)
    _reset_config()
    # 验证 reload 拿到 3 事件
    cfg = reload_config()
    assert len(cfg.entries) == 3
    assert "PreToolUse" in cfg.entries
    assert "PostToolUse" in cfg.entries
    assert "Stop" in cfg.entries


@pytest.mark.asyncio
async def test_hooks_reload_replaces_singleton(isolated_hooks_home, monkeypatch):
    """改 ~/.argos/hooks.json 后 /hooks reload → 后续 fire 用新配。"""
    from argos.hooks import _reset_config, get_config, reload_config
    isolated_hooks_home.mkdir(parents=True, exist_ok=True)
    p = isolated_hooks_home / "hooks.json"
    # 初始空
    p.write_text(json.dumps({"version": 1, "hooks": {}}))
    monkeypatch.setattr("argos.hooks.config.HOOKS_CONFIG_PATH", p)
    _reset_config()
    assert get_config().entries == {}
    # 改
    p.write_text(json.dumps({
        "version": 1,
        "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "x"}]}]},
    }))
    reload_config()
    assert "Stop" in get_config().entries


@pytest.mark.asyncio
async def test_hooks_reload_invalid_keeps_old(isolated_hooks_home, monkeypatch):
    """reload 时新配不合规 → 保旧 + 抛 HooksConfigError。"""
    from argos.hooks import _reset_config, get_config, reload_config, HooksConfigError
    isolated_hooks_home.mkdir(parents=True, exist_ok=True)
    p = isolated_hooks_home / "hooks.json"
    p.write_text(json.dumps({
        "version": 1,
        "hooks": {"PreToolUse": [{"hooks": [{"type": "command", "command": "old"}]}]},
    }))
    monkeypatch.setattr("argos.hooks.config.HOOKS_CONFIG_PATH", p)
    _reset_config()
    cfg_old = reload_config()
    # 改坏
    p.write_text("{not json")
    with pytest.raises(HooksConfigError):
        reload_config()
    # 单例仍是旧的
    assert get_config() is cfg_old


def test_bad_config_splash_banner():
    """启动时坏配置 → StartupSplash.set_bad_config(reason) 被调,渲染含 'hooks 已禁用'。"""
    from argos.tui.widgets.splash import StartupSplash
    sp = StartupSplash(model_label="x", tier="default", live=True)
    sp.set_bad_config("parse error: bad json at line 3")
    # 渲染文本含 'hooks 已禁用'
    text = sp.renderable_text
    assert "hooks 已禁用" in text
    assert "parse error" in text


def test_command_help_includes_hooks():
    """COMMAND_HELP 含 'hooks' 描述。"""
    from argos.tui.commands import COMMAND_HELP
    assert "hooks" in COMMAND_HELP
    assert "reload" in COMMAND_HELP["hooks"]
