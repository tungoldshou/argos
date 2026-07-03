"""Internal documentation."""
from __future__ import annotations

import subprocess
from typing import Any
from unittest.mock import MagicMock

import pytest

from argos.perception.actions import ComputerAction
from argos.perception.executor import ComputerExecutor, ComputerActionResult, detect_scale_factor



def _make_run_result(returncode: int, stdout: str = "", stderr: str = "") -> Any:
    r = MagicMock()
    r.returncode = returncode
    r.stdout = stdout
    r.stderr = stderr
    return r



def test_executor_accepts_scale_factor():
    """Internal documentation."""
    ex = ComputerExecutor(scale_factor=2.0)
    assert ex._scale_factor == 2.0


def test_executor_default_scale_factor_is_one():
    """Internal documentation."""
    ex = ComputerExecutor()
    assert ex._scale_factor == 1.0



def test_click_divides_coords_by_scale_factor(monkeypatch: pytest.MonkeyPatch):
    """Internal documentation."""
    monkeypatch.setenv("ARGOS_COMPUTER_USE", "1")
    calls: list[list[str]] = []

    def mock_run(cmd: list[str], **kw: Any) -> Any:
        calls.append(list(cmd))
        return _make_run_result(0)

    monkeypatch.setattr(subprocess, "run", mock_run)

    executor = ComputerExecutor(scale_factor=2.0)
    result = executor._click(600, 900, double=False)

    assert result.ok is True
    assert calls, "应调用 subprocess.run"
    script = calls[0][2]
    assert "300" in script, f"期望逻辑 x=300 出现在脚本中,实际:\n{script}"
    assert "450" in script, f"期望逻辑 y=450 出现在脚本中,实际:\n{script}"
    assert "x:600" not in script and "{600," not in script, (
        f"物理像素 x=600 不应未经缩放出现在脚本中:\n{script}"
    )


def test_click_scale_factor_one_passes_coords_unchanged(monkeypatch: pytest.MonkeyPatch):
    """Internal documentation."""
    monkeypatch.setenv("ARGOS_COMPUTER_USE", "1")
    calls: list[list[str]] = []

    def mock_run(cmd: list[str], **kw: Any) -> Any:
        calls.append(list(cmd))
        return _make_run_result(0)

    monkeypatch.setattr(subprocess, "run", mock_run)

    executor = ComputerExecutor(scale_factor=1.0)
    executor._click(300, 450, double=False)

    script = calls[0][2]
    assert "300" in script
    assert "450" in script


def test_double_click_also_scales(monkeypatch: pytest.MonkeyPatch):
    """Internal documentation."""
    monkeypatch.setenv("ARGOS_COMPUTER_USE", "1")
    calls: list[list[str]] = []

    def mock_run(cmd: list[str], **kw: Any) -> Any:
        calls.append(list(cmd))
        return _make_run_result(0)

    monkeypatch.setattr(subprocess, "run", mock_run)

    executor = ComputerExecutor(scale_factor=2.0)
    result = executor._click(400, 800, double=True)

    assert result.ok is True
    script = calls[0][2]
    assert "200" in script, f"期望逻辑 x=200,实际:\n{script}"
    assert "400" in script, f"期望逻辑 y=400,实际:\n{script}"
    assert "double click" in script



def test_scroll_divides_coords_by_scale_factor(monkeypatch: pytest.MonkeyPatch):
    """Internal documentation."""
    monkeypatch.setenv("ARGOS_COMPUTER_USE", "1")
    calls: list[list[str]] = []

    def mock_run(cmd: list[str], **kw: Any) -> Any:
        calls.append(list(cmd))
        return _make_run_result(0)

    monkeypatch.setattr(subprocess, "run", mock_run)

    executor = ComputerExecutor(scale_factor=2.0)
    result = executor._scroll(500, 1000, 3)

    assert result.ok is True
    script = calls[0][2]
    assert "250" in script, f"期望逻辑 x=250,实际:\n{script}"
    assert "500" in script, f"期望逻辑 y=500,实际:\n{script}"


def test_scroll_scale_factor_one_unchanged(monkeypatch: pytest.MonkeyPatch):
    """Internal documentation."""
    monkeypatch.setenv("ARGOS_COMPUTER_USE", "1")
    calls: list[list[str]] = []

    def mock_run(cmd: list[str], **kw: Any) -> Any:
        calls.append(list(cmd))
        return _make_run_result(0)

    monkeypatch.setattr(subprocess, "run", mock_run)

    executor = ComputerExecutor(scale_factor=1.0)
    executor._scroll(100, 200, 3)

    script = calls[0][2]
    assert "100" in script
    assert "200" in script



def test_disabled_path_unaffected_by_scale_factor(monkeypatch: pytest.MonkeyPatch):
    """Internal documentation."""
    monkeypatch.delenv("ARGOS_COMPUTER_USE", raising=False)
    executor = ComputerExecutor(scale_factor=2.0)
    result = executor.dispatch(ComputerAction(kind="click", x=100, y=200))
    assert result.ok is False
    assert "未启用" in result.detail



def test_detect_scale_factor_returns_float():
    """Internal documentation."""
    result = detect_scale_factor(screenshot_width=2880, logical_width=1440)
    assert isinstance(result, float)
    assert result == 2.0


def test_detect_scale_factor_unit_display():
    """Internal documentation."""
    assert detect_scale_factor(screenshot_width=1920, logical_width=1920) == 1.0


def test_detect_scale_factor_zero_logical_returns_one():
    """Internal documentation."""
    assert detect_scale_factor(screenshot_width=1920, logical_width=0) == 1.0



def test_auto_detect_scale_applies_on_click_when_enabled(monkeypatch):
    """Internal documentation."""
    monkeypatch.setenv("ARGOS_COMPUTER_USE", "1")
    import argos.perception.executor as ex_mod
    monkeypatch.setattr(ex_mod, "detect_display_scale", lambda: 2.0)
    calls: list[list[str]] = []
    monkeypatch.setattr(subprocess, "run",
                        lambda cmd, **kw: (calls.append(list(cmd)), _make_run_result(0))[1])

    ex = ComputerExecutor(auto_detect_scale=True)
    ex._click(600, 900, double=False)
    script = calls[0][2]
    assert "300" in script and "450" in script, f"应用探测到的 2.0 缩放,实际:\n{script}"


def test_auto_detect_scale_inert_when_computer_use_off(monkeypatch):
    """Internal documentation."""
    monkeypatch.delenv("ARGOS_COMPUTER_USE", raising=False)
    import argos.perception.executor as ex_mod

    def _boom() -> float:
        raise AssertionError("computer-use 关闭时不应调用 detect_display_scale")
    monkeypatch.setattr(ex_mod, "detect_display_scale", _boom)
    calls: list[list[str]] = []
    monkeypatch.setattr(subprocess, "run",
                        lambda cmd, **kw: (calls.append(list(cmd)), _make_run_result(0))[1])

    ex = ComputerExecutor(auto_detect_scale=True)
    ex._click(300, 450, double=False)
    script = calls[0][2]
    assert "300" in script and "450" in script


def test_detect_display_scale_fallbacks_to_one(monkeypatch):
    """Internal documentation."""
    import argos.perception.executor as ex_mod
    ex_mod._SCALE_CACHE.clear()
    monkeypatch.setattr(subprocess, "run",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("no display")))
    try:
        assert ex_mod.detect_display_scale() == 1.0
    finally:
        ex_mod._SCALE_CACHE.clear()
