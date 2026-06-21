"""argosd stop / status / restart CLI 子命令单元测试。

策略:
- 用 tmp_path 伪造 pid 文件 + socket;不启动真实 daemon 进程。
- os.kill / _socket_alive 走 mock 隔离,避免真实信号和网络调用。
- 不依赖 asyncio / DaemonHTTPServer,只测 CLI 层逻辑。
"""
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

# 被测模块
import argos.daemon.__main__ as daemon_main
from argos.daemon.__main__ import _cmd_stop, _cmd_status, _socket_alive


# ── helpers ──────────────────────────────────────────────────────────────────

def _write_pid(path: Path, pid: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{pid}\n", encoding="utf-8")


def _make_listening_socket(path: Path) -> _stdlib_socket.socket:
    """在 path 创建并监听 Unix socket,返回 server socket(调用方 close)。"""
    srv = _stdlib_socket.socket(_stdlib_socket.AF_UNIX, _stdlib_socket.SOCK_STREAM)
    srv.bind(str(path))
    srv.listen(1)
    return srv


# ── _socket_alive 单元测试 ────────────────────────────────────────────────────

def test_socket_alive_no_file(tmp_path: Path) -> None:
    """不存在的 socket 路径 → False。"""
    assert _socket_alive(tmp_path / "nonexistent.sock") is False


def test_socket_alive_dead_socket(tmp_path: Path) -> None:
    """socket 文件存在但无监听者 → False。"""
    sock_path = tmp_path / "dead.sock"
    # 创建文件但不监听
    sock_path.touch()
    assert _socket_alive(sock_path) is False


def test_socket_alive_live_socket(tmp_path: Path) -> None:
    """socket 文件存在且有 daemon 监听 → True。

    Unix socket 路径最长 ~104 字节;tmp_path 可能很长,用 /tmp 下的短路径。
    """
    import tempfile
    # 在 /tmp 下用固定短名,避免 macOS /private/var/… 超过内核限制
    with tempfile.TemporaryDirectory(dir="/tmp", prefix="argtest_") as td:
        sock_path = Path(td) / "t.sock"
        srv = _make_listening_socket(sock_path)
        try:
            assert _socket_alive(sock_path) is True
        finally:
            srv.close()
            sock_path.unlink(missing_ok=True)


# ── _cmd_stop 测试 ────────────────────────────────────────────────────────────

def test_stop_no_daemon(tmp_path: Path, capsys) -> None:
    """pid 文件不存在、socket 不存在 → 报'未运行',返回 0。"""
    pid_path = tmp_path / "daemon.pid"
    sock_path = tmp_path / "daemon.sock"

    rc = _cmd_stop(pid_path, sock_path)

    assert rc == 0
    captured = capsys.readouterr()
    assert "未运行" in captured.out


def test_stop_stale_pid_no_socket(tmp_path: Path, capsys) -> None:
    """pid 文件存在但进程已死、socket 不在 → 清理残留 pid 文件,返回 0。"""
    pid_path = tmp_path / "daemon.pid"
    sock_path = tmp_path / "daemon.sock"

    # 写一个不存在的 pid
    _write_pid(pid_path, 9999999)

    with mock.patch("argos.daemon.pidfile.is_alive", return_value=False):
        rc = _cmd_stop(pid_path, sock_path)

    assert rc == 0
    assert not pid_path.exists(), "残留 pid 文件应已被清理"
    captured = capsys.readouterr()
    assert "未运行" in captured.out


def test_stop_running_daemon_exits_cleanly(tmp_path: Path, capsys) -> None:
    """pid 文件 + socket 均在、进程在运行 → 发 SIGTERM,等 socket 消失,返回 0。"""
    pid_path = tmp_path / "daemon.pid"
    sock_path = tmp_path / "daemon.sock"

    _write_pid(pid_path, 12345)

    # socket 在第一次检测时"活",SIGTERM 后立即消失
    alive_calls: list[bool] = [True, False]  # 第1次=True(发信号前校验),第2次=False(已退出)

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
    """daemon 不响应 SIGTERM,超时后返回 1 并打印警告。"""
    pid_path = tmp_path / "daemon.pid"
    sock_path = tmp_path / "daemon.sock"

    _write_pid(pid_path, 12345)

    with (
        mock.patch("argos.daemon.pidfile.is_alive", return_value=True),
        # socket 始终活着(daemon 不退出)
        mock.patch("argos.daemon.__main__._socket_alive", return_value=True),
        mock.patch("os.kill"),
        # 让 time.sleep 几乎不等(加速测试),但 time.monotonic 正常走
        mock.patch("time.sleep"),
        # 缩短超时
    ):
        rc = _cmd_stop(pid_path, sock_path, timeout=0.05)

    assert rc == 1
    captured = capsys.readouterr()
    assert "警告" in captured.err or "未完全退出" in captured.err


def test_stop_no_pid_file_but_socket_exists(tmp_path: Path, capsys) -> None:
    """socket 在但 pid 文件不在 → 无法发信号,返回 1。"""
    pid_path = tmp_path / "daemon.pid"
    sock_path = tmp_path / "daemon.sock"
    # 创建一个空文件让 socket_path.exists() 为 True,避免早期"未运行"退出
    sock_path.touch()
    # 用 mock 让 _socket_alive 返回 True
    with mock.patch("argos.daemon.__main__._socket_alive", return_value=True):
        rc = _cmd_stop(pid_path, sock_path)

    assert rc == 1
    captured = capsys.readouterr()
    assert "pid" in captured.err.lower()


def test_stop_process_already_gone(tmp_path: Path, capsys) -> None:
    """os.kill 抛 ProcessLookupError(进程已不存在)→ 视为已停止,返回 0。"""
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


# ── _cmd_status 测试 ─────────────────────────────────────────────────────────

def test_status_not_running(tmp_path: Path, capsys) -> None:
    """pid / socket 均不在 → 报'未运行',返回 1。"""
    pid_path = tmp_path / "daemon.pid"
    sock_path = tmp_path / "daemon.sock"

    rc = _cmd_status(pid_path, sock_path)

    assert rc == 1
    captured = capsys.readouterr()
    assert "未运行" in captured.out


def test_status_running(tmp_path: Path, capsys) -> None:
    """pid + socket 均在且进程活跃 → 打印运行信息,返回 0。"""
    pid_path = tmp_path / "daemon.pid"
    sock_path = tmp_path / "daemon.sock"

    _write_pid(pid_path, 42)

    with (
        mock.patch("argos.daemon.pidfile.is_alive", return_value=True),
        mock.patch("argos.daemon.__main__._socket_alive", return_value=True),
        # 跳过版本查询(socket 是 mock 的,无真实 HTTP)
        mock.patch("argos.daemon.__main__._query_version_sync", return_value="0.1.0"),
    ):
        rc = _cmd_status(pid_path, sock_path)

    assert rc == 0
    captured = capsys.readouterr()
    assert "运行中" in captured.out
    assert "42" in captured.out          # pid 显示
    assert "0.1.0" in captured.out       # 版本号显示


def test_status_shows_uptime(tmp_path: Path, capsys) -> None:
    """pid 文件存在时输出 uptime(基于 pid 文件 mtime)。"""
    pid_path = tmp_path / "daemon.pid"
    sock_path = tmp_path / "daemon.sock"

    _write_pid(pid_path, 99)

    # 手动把 pid 文件 mtime 设成 1 小时前
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
    # uptime 格式 HH:MM:SS,1 小时前应包含 "01:"
    assert "01:" in captured.out, f"uptime 应含 '01:',实际输出:{captured.out!r}"


def test_status_stale_pid(tmp_path: Path, capsys) -> None:
    """pid 文件存在但进程已死 + socket 不在 → 报'未运行' + 残留 pid 提示。"""
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


# ── main() argparse 集成测试 ─────────────────────────────────────────────────

def test_main_stop_subcommand(tmp_path: Path, capsys) -> None:
    """main() 解析 'stop' 子命令并调用 _cmd_stop。
    注意:全局选项(--pid-path / --socket-path)必须在子命令名之前。
    """
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
    """main() 解析 'status' 子命令并调用 _cmd_status。"""
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
    """main() 无子命令 → 调用 asyncio.run(_serve(...))。"""
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


def test_main_start_subcommand_calls_serve(tmp_path: Path) -> None:
    """main() 'start' 子命令 → 同样调用 asyncio.run(_serve(...))。"""
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
