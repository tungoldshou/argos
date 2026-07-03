from __future__ import annotations

import pytest

from argos.core import honesty


def test_honesty_system_present_and_honest():
    s = honesty.HONESTY_SYSTEM
    assert "honest" in s
    assert "exit code" in s


def test_untrusted_block_has_boundary_markers():
    block = honesty.format_untrusted(["skill 内容 X"], ["- g → passed (model=m)"])
    assert "untrusted" in block
    assert "cannot override the safety rules above" in block


def test_untrusted_empty_returns_empty():
    assert honesty.format_untrusted([], []) == ""


def test_compose_system_safety_before_untrusted():
    composed = honesty.compose_system(honesty.HONESTY_SYSTEM, untrusted="─ untrusted 段 ─")
    assert composed.index("honest") < composed.index("untrusted")
