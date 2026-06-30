"""#2 CC对齐:OS 沙箱改 opt-in(默认关)。验证开关语义 + 关时不裹 sandbox-exec/bwrap(旁路)+
开时仍裹。confinement 本身(越界写/网络被拦)由 conftest 钉 ARGOS_SANDBOX=1 的既有测试覆盖。

注:这些测试 mock 掉 Popen/subprocess.run,只验"裹不裹"的 argv 决策,不真 spawn → 跨平台稳。
"""
from __future__ import annotations

import subprocess

import pytest

from argos import config
from argos.sandbox import seatbelt
from argos.tools import shell


# ── 开关语义:opt-in,默认关 ──────────────────────────────────────────────────
def test_sandbox_enabled_default_off(monkeypatch):
    monkeypatch.delenv("ARGOS_SANDBOX", raising=False)   # 抹掉 conftest 的钉 → 看真默认
    assert config.sandbox_enabled() is False


def test_sandbox_enabled_on_when_set(monkeypatch):
    for v in ("1", "true", "yes", "on", "ON", "True"):
        monkeypatch.setenv("ARGOS_SANDBOX", v)
        assert config.sandbox_enabled() is True, v
    for v in ("0", "false", "no", ""):
        monkeypatch.setenv("ARGOS_SANDBOX", v)
        assert config.sandbox_enabled() is False, v


# ── spawn_child:关时不裹 sandbox-exec、不写 profile;开时裹 ──────────────────────
class _FakeProc:
    stdin = stdout = stderr = None


def test_spawn_child_unwrapped_when_sandbox_off(tmp_path, monkeypatch):
    captured = {}
    monkeypatch.setattr(subprocess, "Popen",
                        lambda argv, **kw: captured.__setitem__("argv", argv) or _FakeProc())
    seatbelt.spawn_child(workspace=tmp_path, child_argv=["python3", "-c", "pass"], sandbox=False)
    assert captured["argv"] == ["python3", "-c", "pass"]          # 直跑,未裹
    assert not (tmp_path / ".argos_sandbox.sb").exists()           # 未写 Seatbelt profile


def test_spawn_child_wrapped_when_sandbox_on(tmp_path, monkeypatch):
    captured = {}
    monkeypatch.setattr(subprocess, "Popen",
                        lambda argv, **kw: captured.__setitem__("argv", argv) or _FakeProc())
    seatbelt.spawn_child(workspace=tmp_path, child_argv=["python3", "-c", "pass"], sandbox=True)
    assert captured["argv"][0] == "/usr/bin/sandbox-exec"          # 裹了 Seatbelt
    assert (tmp_path / ".argos_sandbox.sb").exists()               # 写了 profile


# ── run_command:关沙箱时 shell 直跑(不裹),开时按平台裹 ─────────────────────────
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
    assert captured["argv"] == ["echo", "hi"]                      # 直跑,未裹 sandbox-exec/bwrap
