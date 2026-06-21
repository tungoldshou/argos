"""tests/perception/test_retina_scaling.py — Retina 坐标缩放测试。

测试覆盖:
  · scale_factor 可注入(不依赖真实显示器)
  · scale_factor=2.0 时 _click 坐标被除以 2
  · scale_factor=2.0 时 _scroll 坐标被除以 2
  · scale_factor=1.0 时坐标不变(默认行为)
  · 非 darwin 不影响 disabled 路径(原有 honest-error 路径不破坏)
  · detect_scale_factor 函数存在且返回 float(仅检测接口,不真调系统)
"""
from __future__ import annotations

import subprocess
from typing import Any
from unittest.mock import MagicMock

import pytest

from argos.perception.actions import ComputerAction
from argos.perception.executor import ComputerExecutor, ComputerActionResult, detect_scale_factor


# ── 辅助 ─────────────────────────────────────────────────────────────────────

def _make_run_result(returncode: int, stdout: str = "", stderr: str = "") -> Any:
    r = MagicMock()
    r.returncode = returncode
    r.stdout = stdout
    r.stderr = stderr
    return r


# ── scale_factor 注入 ─────────────────────────────────────────────────────────

def test_executor_accepts_scale_factor():
    """ComputerExecutor 应接受 scale_factor 关键字参数。"""
    ex = ComputerExecutor(scale_factor=2.0)
    assert ex._scale_factor == 2.0


def test_executor_default_scale_factor_is_one():
    """未传 scale_factor 时默认值为 1.0。"""
    ex = ComputerExecutor()
    assert ex._scale_factor == 1.0


# ── click 坐标缩放 ────────────────────────────────────────────────────────────

def test_click_divides_coords_by_scale_factor(monkeypatch: pytest.MonkeyPatch):
    """scale_factor=2.0 时,传入物理像素 (600, 900) 应转换为逻辑点 (300, 450) 再发给 osascript。"""
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
    # 逻辑点 300, 450 — 不是原始物理像素 600, 900
    assert "300" in script, f"期望逻辑 x=300 出现在脚本中,实际:\n{script}"
    assert "450" in script, f"期望逻辑 y=450 出现在脚本中,实际:\n{script}"
    # 原始物理像素不应直接出现(排除恰好含 600 的其他子串)
    assert "x:600" not in script and "{600," not in script, (
        f"物理像素 x=600 不应未经缩放出现在脚本中:\n{script}"
    )


def test_click_scale_factor_one_passes_coords_unchanged(monkeypatch: pytest.MonkeyPatch):
    """scale_factor=1.0 时坐标不变(默认行为,1x 显示器兼容)。"""
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
    """double_click 与 click 同路径,也应缩放坐标。"""
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


# ── scroll 坐标缩放 ───────────────────────────────────────────────────────────

def test_scroll_divides_coords_by_scale_factor(monkeypatch: pytest.MonkeyPatch):
    """scroll 坐标也应除以 scale_factor。"""
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
    """scale_factor=1.0 时 scroll 坐标不变。"""
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


# ── non-darwin 路径不破坏 ─────────────────────────────────────────────────────

def test_disabled_path_unaffected_by_scale_factor(monkeypatch: pytest.MonkeyPatch):
    """ARGOS_COMPUTER_USE 未设置时,scale_factor 不影响 disabled 路径诚实返回。"""
    monkeypatch.delenv("ARGOS_COMPUTER_USE", raising=False)
    executor = ComputerExecutor(scale_factor=2.0)
    result = executor.dispatch(ComputerAction(kind="click", x=100, y=200))
    assert result.ok is False
    assert "未启用" in result.detail


# ── detect_scale_factor 接口 ──────────────────────────────────────────────────

def test_detect_scale_factor_returns_float():
    """detect_scale_factor() 函数必须存在且返回 float(不调真实系统)。"""
    # 测试接口存在性:不 mock —— 在 CI (非 darwin / 无显示器) 中
    # 函数应 fallback 到 1.0 而非抛异常
    result = detect_scale_factor(screenshot_width=2880, logical_width=1440)
    assert isinstance(result, float)
    assert result == 2.0


def test_detect_scale_factor_unit_display():
    """1x 显示器:physical=logical → scale=1.0。"""
    assert detect_scale_factor(screenshot_width=1920, logical_width=1920) == 1.0


def test_detect_scale_factor_zero_logical_returns_one():
    """logical_width=0 → 安全 fallback 1.0(避免除零)。"""
    assert detect_scale_factor(screenshot_width=1920, logical_width=0) == 1.0


# ── 生产惰性自动探测接线(auto_detect_scale)──────────────────────────────────

def test_auto_detect_scale_applies_on_click_when_enabled(monkeypatch):
    """auto_detect_scale=True + ARGOS_COMPUTER_USE 开 → 首次点击惰性探测真实 scale 并应用。
    探测函数被 mock 成 2.0(Retina)→ 物理 (600,900) 应被换算成逻辑 (300,450)。"""
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
    """护栏:auto_detect_scale=True 但 ARGOS_COMPUTER_USE 未开 → 不探测,scale 保持 1.0(坐标不变)。
    (computer-use 关闭时本就走 disabled 路径,这里直测 _click 确保不误触探测副作用。)"""
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
    assert "300" in script and "450" in script  # 未缩放


def test_detect_display_scale_fallbacks_to_one(monkeypatch):
    """detect_display_scale 在 osascript/screencapture 失败时回退 1.0(零回归,绝不抛)。"""
    import argos.perception.executor as ex_mod
    ex_mod._SCALE_CACHE.clear()
    monkeypatch.setattr(subprocess, "run",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("no display")))
    try:
        assert ex_mod.detect_display_scale() == 1.0
    finally:
        ex_mod._SCALE_CACHE.clear()
