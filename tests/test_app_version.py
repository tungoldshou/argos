"""顶栏 / splash 版本号单一来源回归(2026-06-16 真机:顶栏显示 v0.x)。
根因:查 version("argos") 必 PackageNotFoundError —— 分发名是 "argos-agent",不是 "argos"
→ 回退 "0.x"。正源是 argos.__version__(查 "argos-agent" + VERSION 文件兜底)。"""
from __future__ import annotations

import os

os.environ.setdefault("ARGOS_NO_DAEMON", "1")  # 导入 TUI 不触发 daemon 探测


def test_app_version_is_real_not_placeholder():
    import argos
    from argos.tui.app import _app_version
    assert _app_version() == argos.__version__
    assert _app_version() != "0.x", "顶栏版本不应回退占位符(查错了分发名)"


def test_splash_version_is_real_not_placeholder():
    import argos
    from argos.tui.widgets import splash
    assert splash._VERSION == argos.__version__
    assert splash._VERSION != "0.x", "splash 版本不应回退占位符(查错了分发名)"
