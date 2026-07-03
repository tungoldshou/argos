"""Internal documentation."""
from __future__ import annotations

import os
import signal
import socket as _stdlib_socket
import sys
import time
from pathlib import Path
from typing import Iterator
from unittest import mock

import pytest

import argos.daemon.__main__ as daemon_main
from argos.daemon.__main__ import _cmd_stop, _cmd_status, _socket_alive


# ── helpers ──────────────────────────────────────────────────────────────────

def _write_pid(path: Path, pid: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{pid}\n", encoding="utf-8")


def _make_listening_socket(path: Path) -> _stdlib_socket.socket:
    """Internal documentation."""
    srv = _stdlib_socket.socket(_stdlib_socket.AF_UNIX, _stdlib_socket.SOCK_STREAM)
    srv.bind(str(path))
    srv.listen(1)
    return srv



def test_socket_alive_no_file(tmp_path: Path) -> None:
    """Internal documentation."""
    assert _socket_alive(tmp_path / "nonexistent.sock") is False


def test_default_socket_paths_honor_env_local_config(tmp_path: Path, monkeypatch) -> None:
    """daemon and CLI defaults must use the same configured socket path as TUI."""
    from argos import config as C
    from argos.daemon.socket import default_socket_path

    sock = tmp_path / "configured.sock"
    monkeypatch.delenv("ARGOS_DAEMON_SOCKET", raising=False)
    monkeypatch.setattr(C, "_ENV", {"ARGOS_DAEMON_SOCKET": str(sock)})

    assert daemon_main._default_socket_path() == sock
    assert default_socket_path() == sock


def test_default_state_paths_honor_argos_config_dir(tmp_path: Path, monkeypatch) -> None:
    from argos import config as C
    from argos.daemon.socket import default_socket_path

    cfg_dir = tmp_path / ".argos"
    monkeypatch.delenv("ARGOS_DAEMON_SOCKET", raising=False)
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(cfg_dir))
    monkeypatch.setattr(C, "_ENV", {})

    assert daemon_main._default_socket_path() == cfg_dir / "daemon.sock"
    assert default_socket_path() == cfg_dir / "daemon.sock"
    assert daemon_main._default_runs_dir() == cfg_dir / "runs"
    assert daemon_main._default_index_path() == cfg_dir / "runs" / "index.json"
    assert daemon_main._default_pid_path() == cfg_dir / "daemon.pid"


def test_default_conductor_dir_honors_argos_config_dir(tmp_path: Path, monkeypatch) -> None:
    from argos import config as C
    from argos.daemon.manager import RunManager
    from argos.daemon.server import DaemonHTTPServer

    cfg_dir = tmp_path / ".argos"
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(cfg_dir))
    monkeypatch.setattr(C, "_ENV", {})

    manager = RunManager(runs_dir=tmp_path / "runs", index_path=tmp_path / "runs" / "index.json")
    server = DaemonHTTPServer(manager=manager, socket_path=tmp_path / "daemon.sock")

    assert daemon_main._default_conductor_dir() == cfg_dir / "conductor"
    assert server._conductor_orders_dir() == cfg_dir / "conductor"


def test_socket_alive_dead_socket(tmp_path: Path) -> None:
    """Internal documentation."""
    sock_path = tmp_path / "dead.sock"
    sock_path.touch()
    assert _socket_alive(sock_path) is False


def test_socket_alive_live_socket(tmp_path: Path) -> None:
    """Internal documentation."""
    import tempfile
    with tempfile.TemporaryDirectory(dir="/tmp", prefix="argtest_") as td:
        sock_path = Path(td) / "t.sock"
        srv = _make_listening_socket(sock_path)
        try:
            assert _socket_alive(sock_path) is True
        finally:
            srv.close()
            sock_path.unlink(missing_ok=True)



def test_stop_no_daemon(tmp_path: Path, capsys) -> None:
    """Internal documentation."""
    pid_path = tmp_path / "daemon.pid"
    sock_path = tmp_path / "daemon.sock"

    rc = _cmd_stop(pid_path, sock_path)

    assert rc == 0
    captured = capsys.readouterr()
    assert "未运行" in captured.out


