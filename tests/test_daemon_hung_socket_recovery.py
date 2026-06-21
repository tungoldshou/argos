"""假死 daemon 占 socket → 自愈恢复(2026-06-22 真机 bug)。

根因(真机实测):两个 7 天前启动的 dev daemon 事件循环假死——内核 listen backlog
仍接受 connect(),但进程永不响应 /health。这一个"连得上但不响应"的状态把三层击穿:

  1. TUI 探针 _probe 拿不到 health 响应 → 判不可达 → 不复用;
  2. _kill_stale_daemon 只在 "_probe True 且版本不兼容" 分支调用,假死(_probe False)
     时被跳过 → 僵尸活着;
  3. 新 argosd 的 check_socket_available 用 connect() 成功当"已占用" → 抛错 rc=1 退出
     → 永久回退 inline。spawn 又用 stderr=DEVNULL 把这条致命错误吞掉。

  → 死锁:既不能复用、又不被杀、还堵住替代者。每次启动都永久 inline。

修(防御纵深三处):
  B1 check_socket_available 改为 connect 后真发 /health 并要求响应;无响应=假死→清理接管。
  B2 probe_or_spawn 在 socket 存在但 _probe 失败(假死)时,spawn 前先 _kill_stale_daemon。
  B3 spawn 不再 DEVNULL stderr,重定向到 ~/.argos/daemon.log;启动失败时回显其尾部。
"""
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
    """短路径 socket(macOS AF_UNIX 路径上限 ~104 字符,pytest tmp_path 太长会 bind 失败)。"""
    d = tempfile.mkdtemp(prefix="argos_t_", dir="/tmp")
    try:
        yield Path(d) / "d.sock"
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ── 测试夹具:真 unix-socket 服务器(响应 / 假死) ──────────────────────────────

def _responding_server(path):
    """绑定 + 监听 + 真响应 /health 200 的服务器(模拟健康 daemon)。"""
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
    """绑定 + 监听但**永不 accept**(模拟假死 daemon):connect 经 backlog 成功,但永不响应。"""
    srv = _sock.socket(_sock.AF_UNIX, _sock.SOCK_STREAM)
    srv.bind(str(path))
    srv.listen(1)
    return srv  # 故意不 accept


# ── B1: check_socket_available 必须靠 health 响应判活,不能只看 connect ──────────

def test_check_socket_available_raises_when_daemon_responds_health(short_sock):
    """真响应 /health 200 的 daemon = 真占用 → raise(不许双开)。"""
    srv = _responding_server(short_sock)
    try:
        with pytest.raises(RuntimeError, match="already in use"):
            daemon_socket.check_socket_available(short_sock)
    finally:
        srv.close()


def test_check_socket_available_treats_unresponsive_as_dead(short_sock, monkeypatch):
    """连得上但不响应 /health 的假死 daemon → 不 raise,且清掉 socket 让新 daemon 接管。

    这是真机死锁的核心:旧逻辑 connect 成功就抛 'already in use' → 新 daemon 永远起不来。
    """
    monkeypatch.setattr(daemon_socket, "_HEALTH_TIMEOUT", 0.2, raising=False)
    srv = _hung_server(short_sock)
    try:
        # 不该抛异常(假死不等于真占用)
        daemon_socket.check_socket_available(short_sock)
        # 且应清掉残留 socket,让后续 bind 能接管
        assert not short_sock.exists(), "假死 daemon 的 socket 应被清理以允许接管"
    finally:
        srv.close()


def test_check_socket_available_returns_when_no_socket(short_sock):
    """socket 文件不存在 → 直接返回(可用)。"""
    daemon_socket.check_socket_available(short_sock)  # 不抛即通过


def test_check_socket_available_cleans_refused_socket(short_sock):
    """socket 文件在但 connect 被拒(死 daemon 残留文件)→ 清理 + 返回。"""
    short_sock.write_text("")  # 普通文件,connect 必失败(非 socket)
    daemon_socket.check_socket_available(short_sock)
    assert not short_sock.exists(), "不可连接的残留 socket 文件应被清掉"


# ── B2: probe_or_spawn 在 socket 假死(连得上但 health 失败)时,spawn 前先清理 ────

@pytest.mark.asyncio
async def test_unresponsive_socket_is_killed_before_spawn(monkeypatch, tmp_path):
    """_probe 失败但 socket 文件存在(假死 daemon 占着)→ spawn 前必须 _kill_stale_daemon。

    不清理的话,新 argosd 的 check_socket_available 会因 connect 成功误判'已占用'→ rc=1
    → 永久 inline。这正是真机死锁。
    """
    sock = tmp_path / "daemon.sock"
    sock.write_text("")  # socket 文件存在(假死 daemon 占着)
    order: list[str] = []

    async def fake_probe(_p):
        return False  # 假死:health 不响应

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
    """_probe 失败且 socket 文件不存在(干净环境首启)→ 不调 _kill_stale_daemon,直接 spawn。"""
    sock = tmp_path / "daemon.sock"  # 不创建文件
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


