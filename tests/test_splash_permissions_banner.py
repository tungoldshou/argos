"""Internal documentation."""
from __future__ import annotations

import pytest


def test_splash_permissions_banner():
    """Internal documentation."""
    from argos.tui.widgets.splash import StartupSplash
    sp = StartupSplash(model_label="M3", tier="sonnet", live=True)
    sp.set_bad_config("permissions: JSON 解析失败: ...")
    text = sp.renderable_text
    assert "permissions 已禁用" in text
    assert "JSON" in text


def test_splash_lsp_banner_preserved():
    """Internal documentation."""
    from argos.tui.widgets.splash import StartupSplash
    sp = StartupSplash(model_label="M3", tier="sonnet", live=True)
    sp.set_bad_config("LSP: 加载失败")
    text = sp.renderable_text
    assert "LSP 已禁用" in text


def test_splash_hooks_banner_default():
    """Internal documentation."""
    from argos.tui.widgets.splash import StartupSplash
    sp = StartupSplash(model_label="M3", tier="sonnet", live=True)
    sp.set_bad_config("command not found")
    text = sp.renderable_text
    assert "hooks 已禁用" in text