def test_stop_stale_pid_no_socket(tmp_path: Path, capsys) -> None:
    """Internal documentation."""
    pid_path = tmp_path / "daemon.pid"
    sock_path = tmp_path / "daemon.sock"

    _write_pid(pid_path, 9999999)

    with mock.patch("argos.daemon.pidfile.is_alive", return_value=False):
        rc = _cmd_stop(pid_path, sock_path)

    assert rc == 0
    assert not pid_path.exists(), "残留 pid 文件应已被清理"
    captured = capsys.readouterr()
    assert "未运行" in captured.out


def test_stop_running_daemon_exits_cleanly(tmp_path: Path, capsys) -> None:
    """Internal documentation."""
    pid_path = tmp_path / "daemon.pid"
    sock_path = tmp_path / "daemon.sock"

    _write_pid(pid_path, 12345)

    alive_calls: list[bool] = [True, False]

    def _mock_socket_alive(path: Path) -> bool:
        return alive_calls.pop(0) if alive_calls else False

    with (
        mock.patch("argos.daemon.pidfile.is_alive", return_value=True),
        mock.patch("argos.daemon.__main__._socket_alive", side_effect=_mock_socket_alive),
        mock.patch("os.kill") as mock_kill,
    ):
        rc = _cmd_stop(pid_path, sock_path, timeout=2.0)

    assert rc == 0
    mock_kill.assert_called_once_with(12345, signal.SIGTERM)
    captured = capsys.readouterr()
    assert "已停止" in captured.out


def test_stop_daemon_timeout(tmp_path: Path, capsys) -> None:
    """Internal documentation."""
    pid_path = tmp_path / "daemon.pid"
    sock_path = tmp_path / "daemon.sock"

    _write_pid(pid_path, 12345)

    with (
        mock.patch("argos.daemon.pidfile.is_alive", return_value=True),
        mock.patch("argos.daemon.__main__._socket_alive", return_value=True),
        mock.patch("os.kill"),
        mock.patch("time.sleep"),
    ):
        rc = _cmd_stop(pid_path, sock_path, timeout=0.05)

    assert rc == 1
    captured = capsys.readouterr()
    assert "警告" in captured.err or "未完全退出" in captured.err


def test_stop_no_pid_file_but_socket_exists(tmp_path: Path, capsys) -> None:
    """Internal documentation."""
    pid_path = tmp_path / "daemon.pid"
    sock_path = tmp_path / "daemon.sock"
    sock_path.touch()
    with mock.patch("argos.daemon.__main__._socket_alive", return_value=True):
        rc = _cmd_stop(pid_path, sock_path)

    assert rc == 1
    captured = capsys.readouterr()
    assert "pid" in captured.err.lower()


def test_stop_process_already_gone(tmp_path: Path, capsys) -> None:
    """Internal documentation."""
    pid_path = tmp_path / "daemon.pid"
    sock_path = tmp_path / "daemon.sock"

    _write_pid(pid_path, 12345)

    with (
        mock.patch("argos.daemon.pidfile.is_alive", return_value=True),
        mock.patch("argos.daemon.__main__._socket_alive", return_value=False),
        mock.patch("os.kill", side_effect=ProcessLookupError),
    ):
        rc = _cmd_stop(pid_path, sock_path)

    assert rc == 0
    captured = capsys.readouterr()
    assert "未运行" in captured.out



def test_status_not_running(tmp_path: Path, capsys) -> None:
    """Internal documentation."""
    pid_path = tmp_path / "daemon.pid"
    sock_path = tmp_path / "daemon.sock"

    rc = _cmd_status(pid_path, sock_path)

    assert rc == 1
    captured = capsys.readouterr()
    assert "未运行" in captured.out


def test_status_running(tmp_path: Path, capsys) -> None:
    """Internal documentation."""
    pid_path = tmp_path / "daemon.pid"
    sock_path = tmp_path / "daemon.sock"

    _write_pid(pid_path, 42)

    with (
        mock.patch("argos.daemon.pidfile.is_alive", return_value=True),
        mock.patch("argos.daemon.__main__._socket_alive", return_value=True),
        mock.patch("argos.daemon.__main__._query_version_sync", return_value="0.1.0"),
    ):
        rc = _cmd_status(pid_path, sock_path)

    assert rc == 0
    captured = capsys.readouterr()
    assert "运行中" in captured.out
    assert "42" in captured.out
    assert "0.1.0" in captured.out


