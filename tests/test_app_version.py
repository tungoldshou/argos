"""Internal documentation."""
from __future__ import annotations

import os

os.environ.setdefault("ARGOS_NO_DAEMON", "1")


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
