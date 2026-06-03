"""Phase 3:SeatbeltExecutor 经真子进程跑代码,命名空间持久 + 三态捕获。
本测试真起 sandbox-exec 子进程(macOS only)。"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from argos_agent.sandbox.executor import SeatbeltExecutor

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="Seatbelt 仅 macOS")


@pytest.fixture
def ex(tmp_path: Path):
    e = SeatbeltExecutor()
    e.spawn(workspace=tmp_path, namespace={})
    yield e
    e.close()


def test_stdout_captured(ex):
    r = ex.exec_code("print('hello sandbox')")
    assert r.ok
    assert "hello sandbox" in r.stdout


def test_value_repr_captured(ex):
    r = ex.exec_code("21 * 2")
    assert r.ok
    assert r.value_repr == "42"


def test_namespace_persists_across_calls(ex):
    ex.exec_code("counter = 10")
    ex.exec_code("counter = counter + 5")
    r = ex.exec_code("counter")
    assert r.ok
    assert r.value_repr == "15"   # 变量跨 code-action 存活(CodeAct 核心)


def test_exception_captured_as_data(ex):
    r = ex.exec_code("1 / 0")
    assert r.ok is False
    assert "ZeroDivisionError" in r.exc