def test_status_shows_uptime(tmp_path: Path, capsys) -> None:
    """Internal documentation."""
    pid_path = tmp_path / "daemon.pid"
    sock_path = tmp_path / "daemon.sock"

    _write_pid(pid_path, 99)

    past_ts = time.time() - 3600
    os.utime(pid_path, (past_ts, past_ts))

    with (
        mock.patch("argos.daemon.pidfile.is_alive", return_value=True),
        mock.patch("argos.daemon.__main__._socket_alive", return_value=True),
        mock.patch("argos.daemon.__main__._query_version_sync", return_value=None),
    ):
        rc = _cmd_status(pid_path, sock_path)

    assert rc == 0
    captured = capsys.readouterr()
    assert "01:" in captured.out, f"uptime 应含 '01:',实际输出:{captured.out!r}"


def test_status_stale_pid(tmp_path: Path, capsys) -> None:
    """Internal documentation."""
    pid_path = tmp_path / "daemon.pid"
    sock_path = tmp_path / "daemon.sock"

    _write_pid(pid_path, 9999999)

    with (
        mock.patch("argos.daemon.pidfile.is_alive", return_value=False),
        mock.patch("argos.daemon.__main__._socket_alive", return_value=False),
    ):
        rc = _cmd_status(pid_path, sock_path)

    assert rc == 1
    captured = capsys.readouterr()
    assert "未运行" in captured.out



def test_main_stop_subcommand(tmp_path: Path, capsys) -> None:
    """Internal documentation."""
    pid_path = tmp_path / "daemon.pid"
    sock_path = tmp_path / "daemon.sock"

    with (
        mock.patch.object(
            sys, "argv",
            ["argosd",
             "--pid-path", str(pid_path),
             "--socket-path", str(sock_path),
             "stop"],
        ),
        mock.patch("argos.daemon.__main__._cmd_stop", return_value=0) as mock_stop,
    ):
        rc = daemon_main.main()

    assert rc == 0
    mock_stop.assert_called_once()


def test_main_status_subcommand(tmp_path: Path, capsys) -> None:
    """Internal documentation."""
    pid_path = tmp_path / "daemon.pid"
    sock_path = tmp_path / "daemon.sock"

    with (
        mock.patch.object(
            sys, "argv",
            ["argosd",
             "--pid-path", str(pid_path),
             "--socket-path", str(sock_path),
             "status"],
        ),
        mock.patch("argos.daemon.__main__._cmd_status", return_value=1) as mock_status,
    ):
        rc = daemon_main.main()

    assert rc == 1
    mock_status.assert_called_once()


def test_main_no_subcommand_calls_serve(tmp_path: Path) -> None:
    """Internal documentation."""
    pid_path = tmp_path / "daemon.pid"
    sock_path = tmp_path / "daemon.sock"

    with (
        mock.patch.object(
            sys, "argv",
            ["argosd",
             "--pid-path", str(pid_path),
             "--socket-path", str(sock_path)],
        ),
        mock.patch("asyncio.run", return_value=0) as mock_run,
    ):
        rc = daemon_main.main()

    assert rc == 0
    mock_run.assert_called_once()
    mock_run.call_args.args[0].close()


def test_main_start_subcommand_calls_serve(tmp_path: Path) -> None:
    """Internal documentation."""
    pid_path = tmp_path / "daemon.pid"
    sock_path = tmp_path / "daemon.sock"

    with (
        mock.patch.object(
            sys, "argv",
            ["argosd",
             "--pid-path", str(pid_path),
             "--socket-path", str(sock_path),
             "start"],
        ),
        mock.patch("asyncio.run", return_value=0) as mock_run,
    ):
        rc = daemon_main.main()

    assert rc == 0
    mock_run.assert_called_once()
    mock_run.call_args.args[0].close()
