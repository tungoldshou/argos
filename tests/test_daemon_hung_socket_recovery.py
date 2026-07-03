from __future__ import annotations

import shutil
import socket as _sock
import tempfile
import threading
from pathlib import Path

import pytest

from argos.daemon import socket as daemon_socket
from argos.tui import daemon_spawn


@pytest.fixture
def short_sock():
    d = tempfile.mkdtemp(prefix="argos_t_", dir="/tmp")
    try:
        yield Path(d) / "d.sock"
    finally:
        shutil.rmtree(d, ignore_errors=True)



def _responding_server(path):
    srv = _sock.socket(_sock.AF_UNIX, _sock.SOCK_STREAM)
    srv.bind(str(path))
    srv.listen(1)

    def serve():
        try:
            conn, _ = srv.accept()
            conn.recv(256)
            conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\n{}")
            conn.close()
        except OSError:
            pass

    th = threading.Thread(target=serve, daemon=True)
    th.start()
    return srv


def _hung_server(path):
    srv = _sock.socket(_sock.AF_UNIX, _sock.SOCK_STREAM)
    srv.bind(str(path))
    srv.listen(1)
    return srv



def test_check_socket_available_raises_when_daemon_responds_health(short_sock):
    srv = _responding_server(short_sock)
    try:
        with pytest.raises(RuntimeError, match="already in use"):
            daemon_socket.check_socket_available(short_sock)
    finally:
        srv.close()


def test_check_socket_available_treats_unresponsive_as_dead(short_sock, monkeypatch):
    monkeypatch.setattr(daemon_socket, "_HEALTH_TIMEOUT", 0.2, raising=False)
    srv = _hung_server(short_sock)
    try:
        daemon_socket.check_socket_available(short_sock)
        assert not short_sock.exists(), "假死 daemon 的 socket 应被清理以允许接管"
    finally:
        srv.close()


def test_check_socket_available_returns_when_no_socket(short_sock):
    daemon_socket.check_socket_available(short_sock)


def test_check_socket_available_cleans_refused_socket(short_sock):
    short_sock.write_text("")
    daemon_socket.check_socket_available(short_sock)
    assert not short_sock.exists(), "不可连接的残留 socket 文件应被清掉"



@pytest.mark.asyncio
async def test_unresponsive_socket_is_killed_before_spawn(monkeypatch, tmp_path):
    sock = tmp_path / "daemon.sock"
    sock.write_text("")
    order: list[str] = []

    async def fake_probe(_p):
        return False

    def fake_kill(_p):
        order.append("kill")
        try:
            (tmp_path / "daemon.sock").unlink()
        except FileNotFoundError:
            pass

    class _P:
        returncode = None

    async def fake_exec(*a, **k):
        order.append("spawn")
        return _P()

    monkeypatch.setattr(daemon_spawn, "_probe", fake_probe)
    monkeypatch.setattr(daemon_spawn, "_kill_stale_daemon", fake_kill)
    monkeypatch.setattr(daemon_spawn.asyncio, "create_subprocess_exec", fake_exec)
    monkeypatch.setattr(daemon_spawn, "_SPAWN_TIMEOUT", 0.05)
    monkeypatch.setattr(daemon_spawn, "_WAIT_POLL", 0.01)

    await daemon_spawn.probe_or_spawn(sock)

    assert "kill" in order, "假死 daemon 占着 socket 时,spawn 前必须先清理"
    assert order.index("kill") < order.index("spawn"), "必须先 kill 再 spawn"


@pytest.mark.asyncio
async def test_no_socket_file_does_not_kill(monkeypatch, tmp_path):
    sock = tmp_path / "daemon.sock"
    killed = {"n": 0}

    async def fake_probe(_p):
        return False

    def fake_kill(_p):
        killed["n"] += 1

    class _P:
        returncode = None

    async def fake_exec(*a, **k):
        return _P()

    monkeypatch.setattr(daemon_spawn, "_probe", fake_probe)
    monkeypatch.setattr(daemon_spawn, "_kill_stale_daemon", fake_kill)
    monkeypatch.setattr(daemon_spawn.asyncio, "create_subprocess_exec", fake_exec)
    monkeypatch.setattr(daemon_spawn, "_SPAWN_TIMEOUT", 0.05)
    monkeypatch.setattr(daemon_spawn, "_WAIT_POLL", 0.01)

    await daemon_spawn.probe_or_spawn(sock)
    assert killed["n"] == 0, "没有残留 socket 时不该试图杀任何东西"



