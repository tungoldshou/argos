"""Internal documentation."""
from __future__ import annotations

import pytest

from argos import __version__ as ARGOS_VERSION
from argos.protocol import PROTOCOL_VERSION
from argos.tui import daemon_spawn



def test_is_compatible_accepts_own_version():
    assert daemon_spawn._is_compatible(
        {"daemon": ARGOS_VERSION, "protocol": PROTOCOL_VERSION}
    ) is True


def test_is_compatible_rejects_version_mismatch():
    assert daemon_spawn._is_compatible(
        {"daemon": "0.0.0-stale", "protocol": PROTOCOL_VERSION}
    ) is False


def test_is_compatible_rejects_protocol_mismatch():
    assert daemon_spawn._is_compatible(
        {"daemon": ARGOS_VERSION, "protocol": 999}
    ) is False


def test_is_compatible_rejects_missing_fields():
    assert daemon_spawn._is_compatible({}) is False
    assert daemon_spawn._is_compatible({"protocol": PROTOCOL_VERSION}) is False
    assert daemon_spawn._is_compatible({"daemon": ARGOS_VERSION}) is False



def test_is_compatible_detects_dev_code_change(monkeypatch):
    """Internal documentation."""
    monkeypatch.setattr(daemon_spawn, "_argos_code_mtime", lambda: 2000.0)
    assert daemon_spawn._is_compatible(
        {"daemon": ARGOS_VERSION, "protocol": PROTOCOL_VERSION, "started_at": 1000.0}
    ) is False


def test_is_compatible_accepts_daemon_newer_than_code(monkeypatch):
    """Internal documentation."""
    monkeypatch.setattr(daemon_spawn, "_argos_code_mtime", lambda: 1000.0)
    assert daemon_spawn._is_compatible(
        {"daemon": ARGOS_VERSION, "protocol": PROTOCOL_VERSION, "started_at": 2000.0}
    ) is True


def test_is_compatible_missing_started_at_falls_back_to_version(monkeypatch):
    """Internal documentation."""
    monkeypatch.setattr(daemon_spawn, "_argos_code_mtime", lambda: 9e9)
    assert daemon_spawn._is_compatible(
        {"daemon": ARGOS_VERSION, "protocol": PROTOCOL_VERSION}
    ) is True



@pytest.mark.asyncio
async def test_compatible_daemon_is_reused(monkeypatch, tmp_path):
    """Internal documentation."""
    killed = {"n": 0}
    spawned = {"n": 0}

    async def fake_probe(_p):
        return True

    async def fake_version(_p):
        return {"daemon": ARGOS_VERSION, "protocol": PROTOCOL_VERSION}

    def fake_kill(_p):
        killed["n"] += 1

    async def fake_exec(*a, **k):
        spawned["n"] += 1
        raise AssertionError("compatible daemon must NOT be respawned")

    monkeypatch.setattr(daemon_spawn, "_probe", fake_probe)
    monkeypatch.setattr(daemon_spawn, "_daemon_version", fake_version)
    monkeypatch.setattr(daemon_spawn, "_kill_stale_daemon", fake_kill)
    monkeypatch.setattr(daemon_spawn.asyncio, "create_subprocess_exec", fake_exec)

    result = await daemon_spawn.probe_or_spawn(tmp_path / "d.sock")
    assert result is True
    assert killed["n"] == 0
    assert spawned["n"] == 0


@pytest.mark.asyncio
async def test_stale_daemon_killed_and_respawned(monkeypatch, tmp_path):
    """Internal documentation."""
    killed = {"n": 0}
    spawned = {"n": 0}

    async def fake_probe(_p):
        return True

    async def fake_version(_p):
        return {"daemon": "0.0.0-stale", "protocol": PROTOCOL_VERSION}

    def fake_kill(_p):
        killed["n"] += 1

    class _P:
        returncode = None

    async def fake_exec(*a, **k):
        spawned["n"] += 1
        return _P()

    monkeypatch.setattr(daemon_spawn, "_probe", fake_probe)
    monkeypatch.setattr(daemon_spawn, "_daemon_version", fake_version)
    monkeypatch.setattr(daemon_spawn, "_kill_stale_daemon", fake_kill)
    monkeypatch.setattr(daemon_spawn.asyncio, "create_subprocess_exec", fake_exec)
    monkeypatch.setattr(daemon_spawn, "_SPAWN_TIMEOUT", 0.05)
    monkeypatch.setattr(daemon_spawn, "_WAIT_POLL", 0.01)

    result = await daemon_spawn.probe_or_spawn(tmp_path / "d.sock")
    assert killed["n"] == 1, "陈旧 daemon 必须被杀"
    assert spawned["n"] == 1, "必须 spawn 新 daemon"
    assert result is True


@pytest.mark.asyncio
async def test_version_unreachable_treated_as_stale(monkeypatch, tmp_path):
    """Internal documentation."""
    killed = {"n": 0}
    spawned = {"n": 0}

    async def fake_probe(_p):
        return True

    async def fake_version(_p):
        return None

    def fake_kill(_p):
        killed["n"] += 1

    class _P:
        returncode = None

    async def fake_exec(*a, **k):
        spawned["n"] += 1
        return _P()

    monkeypatch.setattr(daemon_spawn, "_probe", fake_probe)
    monkeypatch.setattr(daemon_spawn, "_daemon_version", fake_version)
    monkeypatch.setattr(daemon_spawn, "_kill_stale_daemon", fake_kill)
    monkeypatch.setattr(daemon_spawn.asyncio, "create_subprocess_exec", fake_exec)
    monkeypatch.setattr(daemon_spawn, "_SPAWN_TIMEOUT", 0.05)
    monkeypatch.setattr(daemon_spawn, "_WAIT_POLL", 0.01)

    await daemon_spawn.probe_or_spawn(tmp_path / "d.sock")
    assert killed["n"] == 1
    assert spawned["n"] == 1


# ── _kill_stale_daemon ────────────────────────────────────────────────────

def test_kill_stale_daemon_removes_pid_and_sock(monkeypatch, tmp_path):
    """Internal documentation."""
    sock = tmp_path / "daemon.sock"
    sock.write_text("")
    pid_path = tmp_path / "daemon.pid"
    pid_path.write_text("424242\n")

    states = iter([True, False, False, False])
    monkeypatch.setattr(daemon_spawn, "_pid_alive", lambda pid: next(states, False))
    killed: list[int] = []
    monkeypatch.setattr(daemon_spawn.os, "kill", lambda pid, sig: killed.append(pid))

    daemon_spawn._kill_stale_daemon(sock)

    assert killed == [424242], "应向 pid 文件里的 PID 发一次信号(SIGTERM)"
    assert not pid_path.exists(), "pid 文件应被删"
    assert not sock.exists(), "sock 文件应被删"


def test_kill_stale_daemon_skips_dead_pid(monkeypatch, tmp_path):
    """Internal documentation."""
    sock = tmp_path / "daemon.sock"
    sock.write_text("")
    pid_path = tmp_path / "daemon.pid"
    pid_path.write_text("424242\n")

    monkeypatch.setattr(daemon_spawn, "_pid_alive", lambda pid: False)
    killed: list[int] = []
    monkeypatch.setattr(daemon_spawn.os, "kill", lambda pid, sig: killed.append(pid))

    daemon_spawn._kill_stale_daemon(sock)

    assert killed == [], "死 PID 不该发 kill(防 PID 复用误杀)"
    assert not pid_path.exists()
    assert not sock.exists()
