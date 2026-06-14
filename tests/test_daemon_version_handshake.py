"""daemon 版本握手:陈旧 daemon 不被静默复用 → 杀旧 + 起新。

根因(2026-06-14 真机 bug):Jun-12 启动的旧 `argos_agent` daemon 跨越 Jun-13 包改名
(argos_agent → argos)+ .venv 重装后,内存里仍跑旧代码,spawn 的 sandbox child 用旧模块名
→ ModuleNotFoundError: No module named 'argos_agent' → run 一启动就 sandbox init 失败。
但 TUI 只探 /health 200 就静默复用该 daemon → 表现为无限"思考中"。

修:probe_or_spawn 在 /health 后再握手 /version,比对 daemon 报的版本 + 协议号与 TUI 自身;
不匹配/拿不到 → 视为陈旧,杀旧 daemon + 清 pid/sock + spawn 新的(用户选定:自动杀+起新)。
"""
from __future__ import annotations

import pytest

from argos import __version__ as ARGOS_VERSION
from argos.protocol import PROTOCOL_VERSION
from argos.tui import daemon_spawn


# ── _is_compatible:版本 + 协议双比对 ──────────────────────────────────────

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


# ── dev 改码检测(版本号相同但代码改过 → 陈旧)─────────────────────────────────

def test_is_compatible_detects_dev_code_change(monkeypatch):
    """daemon started_at 早于代码 mtime(dev 改过码,版本号没变)→ 不兼容(需重启)。

    这正是真机踩的坑:旧 daemon 与当前代码都 0.1.0,旧握手只比版本号 → 误判兼容复用。
    """
    monkeypatch.setattr(daemon_spawn, "_argos_code_mtime", lambda: 2000.0)
    assert daemon_spawn._is_compatible(
        {"daemon": ARGOS_VERSION, "protocol": PROTOCOL_VERSION, "started_at": 1000.0}
    ) is False


def test_is_compatible_accepts_daemon_newer_than_code(monkeypatch):
    """daemon started_at 晚于代码 mtime(daemon 跑的就是当前码)→ 兼容,复用。"""
    monkeypatch.setattr(daemon_spawn, "_argos_code_mtime", lambda: 1000.0)
    assert daemon_spawn._is_compatible(
        {"daemon": ARGOS_VERSION, "protocol": PROTOCOL_VERSION, "started_at": 2000.0}
    ) is True


def test_is_compatible_missing_started_at_falls_back_to_version(monkeypatch):
    """started_at 缺失(更老的 daemon)→ 保守只按版本号判,不靠 mtime。"""
    monkeypatch.setattr(daemon_spawn, "_argos_code_mtime", lambda: 9e9)
    assert daemon_spawn._is_compatible(
        {"daemon": ARGOS_VERSION, "protocol": PROTOCOL_VERSION}
    ) is True


# ── probe_or_spawn 握手控制流 ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_compatible_daemon_is_reused(monkeypatch, tmp_path):
    """health 200 + 版本匹配 → 复用(True),既不杀也不 spawn。"""
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
    """health 200 但版本不匹配 → 杀旧 daemon + spawn 新的。"""
    killed = {"n": 0}
    spawned = {"n": 0}

    async def fake_probe(_p):
        return True  # 旧 health 活;spawn 后轮询也 True(新 daemon 就绪)

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
    """health 200 但 /version 拿不到(更老的 daemon 无此端点)→ 视为陈旧 → 杀 + spawn。"""
    killed = {"n": 0}
    spawned = {"n": 0}

    async def fake_probe(_p):
        return True

    async def fake_version(_p):
        return None  # 端点不可达 / 解析失败

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
    """杀 daemon.pid 记录的 PID + 删 pid/sock 文件。"""
    sock = tmp_path / "daemon.sock"
    sock.write_text("")  # 假 sock 文件(单元测试不起真 socket)
    pid_path = tmp_path / "daemon.pid"
    pid_path.write_text("424242\n")

    monkeypatch.setattr(daemon_spawn, "_pid_alive", lambda pid: True)
    killed: list[int] = []
    monkeypatch.setattr(daemon_spawn.os, "kill", lambda pid, sig: killed.append(pid))

    daemon_spawn._kill_stale_daemon(sock)

    assert killed == [424242], "应向 pid 文件里的 PID 发信号"
    assert not pid_path.exists(), "pid 文件应被删"
    assert not sock.exists(), "sock 文件应被删"


def test_kill_stale_daemon_skips_dead_pid(monkeypatch, tmp_path):
    """PID 已不存在(is_alive False)→ 不发 kill,但仍清 pid/sock。"""
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
