from __future__ import annotations

import sys
from unittest import mock

import pytest

from argos.sandbox import linux as linux_mod
from argos.sandbox.executor import select_backend
from argos.sandbox.linux import sandbox_backend_summary




def test_select_backend_raises_on_win32():
    with mock.patch.object(sys, "platform", "win32"):
        with pytest.raises(RuntimeError, match="Windows"):
            select_backend()


def test_select_backend_win32_message_mentions_macos_and_linux():
    with mock.patch.object(sys, "platform", "win32"):
        with pytest.raises(RuntimeError) as exc_info:
            select_backend()
    msg = str(exc_info.value)
    assert "macOS" in msg or "mac" in msg.lower(), f"消息未提 macOS:{msg!r}"
    assert "Linux" in msg, f"消息未提 Linux:{msg!r}"


# ── sandbox_backend_summary (Contract D) ────────────────────────────────


def test_backend_summary_darwin_is_strong():
    with mock.patch.object(sys, "platform", "darwin"):
        name, weak = sandbox_backend_summary()
    assert name == "seatbelt"
    assert weak is False


def test_backend_summary_linux_bwrap_is_strong():
    with mock.patch.object(sys, "platform", "linux"),\
         mock.patch.object(linux_mod, "_AVAILABLE_BACKEND", "bwrap"):
        name, weak = sandbox_backend_summary()
    assert name == "bwrap"
    assert weak is False


def test_backend_summary_linux_unshare_is_weak():
    with mock.patch.object(sys, "platform", "linux"),\
         mock.patch.object(linux_mod, "_AVAILABLE_BACKEND", "unshare"):
        name, weak = sandbox_backend_summary()
    assert name == "unshare"
    assert weak is True


def test_backend_summary_linux_no_backend_is_weak():
    with mock.patch.object(sys, "platform", "linux"),\
         mock.patch.object(linux_mod, "_AVAILABLE_BACKEND", None):
        name, weak = sandbox_backend_summary()
    assert name == "none"
    assert weak is True


def test_backend_summary_unknown_platform_is_weak():
    with mock.patch.object(sys, "platform", "win32"):
        name, weak = sandbox_backend_summary()
    assert name == "none"
    assert weak is True


def test_backend_summary_return_type():
    with mock.patch.object(sys, "platform", "darwin"):
        result = sandbox_backend_summary()
    assert isinstance(result, tuple)
    assert len(result) == 2
    assert isinstance(result[0], str)
    assert isinstance(result[1], bool)
