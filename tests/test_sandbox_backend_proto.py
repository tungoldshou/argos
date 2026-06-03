"""Phase 3:SandboxBackend 协议形状 + ExecResult 字段/ok 属性(契约 §5)。"""
from __future__ import annotations

import dataclasses
from typing import get_type_hints

import pytest

from argos_agent.sandbox.backend import ExecResult, SandboxBackend


def test_exec_result_is_frozen_slots_dataclass():
    assert dataclasses.is_dataclass(ExecResult)
    p = ExecResult.__dataclass_params__
    assert p.frozen is True
    hints = get_type_hints(ExecResult)
    assert hints["stdout"] is str
    assert hints["value_repr"] is str
    assert hints["exc"] is str


def test_exec_result_ok_property():
    assert ExecResult(stdout="hi", value_repr="3", exc="").ok is True
    assert ExecResult(stdout="", value_repr="", exc="ValueError: boom").ok is False


def test_sandbox_backend_protocol_methods():
    # Protocol 必须声明 spawn / exec_code / close
    for name in ("spawn", "exec_code", "close"):
        assert hasattr(SandboxBackend, name), f"SandboxBackend 缺方法 {name}"
