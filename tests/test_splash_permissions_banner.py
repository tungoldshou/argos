"""StartupSplash 坏配置 banner 接入 permissions(spec §2.6)。"""
from __future__ import annotations

import pytest


def test_splash_permissions_banner():
    """reason 串含 'permissions' → 显 'permissions 已禁用' 前缀。"""
    from argos.tui.widgets.splash import StartupSplash
    sp = StartupSplash(model_label="M3", tier="sonnet", live=True)
    sp.set_bad_config("permissions: JSON 解析失败: ...")
    text = sp.renderable_text
    assert "permissions 已禁用" in text
    assert "JSON" in text


def test_splash_lsp_banner_preserved():
    """reason 含 'LSP' → 'LSP 已禁用' 前缀(向后兼容 hooks/LSP 行为)。"""
    from argos.tui.widgets.splash import StartupSplash
    sp = StartupSplash(model_label="M3", tier="sonnet", live=True)
    sp.set_bad_config("LSP: 加载失败")
    text = sp.renderable_text
    assert "LSP 已禁用" in text


def test_splash_hooks_banner_default():
    """reason 不含 LSP/permissions → hooks 前缀(向后兼容)。"""
    from argos.tui.widgets.splash import StartupSplash
    sp = StartupSplash(model_label="M3", tier="sonnet", live=True)
    sp.set_bad_config("command not found")
    text = sp.renderable_text
    assert "hooks 已禁用" in text