# ── B3: spawn 失败时,被 DEVNULL 吞掉的 daemon 启动错误必须被回显 ───────────────

@pytest.mark.asyncio
async def test_spawn_failure_surfaces_daemon_log(monkeypatch, tmp_path, caplog):
    """argosd 启动失败(early exit)时,daemon 日志尾部必须经 log.warning 回显(不再静默)。"""
    import logging

    sock = tmp_path / "daemon.sock"

    async def fake_probe(_p):
        return False  # 永不就绪

    class _P:
        returncode = 1  # 子进程已退出(失败)

    async def fake_exec(*a, **k):
        # 模拟 daemon 子进程把致命错误写进它继承的输出 fd(= probe_or_spawn 打开的 daemon.log)
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


# ── B4: _kill_stale_daemon 必须确认死亡——SIGTERM 无效则升级 SIGKILL,杜绝孤儿泄漏 ──

def test_kill_stale_daemon_escalates_to_sigkill_when_sigterm_ignored(monkeypatch, tmp_path):
    """SIGTERM 后进程仍存活(假死忽略信号)→ 升级 SIGKILL。

    真机根因:旧 _kill_stale_daemon 发完 SIGTERM 立即删文件返回,假死 daemon 抗 SIGTERM
    不死 → 成孤儿继续占着旧 socket inode(lsof 见两个 daemon 绑同一路径)。
    """
    import signal

    sock = tmp_path / "daemon.sock"
    sock.write_text("")
    pid_path = tmp_path / "daemon.pid"
    pid_path.write_text("424242\n")

    monkeypatch.setattr(daemon_spawn, "_pid_alive", lambda pid: True)  # 恒活=忽略 SIGTERM
    monkeypatch.setattr(daemon_spawn, "_KILL_GRACE_S", 0.1, raising=False)
    monkeypatch.setattr(daemon_spawn, "_KILL_POLL_S", 0.02, raising=False)
    signals: list[tuple[int, int]] = []
    monkeypatch.setattr(daemon_spawn.os, "kill", lambda pid, sig: signals.append((pid, sig)))

    daemon_spawn._kill_stale_daemon(sock)

    assert (424242, signal.SIGTERM) in signals, "应先发 SIGTERM"
    assert (424242, signal.SIGKILL) in signals, "SIGTERM 无效必须升级 SIGKILL,杜绝孤儿"
    assert not pid_path.exists() and not sock.exists()


def test_kill_stale_daemon_no_sigkill_when_process_exits(monkeypatch, tmp_path):
    """SIGTERM 后进程优雅退出 → 不发 SIGKILL。"""
    import signal

    sock = tmp_path / "daemon.sock"
    sock.write_text("")
    pid_path = tmp_path / "daemon.pid"
    pid_path.write_text("424242\n")

    # 第1次(决定 SIGTERM)=活;之后(等待轮询/最终检查)=已退出
    states = iter([True, False, False, False])
    monkeypatch.setattr(daemon_spawn, "_pid_alive", lambda pid: next(states, False))
    monkeypatch.setattr(daemon_spawn, "_KILL_GRACE_S", 0.2, raising=False)
    monkeypatch.setattr(daemon_spawn, "_KILL_POLL_S", 0.02, raising=False)
    signals: list[tuple[int, int]] = []
    monkeypatch.setattr(daemon_spawn.os, "kill", lambda pid, sig: signals.append((pid, sig)))

    daemon_spawn._kill_stale_daemon(sock)

    assert (424242, signal.SIGTERM) in signals
    assert not any(sig == signal.SIGKILL for _, sig in signals), "进程已优雅退出,不该 SIGKILL"


# ── daemon.log 轮转:daemon 进程内结构化日志走 RotatingFileHandler(有界),不再无限增长 ──

def test_daemon_build_log_handlers_uses_rotating_file(tmp_path):
    """daemon logging 必须配 RotatingFileHandler 指向 daemon.log,且有大小上限 + 备份数。"""
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
    """TUI 截获启动期输出的 boot 日志与 daemon 运行日志必须是不同文件(职责分离,互不污染)。"""
    sock = tmp_path / "daemon.sock"
    boot = daemon_spawn._daemon_log_path(sock)
    assert boot.name == "daemon-boot.log", "TUI 重定向应落 daemon-boot.log"
    assert boot.name != "daemon.log", "boot 日志不能与 daemon 运行日志同名(否则轮转/重定向相互冲突)"
