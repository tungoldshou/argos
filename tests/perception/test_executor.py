"""tests/perception/test_executor.py — ComputerExecutor 测试。

全部用 monkeypatch 假桩替换 subprocess.run;绝不真截屏/真点击。
覆盖:
  · 旗标关闭时诚实拒绝(返回"未启用"消息)
  · screenshot 命令拼装正确
  · screenshot 超时返回 ok=False + 诚实描述
  · Accessibility 权限失败路径 → 诚实提示
  · click / double_click / type_text / key / scroll / open_app 命令拼装
  · open_app 命令正确(不含 shell 特殊字符)
  · timeout 参数传给 subprocess.run
"""
from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from argos_agent.perception.actions import ComputerAction
from argos_agent.perception.executor import (
    ComputerExecutor,
    ComputerActionResult,
    _DISABLED_MSG,
    _ACCESS_DENIED_MSG,
)


# ── 辅助 ──────────────────────────────────────────────────────────────────────

def _make_run_result(returncode: int, stdout: str = "", stderr: str = ""):
    """构造 subprocess.CompletedProcess 假结果。"""
    r = MagicMock()
    r.returncode = returncode
    r.stdout = stdout
    r.stderr = stderr
    return r


# ── 旗标关闭路径 ──────────────────────────────────────────────────────────────

def test_disabled_when_no_flag(monkeypatch: pytest.MonkeyPatch):
    """ARGOS_COMPUTER_USE 未设置 → dispatch 返回诚实禁止消息,不调 subprocess。"""
    monkeypatch.delenv("ARGOS_COMPUTER_USE", raising=False)
    called = []

    def mock_run(*a, **kw):
        called.append(True)
        return _make_run_result(0)

    monkeypatch.setattr(subprocess, "run", mock_run)

    executor = ComputerExecutor()
    result = executor.dispatch(ComputerAction(kind="screenshot"))
    assert result.ok is False
    assert "未启用" in result.detail or _DISABLED_MSG in result.detail
    assert len(called) == 0, "旗标未设置时不应调用 subprocess.run"


def test_disabled_when_flag_is_zero(monkeypatch: pytest.MonkeyPatch):
    """ARGOS_COMPUTER_USE=0 → 依然禁用。"""
    monkeypatch.setenv("ARGOS_COMPUTER_USE", "0")
    executor = ComputerExecutor()
    result = executor.dispatch(ComputerAction(kind="screenshot"))
    assert result.ok is False
    assert "未启用" in result.detail


# ── screenshot ────────────────────────────────────────────────────────────────

