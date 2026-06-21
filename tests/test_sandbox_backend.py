"""沙箱后端:win32 明确拒绝 + sandbox_backend_summary Contract D。

覆盖:
  - executor.select_backend() 在 win32 抛出清晰 RuntimeError
  - linux.sandbox_backend_summary() 在 darwin/bwrap/unshare/none 各返正确 (name, is_weak)
"""
from __future__ import annotations

import sys
from unittest import mock

import pytest

from argos.sandbox import linux as linux_mod
from argos.sandbox.executor import select_backend
from argos.sandbox.linux import sandbox_backend_summary


# ── executor.select_backend: win32 分支 ─────────────────────────────────


def test_select_backend_raises_on_win32():
    """Windows 平台必须抛出有意义的 RuntimeError,不能静默 fall-through 到 Linux 路径。"""
    with mock.patch.object(sys, "platform", "win32"):
        with pytest.raises(RuntimeError, match="Windows"):
            select_backend()


def test_select_backend_win32_message_mentions_macos_and_linux():
    """错误消息应同时提 macOS 和 Linux,引导用户使用支持的平台。"""
    with mock.patch.object(sys, "platform", "win32"):
        with pytest.raises(RuntimeError) as exc_info:
            select_backend()
    msg = str(exc_info.value)
    assert "macOS" in msg or "mac" in msg.lower(), f"消息未提 macOS:{msg!r}"
    assert "Linux" in msg, f"消息未提 Linux:{msg!r}"


# ── sandbox_backend_summary (Contract D) ────────────────────────────────


def test_backend_summary_darwin_is_strong():
    """macOS Seatbelt:名字 'seatbelt',is_weak_cage=False。"""
    with mock.patch.object(sys, "platform", "darwin"):
        name, weak = sandbox_backend_summary()
    assert name == "seatbelt"
    assert weak is False


def test_backend_summary_linux_bwrap_is_strong():
    """Linux + bwrap:名字 'bwrap',is_weak_cage=False。"""
    with mock.patch.object(sys, "platform", "linux"), \
         mock.patch.object(linux_mod, "_AVAILABLE_BACKEND", "bwrap"):
        name, weak = sandbox_backend_summary()
    assert name == "bwrap"
    assert weak is False


def test_backend_summary_linux_unshare_is_weak():
    """Linux + unshare 退化:名字 'unshare',is_weak_cage=True(无 mount namespace 写牢笼弱)。"""
    with mock.patch.object(sys, "platform", "linux"), \
         mock.patch.object(linux_mod, "_AVAILABLE_BACKEND", "unshare"):
        name, weak = sandbox_backend_summary()
    assert name == "unshare"
    assert weak is True


def test_backend_summary_linux_no_backend_is_weak():
    """Linux + 都无后端:名字 'none',is_weak_cage=True(无沙箱)。"""
    with mock.patch.object(sys, "platform", "linux"), \
         mock.patch.object(linux_mod, "_AVAILABLE_BACKEND", None):
        name, weak = sandbox_backend_summary()
    assert name == "none"
    assert weak is True


def test_backend_summary_unknown_platform_is_weak():
    """其他平台(win32 等):名字 'none',is_weak_cage=True。"""
    with mock.patch.object(sys, "platform", "win32"):
        name, weak = sandbox_backend_summary()
    assert name == "none"
    assert weak is True


def test_backend_summary_return_type():
    """返回值始终是 tuple[str, bool]。"""
    with mock.patch.object(sys, "platform", "darwin"):
        result = sandbox_backend_summary()
    assert isinstance(result, tuple)
    assert len(result) == 2
    assert isinstance(result[0], str)
    assert isinstance(result[1], bool)
