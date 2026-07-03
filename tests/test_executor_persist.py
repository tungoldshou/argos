"""Internal documentation."""
from __future__ import annotations

from pathlib import Path

import pytest

from argos.sandbox.executor import select_backend


@pytest.fixture
def ex(tmp_path: Path, requires_sandbox):
    e = select_backend()()
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
    assert r.value_repr == "15"


def test_exception_captured_as_data(ex):
    r = ex.exec_code("1 / 0")
    assert r.ok is False
    assert "ZeroDivisionError" in r.exc