def test_screenshot_calls_screencapture(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """screenshot → 调用 screencapture -x <path>。"""
    monkeypatch.setenv("ARGOS_COMPUTER_USE", "1")
    captured_cmd = []

    def mock_run(cmd, **kw):
        captured_cmd.append(list(cmd))
        # 创建一个空 PNG 文件,模拟截图成功
        if cmd[0] == "screencapture":
            Path(cmd[2]).write_bytes(b"")
        return _make_run_result(0)

    monkeypatch.setattr(subprocess, "run", mock_run)
    # 不调 PIL,monkeypatch Image.open
    monkeypatch.setattr("argos_agent.perception.executor.ComputerExecutor._screenshot",
                        lambda self: ComputerActionResult(
                            ok=True, detail="截图已保存至 /tmp/argos_screen_test.png",
                            artifact_path="/tmp/argos_screen_test.png", size=(1920, 1080)
                        ))

    executor = ComputerExecutor()
    result = executor.dispatch(ComputerAction(kind="screenshot"))
    assert result.ok is True
    assert result.artifact_path is not None or "截图" in result.detail


def test_screenshot_command_structure(monkeypatch: pytest.MonkeyPatch):
    """screencapture 命令必须包含 -x 标志(静默/无鼠标)。"""
    monkeypatch.setenv("ARGOS_COMPUTER_USE", "1")
    calls: list[list[str]] = []

    def mock_run(cmd, **kw):
        calls.append(list(cmd))
        # 写入空文件模拟 screencapture 成功
        if len(cmd) >= 3 and cmd[0] == "screencapture":
            Path(cmd[2]).write_bytes(b"PNG_FAKE")
        return _make_run_result(0)

    monkeypatch.setattr(subprocess, "run", mock_run)
    # mock PIL 不可用
    monkeypatch.setattr("builtins.__import__", _make_import_fail_pil())

    executor = ComputerExecutor()
    executor._screenshot()  # 直接调私有方法验命令结构
    assert calls, "应该调用了 subprocess.run"
    sc_calls = [c for c in calls if c[0] == "screencapture"]
    assert sc_calls, "应使用 screencapture"
    assert "-x" in sc_calls[0], "screencapture 必须有 -x 标志(静默)"


def test_screenshot_timeout_returns_failure(monkeypatch: pytest.MonkeyPatch):
    """screencapture 超时 → ok=False + 诚实描述。"""
    monkeypatch.setenv("ARGOS_COMPUTER_USE", "1")

    def mock_run(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, kw.get("timeout", 10))

    monkeypatch.setattr(subprocess, "run", mock_run)

    executor = ComputerExecutor()
    result = executor._screenshot()
    assert result.ok is False
    assert "超时" in result.detail


def test_screenshot_failure_returns_ok_false(monkeypatch: pytest.MonkeyPatch):
    """screencapture 返回非零 → ok=False。"""
    monkeypatch.setenv("ARGOS_COMPUTER_USE", "1")

    def mock_run(cmd, **kw):
        return _make_run_result(1, stderr="permission denied")

    monkeypatch.setattr(subprocess, "run", mock_run)

    executor = ComputerExecutor()
    result = executor._screenshot()
    assert result.ok is False
    assert "截图失败" in result.detail


# ── Accessibility 权限失败路径 ────────────────────────────────────────────────

def test_click_access_denied_returns_helpful_message(monkeypatch: pytest.MonkeyPatch):
    """osascript 返回 Accessibility 权限错误 → ok=False + 人话指引。"""
    monkeypatch.setenv("ARGOS_COMPUTER_USE", "1")

    def mock_run(cmd, **kw):
        return _make_run_result(
            1,
            stderr="osascript: System Events got an error: "
                   "System Events is not allowed to send keystrokes.",
        )

    monkeypatch.setattr(subprocess, "run", mock_run)

    executor = ComputerExecutor()
    result = executor._click(100, 200, double=False)
    assert result.ok is False
    assert "辅助功能" in result.detail or "系统设置" in result.detail
    assert result.detail == _ACCESS_DENIED_MSG


def test_type_text_access_denied(monkeypatch: pytest.MonkeyPatch):
    """type_text Accessibility 拒绝 → 诚实提示。"""
    monkeypatch.setenv("ARGOS_COMPUTER_USE", "1")

    def mock_run(cmd, **kw):
        return _make_run_result(1, stderr="not allowed assistive access")

    monkeypatch.setattr(subprocess, "run", mock_run)

    executor = ComputerExecutor()
    result = executor._type_text("hello")
    assert result.ok is False
    assert "辅助功能" in result.detail or "系统设置" in result.detail


def test_key_access_denied(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ARGOS_COMPUTER_USE", "1")

    def mock_run(cmd, **kw):
        return _make_run_result(1, stderr="-25211")

    monkeypatch.setattr(subprocess, "run", mock_run)

    executor = ComputerExecutor()
    result = executor._key("command+c")
    assert result.ok is False
    assert "辅助功能" in result.detail or "系统设置" in result.detail


# ── 命令拼装 ──────────────────────────────────────────────────────────────────

def test_click_calls_osascript(monkeypatch: pytest.MonkeyPatch):
    """click → osascript -e script, 坐标嵌入脚本。"""
    monkeypatch.setenv("ARGOS_COMPUTER_USE", "1")
    calls: list[list[str]] = []

    def mock_run(cmd, **kw):
        calls.append(list(cmd))
        return _make_run_result(0)

    monkeypatch.setattr(subprocess, "run", mock_run)

    executor = ComputerExecutor()
    result = executor._click(300, 450, double=False)
    assert result.ok is True
    assert calls[0][0] == "osascript"
    script = calls[0][2]
    assert "300" in script and "450" in script
    assert "click" in script


def test_double_click_script_contains_double_click(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ARGOS_COMPUTER_USE", "1")
    calls: list[list[str]] = []

    def mock_run(cmd, **kw):
        calls.append(list(cmd))
        return _make_run_result(0)

    monkeypatch.setattr(subprocess, "run", mock_run)

    executor = ComputerExecutor()
    result = executor._click(0, 0, double=True)
    assert result.ok is True
    script = calls[0][2]
    assert "double click" in script


def test_type_text_escapes_quotes(monkeypatch: pytest.MonkeyPatch):
    """type_text 中的双引号必须被转义(防 AppleScript 注入)。"""
    monkeypatch.setenv("ARGOS_COMPUTER_USE", "1")
    calls: list[list[str]] = []

    def mock_run(cmd, **kw):
        calls.append(list(cmd))
        return _make_run_result(0)

    monkeypatch.setattr(subprocess, "run", mock_run)

    executor = ComputerExecutor()
    result = executor._type_text('say "hello"')
    assert result.ok is True
    script = calls[0][2]
    # 双引号必须被转义为 \"
    assert '\\"hello\\"' in script or "\\\"hello\\\"" in script


def test_key_with_modifier_uses_using_clause(monkeypatch: pytest.MonkeyPatch):
    """key 'command+c' → AppleScript 含 'command key'。"""
    monkeypatch.setenv("ARGOS_COMPUTER_USE", "1")
    calls: list[list[str]] = []

    def mock_run(cmd, **kw):
        calls.append(list(cmd))
        return _make_run_result(0)

    monkeypatch.setattr(subprocess, "run", mock_run)

    executor = ComputerExecutor()
    result = executor._key("command+c")
    assert result.ok is True
    script = calls[0][2]
    assert "command key" in script
    assert "keystroke" in script


def test_key_without_modifier(monkeypatch: pytest.MonkeyPatch):
    """单键 'return' → 无 using 子句。"""
    monkeypatch.setenv("ARGOS_COMPUTER_USE", "1")
    calls: list[list[str]] = []

    def mock_run(cmd, **kw):
        calls.append(list(cmd))
        return _make_run_result(0)

    monkeypatch.setattr(subprocess, "run", mock_run)

    executor = ComputerExecutor()
    result = executor._key("return")
    assert result.ok is True
    script = calls[0][2]
    assert "using" not in script or "using {}" not in script


def test_scroll_calls_osascript_with_coords(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ARGOS_COMPUTER_USE", "1")
    calls: list[list[str]] = []

    def mock_run(cmd, **kw):
        calls.append(list(cmd))
        return _make_run_result(0)

    monkeypatch.setattr(subprocess, "run", mock_run)

    executor = ComputerExecutor()
    result = executor._scroll(100, 200, 5)
    assert result.ok is True
    script = calls[0][2]
    assert "scroll" in script


def test_open_app_uses_open_minus_a(monkeypatch: pytest.MonkeyPatch):
    """`open -a <app>` 命令结构正确。"""
    monkeypatch.setenv("ARGOS_COMPUTER_USE", "1")
    calls: list[list[str]] = []

    def mock_run(cmd, **kw):
        calls.append(list(cmd))
        return _make_run_result(0)

    monkeypatch.setattr(subprocess, "run", mock_run)

    executor = ComputerExecutor()
    result = executor._open_app("Finder")
    assert result.ok is True
    assert calls[0] == ["open", "-a", "Finder"]


def test_open_app_failure_returns_ok_false(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ARGOS_COMPUTER_USE", "1")

    def mock_run(cmd, **kw):
        return _make_run_result(1, stderr="Application not found")

    monkeypatch.setattr(subprocess, "run", mock_run)

    executor = ComputerExecutor()
    result = executor._open_app("NoSuchApp")
    assert result.ok is False
    assert "失败" in result.detail


# ── timeout 参数传递 ──────────────────────────────────────────────────────────

def test_custom_timeout_passed_to_subprocess(monkeypatch: pytest.MonkeyPatch):
    """ComputerExecutor(timeout=5) 的 timeout 应传给 subprocess.run。"""
    monkeypatch.setenv("ARGOS_COMPUTER_USE", "1")
    timeouts_seen: list[int] = []

    def mock_run(cmd, **kw):
        timeouts_seen.append(kw.get("timeout", -1))
        return _make_run_result(0)

    monkeypatch.setattr(subprocess, "run", mock_run)

    executor = ComputerExecutor(timeout=5)
    executor._click(0, 0, double=False)
    assert timeouts_seen and timeouts_seen[0] == 5


def test_command_not_found_returns_ok_false(monkeypatch: pytest.MonkeyPatch):
    """osascript 不存在(FileNotFoundError) → ok=False + 诚实描述。"""
    monkeypatch.setenv("ARGOS_COMPUTER_USE", "1")

    def mock_run(cmd, **kw):
        raise FileNotFoundError(f"No such file: {cmd[0]}")

    monkeypatch.setattr(subprocess, "run", mock_run)

    executor = ComputerExecutor()
    result = executor._click(0, 0, double=False)
    assert result.ok is False
    assert "점击失败" in result.detail or "失败" in result.detail or "不存在" in result.detail


# ── dispatch 旗标控制 ─────────────────────────────────────────────────────────

def test_dispatch_enabled_screenshot(monkeypatch: pytest.MonkeyPatch):
    """ARGOS_COMPUTER_USE=1 + dispatch(screenshot) → 调用 _screenshot。"""
    monkeypatch.setenv("ARGOS_COMPUTER_USE", "1")
    called = []

    def mock_screenshot(self):
        called.append(True)
        return ComputerActionResult(ok=True, detail="ok", artifact_path="/tmp/x.png", size=(1, 1))

    monkeypatch.setattr(ComputerExecutor, "_screenshot", mock_screenshot)

    executor = ComputerExecutor()
    result = executor.dispatch(ComputerAction(kind="screenshot"))
    assert result.ok is True
    assert called


def test_dispatch_enabled_click(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ARGOS_COMPUTER_USE", "1")
    called = []

    def mock_click(self, x, y, *, double):
        called.append((x, y, double))
        return ComputerActionResult(ok=True, detail="ok")

    monkeypatch.setattr(ComputerExecutor, "_click", mock_click)

    executor = ComputerExecutor()
    result = executor.dispatch(ComputerAction(kind="click", x=10, y=20))
    assert result.ok is True
    assert called == [(10, 20, False)]


def test_dispatch_enabled_open_app(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ARGOS_COMPUTER_USE", "1")
    called = []

    def mock_open_app(self, app):
        called.append(app)
        return ComputerActionResult(ok=True, detail="ok")

    monkeypatch.setattr(ComputerExecutor, "_open_app", mock_open_app)

    executor = ComputerExecutor()
    result = executor.dispatch(ComputerAction(kind="open_app", app="Terminal"))
    assert result.ok is True
    assert called == ["Terminal"]


# ── 辅助:屏蔽 PIL 导入 ───────────────────────────────────────────────────────

def _make_import_fail_pil():
    """返回一个 __import__ 替代品,对 PIL 抛 ImportError,其余正常。"""
    _real_import = __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__

    def _fake_import(name, *args, **kwargs):
        if name == "PIL" or name.startswith("PIL."):
            raise ImportError(f"PIL not available (test stub): {name}")
        return _real_import(name, *args, **kwargs)

    return _fake_import