@pytest.mark.asyncio
async def test_spawn_failure_surfaces_daemon_log(monkeypatch, tmp_path, caplog):
    import logging

    sock = tmp_path / "daemon.sock"

    async def fake_probe(_p):
        return False

    class _P:
        returncode = 1

    async def fake_exec(*a, **k):
        fh = k.get("stdout")
        if fh is not None and hasattr(fh, "write"):
            fh.write(b"[daemon] daemon socket already in use: /Users/zc/.argos/daemon.sock\n")
            fh.flush()
        return _P()

    monkeypatch.setattr(daemon_spawn, "_probe", fake_probe)
    monkeypatch.setattr(daemon_spawn.asyncio, "create_subprocess_exec", fake_exec)
    monkeypatch.setattr(daemon_spawn, "_SPAWN_TIMEOUT", 0.05)
    monkeypatch.setattr(daemon_spawn, "_WAIT_POLL", 0.01)

    with caplog.at_level(logging.WARNING, logger="argos.tui.daemon_spawn"):
        result = await daemon_spawn.probe_or_spawn(sock)

    assert result is False
    assert "already in use" in caplog.text, "daemon 启动失败原因必须被回显,不能再被 DEVNULL 吞掉"



def test_kill_stale_daemon_escalates_to_sigkill_when_sigterm_ignored(monkeypatch, tmp_path):
    import signal

    sock = tmp_path / "daemon.sock"
    sock.write_text("")
    pid_path = tmp_path / "daemon.pid"
    pid_path.write_text("424242\n")

    monkeypatch.setattr(daemon_spawn, "_pid_alive", lambda pid: True)
    monkeypatch.setattr(daemon_spawn, "_KILL_GRACE_S", 0.1, raising=False)
    monkeypatch.setattr(daemon_spawn, "_KILL_POLL_S", 0.02, raising=False)
    signals: list[tuple[int, int]] = []
    monkeypatch.setattr(daemon_spawn.os, "kill", lambda pid, sig: signals.append((pid, sig)))

    daemon_spawn._kill_stale_daemon(sock)

    assert (424242, signal.SIGTERM) in signals, "应先发 SIGTERM"
    assert (424242, signal.SIGKILL) in signals, "SIGTERM 无效必须升级 SIGKILL,杜绝孤儿"
    assert not pid_path.exists() and not sock.exists()


def test_kill_stale_daemon_no_sigkill_when_process_exits(monkeypatch, tmp_path):
    import signal

    sock = tmp_path / "daemon.sock"
    sock.write_text("")
    pid_path = tmp_path / "daemon.pid"
    pid_path.write_text("424242\n")

    states = iter([True, False, False, False])
    monkeypatch.setattr(daemon_spawn, "_pid_alive", lambda pid: next(states, False))
    monkeypatch.setattr(daemon_spawn, "_KILL_GRACE_S", 0.2, raising=False)
    monkeypatch.setattr(daemon_spawn, "_KILL_POLL_S", 0.02, raising=False)
    signals: list[tuple[int, int]] = []
    monkeypatch.setattr(daemon_spawn.os, "kill", lambda pid, sig: signals.append((pid, sig)))

    daemon_spawn._kill_stale_daemon(sock)

    assert (424242, signal.SIGTERM) in signals
    assert not any(sig == signal.SIGKILL for _, sig in signals), "进程已优雅退出,不该 SIGKILL"



def test_daemon_build_log_handlers_uses_rotating_file(tmp_path):
    from logging.handlers import RotatingFileHandler

    from argos.daemon import __main__ as dmain

    handlers = dmain._build_log_handlers(tmp_path / "daemon.sock")
    rotating = [h for h in handlers if isinstance(h, RotatingFileHandler)]
    try:
        assert rotating, "daemon 日志应走 RotatingFileHandler(有界轮转)"
        rfh = rotating[0]
        assert Path(rfh.baseFilename).name == "daemon.log"
        assert rfh.maxBytes > 0, "必须设大小上限"
        assert rfh.backupCount > 0, "必须保留若干备份"
    finally:
        for h in handlers:
            try:
                h.close()
            except Exception:
                pass


def test_daemon_boot_log_path_is_separate_from_run_log(tmp_path):
    sock = tmp_path / "daemon.sock"
    boot = daemon_spawn._daemon_log_path(sock)
    assert boot.name == "daemon-boot.log", "TUI 重定向应落 daemon-boot.log"
    assert boot.name != "daemon.log", "boot 日志不能与 daemon 运行日志同名(否则轮转/重定向相互冲突)"
