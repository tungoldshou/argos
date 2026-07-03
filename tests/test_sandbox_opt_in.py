"""Internal documentation."""
from __future__ import annotations

import subprocess

import pytest

from argos import config
from argos.sandbox import seatbelt
from argos.tools import shell


def test_sandbox_enabled_default_off(monkeypatch):
    monkeypatch.delenv("ARGOS_SANDBOX", raising=False)
    assert config.sandbox_enabled() is False


def test_sandbox_enabled_on_when_set(monkeypatch):
    for v in ("1", "true", "yes", "on", "ON", "True"):
        monkeypatch.setenv("ARGOS_SANDBOX", v)
        assert config.sandbox_enabled() is True, v
    for v in ("0", "false", "no", ""):
        monkeypatch.setenv("ARGOS_SANDBOX", v)
        assert config.sandbox_enabled() is False, v


class _FakeProc:
    stdin = stdout = stderr = None


def test_spawn_child_unwrapped_when_sandbox_off(tmp_path, monkeypatch):
    captured = {}
    monkeypatch.setattr(subprocess, "Popen",
                        lambda argv, **kw: captured.__setitem__("argv", argv) or _FakeProc())
    seatbelt.spawn_child(workspace=tmp_path, child_argv=["python3", "-c", "pass"], sandbox=False)
    assert captured["argv"] == ["python3", "-c", "pass"]
    assert not (tmp_path / ".argos_sandbox.sb").exists()


def test_spawn_child_wrapped_when_sandbox_on(tmp_path, monkeypatch):
    captured = {}
    monkeypatch.setattr(subprocess, "Popen",
                        lambda argv, **kw: captured.__setitem__("argv", argv) or _FakeProc())
    seatbelt.spawn_child(workspace=tmp_path, child_argv=["python3", "-c", "pass"], sandbox=True)
    assert captured["argv"][0] == "/usr/bin/sandbox-exec"
    assert (tmp_path / ".argos_sandbox.sb").exists()


def test_run_command_unconfined_when_sandbox_off(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGOS_SANDBOX", "0")
    captured = {}

    class _R:
        returncode = 0
        stdout = "hi\n"
        stderr = ""

    monkeypatch.setattr(subprocess, "run",
                        lambda argv, **kw: captured.__setitem__("argv", argv) or _R())
    shell.run_command("echo hi", workspace=tmp_path)
    assert captured["argv"] == ["echo", "hi"]
