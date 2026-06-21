"""`python -m argos.daemon` 入口(spec §2.10 + D13)。

同一入口也由 `argosd` console script 暴露,以及 TUI 启动时探测 socket 不在则自动 spawn。
(没有 `argos daemon` 子命令 —— daemon 不挂在 `argos` CLI 下;用 `argosd` 或 `python -m argos.daemon`。)

子命令:
  argosd              (无参数)  start daemon (当前行为,后向兼容)
  argosd start        同上,显式 start
  argosd stop         优雅停止:发 SIGTERM → 等 socket 消失 → 报告
  argosd status       报告运行状态(pid / socket / uptime / version)
  argosd restart      stop 后 start (detached)
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import socket as _stdlib_socket
import subprocess
import sys
import time
from pathlib import Path

log = logging.getLogger(__name__)


def _default_runs_dir() -> Path:
    return Path.home() / ".argos" / "runs"


def _default_index_path() -> Path:
    return Path.home() / ".argos" / "runs" / "index.json"


def _default_socket_path() -> Path:
    return Path.home() / ".argos" / "daemon.sock"


def _default_pid_path() -> Path:
    return Path.home() / ".argos" / "daemon.pid"


async def _serve(args: argparse.Namespace) -> int:
    from argos.daemon.manager import RunManager
    from argos.daemon.pidfile import write_pid, remove as remove_pid
    from argos.daemon.server import DaemonHTTPServer
    from argos.daemon.socket import check_socket_available, ensure_socket_mode
    from argos.daemon.supervision import graceful_shutdown, install_signal_handlers

    runs_dir = Path(args.runs_dir).expanduser()
    index_path = Path(args.index_path).expanduser()
    socket_path = Path(args.socket_path).expanduser()
    pid_path = Path(args.pid_path).expanduser()

    runs_dir.mkdir(parents=True, exist_ok=True)
    index_path.parent.mkdir(parents=True, exist_ok=True)

    # 检查 socket 占用
    try:
        check_socket_available(socket_path)
    except RuntimeError as e:
        print(f"[daemon] {e}", file=sys.stderr)
        return 1

    # P1 通电:装配真实组件 + loop_factory ──────────────────────────────
    # 无 worker key → loop_factory=_NO_KEY 哨兵,daemon 仍能启动;create_run 明确拒绝并说明原因。
    from argos.daemon.server import _NO_KEY
    loop_factory = _NO_KEY  # 默认无 key 状态
    components = None
    try:
        from argos.app_factory import build_components, build_loop_factory
        components = build_components()
        loop_factory = build_loop_factory(components)
        log.info("daemon: AgentLoop factory 装配完成(model=%s)", components.config.model_tier)
    except RuntimeError as e:
        # 诚实降级:无 key → daemon 起得来,但 create_run 会明确拒绝(_NO_KEY 哨兵)
        print(f"[daemon] 警告:无法装配 AgentLoop({e});daemon 以无 key 模式启动,create_run 将拒绝。",
              file=sys.stderr)
        log.warning("daemon: loop_factory 装配失败: %s", e)
    except Exception as e:  # noqa: BLE001
        print(f"[daemon] 警告:装配异常({e});daemon 以无 key 模式启动。", file=sys.stderr)
        log.warning("daemon: loop_factory 装配异常: %s", e)

    manager = RunManager(runs_dir=runs_dir, index_path=index_path)
    # 启动恢复
    recovered = manager.recover()
    if recovered:
        log.info("daemon: recovered %d runs: %s", len(recovered), recovered)

    # P5b §9 自治面：conductor supervisor（tick loop 后台协程）
    # 广播函数：向 _conductor 虚拟 run_id 的 SSE 扇出通道投事件
    from argos.daemon.conductor_supervisor import ConductorSupervisor, CONDUCTOR_RUN_ID
    conductor_orders_dir = Path.home() / ".argos" / "conductor"

    async def _conductor_broadcast(ev_dict: dict) -> None:
        """把 conductor 事件存入 _conductor 流并扇出到 SSE 订阅者。"""
        manager.store.append(CONDUCTOR_RUN_ID, ev_dict)
        await manager.fanout(CONDUCTOR_RUN_ID, ev_dict)

    conductor_supervisor = ConductorSupervisor(
        orders_dir=conductor_orders_dir,
        tick_interval=float(os.environ.get("ARGOS_CONDUCTOR_TICK_INTERVAL", "30")),
        broadcast_fn=_conductor_broadcast,
    )

    # P3b §6 行为账本存储(全局单例,所有 run 共享同一个目录)
    from argos.ledger.store import LedgerStore
    ledger_store = LedgerStore()

    server = DaemonHTTPServer(
        manager=manager,
        socket_path=socket_path,
        # components 路径(优先):per-run 独享 sandbox/gate/broker,并发不串台。
        # 无 components(装配失败)时退回 loop_factory=_NO_KEY 哨兵诚实拒绝。
        components=components,
        loop_factory=loop_factory,
        gate=components.gate if components is not None else None,
        ledger_store=ledger_store,
        conductor_supervisor=conductor_supervisor,
    )
    await server.start()
    # P5b §9:启动 conductor tick 后台协程
    conductor_supervisor.start()

    # 写 PID
    write_pid(pid_path, os.getpid())
    ensure_socket_mode(socket_path)

    print(f"[daemon] started, socket={socket_path}, pid={os.getpid()}")

    # 信号处理
    loop = asyncio.get_event_loop()
    shutdown_event = asyncio.Event()

    def _on_signal() -> None:
        if not shutdown_event.is_set():
            log.info("daemon: signal received, scheduling shutdown")
            shutdown_event.set()

    install_signal_handlers(loop, _on_signal)

    try:
        await shutdown_event.wait()
    finally:
        # P5b §9:先停 conductor tick(干净取消,不留孤儿任务)
        try:
            await conductor_supervisor.stop()
        except Exception as e:  # noqa: BLE001
            log.warning("daemon: conductor_supervisor.stop() failed: %s", e)
        await graceful_shutdown(manager, server, socket_path)
        remove_pid(pid_path)
        # 清理 AppComponents(关闭 sandbox/store/browser/mcp 子进程)
        if components is not None:
            try:
                components.close()
            except Exception as e:  # noqa: BLE001
                log.warning("daemon: components.close() failed: %s", e)
    return 0


# ── 子命令实现 ──────────────────────────────────────────────────────────────

def _socket_alive(socket_path: Path) -> bool:
    """检测 socket 是否有 daemon 活跃监听。"""
    if not socket_path.exists():
        return False
    s = _stdlib_socket.socket(_stdlib_socket.AF_UNIX, _stdlib_socket.SOCK_STREAM)
    try:
        s.settimeout(0.5)
        s.connect(str(socket_path))
        return True
    except (ConnectionRefusedError, FileNotFoundError, OSError):
        return False
    finally:
        try:
            s.close()
        except OSError:
            pass


def _cmd_stop(
    pid_path: Path,
    socket_path: Path,
    *,
    timeout: float = 10.0,
) -> int:
    """argosd stop 实现:SIGTERM → 等 socket 消失 → 报告。"""
    from argos.daemon.pidfile import read_pid, is_alive

    pid = read_pid(pid_path)

    # 快速路径:pid 文件不存在或进程已死、socket 也不在 → 诚实说
    if pid is None and not socket_path.exists():
        print("daemon 未运行")
        return 0

    if pid is not None and not is_alive(pid):
        # 进程已死但 pid 文件残留 → 清理
        try:
            pid_path.unlink(missing_ok=True)
        except OSError:
            pass
        if not socket_path.exists():
            print("daemon 未运行 (残留 pid 文件已清理)")
            return 0

    if pid is None:
        # socket 在但 pid 文件没有 —— 无法发信号;提示用户
        print(f"daemon socket 存在于 {socket_path} 但无 pid 文件;无法优雅停止。",
              file=sys.stderr)
        return 1

    # 发 SIGTERM
    try:
        os.kill(pid, signal.SIGTERM)
        print(f"[daemon] SIGTERM 已发送 → pid={pid}")
    except ProcessLookupError:
        print("daemon 未运行 (进程已不存在)")
        # 清理残留文件
        pid_path.unlink(missing_ok=True)
        return 0
    except PermissionError as e:
        print(f"[daemon] 无权发送 SIGTERM: {e}", file=sys.stderr)
        return 1

    # 等待 socket 消失(轮询,最多 timeout 秒)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _socket_alive(socket_path):
            print("[daemon] 已停止")
            return 0
        time.sleep(0.2)

    print(f"[daemon] 警告:daemon 在 {timeout:.0f}s 内未完全退出(socket 仍在 {socket_path})",
          file=sys.stderr)
    return 1


def _cmd_status(
    pid_path: Path,
    socket_path: Path,
) -> int:
    """argosd status 实现:报告 running/not、pid、socket 路径、uptime(若可读)。"""
    from argos.daemon.pidfile import read_pid, is_alive

    pid = read_pid(pid_path)
    alive = pid is not None and is_alive(pid)
    socket_ok = _socket_alive(socket_path)

    if not alive and not socket_ok:
        print("daemon 未运行")
        if pid is not None:
            # 残留 pid 文件
            print(f"  (残留 pid 文件: {pid_path}, pid={pid})")
        return 1

    # 进程存在
    status_lines: list[str] = []
    status_lines.append("daemon 运行中")
    if pid is not None:
        status_lines.append(f"  pid       : {pid}")
    status_lines.append(f"  pid 文件  : {pid_path}")
    status_lines.append(f"  socket    : {socket_path} ({'可连接' if socket_ok else '不可连接'})")

    # 尝试读取 uptime(pid 文件修改时间作为启动时间近似)
    if pid_path.exists():
        try:
            start_ts = pid_path.stat().st_mtime
            uptime_s = time.time() - start_ts
            h, rem = divmod(int(uptime_s), 3600)
            m, s = divmod(rem, 60)
            status_lines.append(f"  uptime    : {h:02d}:{m:02d}:{s:02d}")
        except OSError:
            pass

    # 尝试向 /version 端点查询版本号
    if socket_ok:
        try:
            version_info = _query_version_sync(socket_path)
            if version_info:
                status_lines.append(f"  version   : {version_info}")
        except Exception:  # noqa: BLE001
            pass

    print("\n".join(status_lines))
    return 0


def _query_version_sync(socket_path: Path) -> str | None:
    """同步查询 daemon /version 端点,返回版本字符串或 None。"""
    try:
        s = _stdlib_socket.socket(_stdlib_socket.AF_UNIX, _stdlib_socket.SOCK_STREAM)
        s.settimeout(1.0)
        s.connect(str(socket_path))
        req = b"GET /version HTTP/1.1\r\nHost: daemon\r\nConnection: close\r\n\r\n"
        s.sendall(req)
        raw = b""
        while True:
            chunk = s.recv(4096)
            if not chunk:
                break
            raw += chunk
        s.close()
        # 解析 HTTP 响应体
        if b"\r\n\r\n" in raw:
            body_bytes = raw.split(b"\r\n\r\n", 1)[1]
            import json as _json
            data = _json.loads(body_bytes.decode("utf-8", errors="replace"))
            return data.get("version") or str(data)
        return None
    except Exception:  # noqa: BLE001
        return None


def _cmd_restart(args: argparse.Namespace) -> int:
    """argosd restart 实现:stop → start (detached)。"""
    pid_path = Path(args.pid_path).expanduser()
    socket_path = Path(args.socket_path).expanduser()

    # stop
    rc = _cmd_stop(pid_path, socket_path)
    if rc != 0:
        # 非 0 返回意味着真错误(非"未运行");已经打印了原因
        return rc

    # start (detached subprocess)
    print("[daemon] 正在重新启动…")
    _spawn_detached(args)
    print("[daemon] 已重新启动(后台运行)")
    return 0


def _spawn_detached(args: argparse.Namespace) -> None:
    """在后台 detach 启动 daemon 子进程。"""
    cmd = [
        sys.executable, "-m", "argos.daemon",
        "--runs-dir", args.runs_dir,
        "--index-path", args.index_path,
        "--socket-path", args.socket_path,
        "--pid-path", args.pid_path,
        "--log-level", args.log_level,
    ]
    # 双 fork / setsid 等价:start_new_session=True 让子进程脱离当前控制 tty
    subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


# ── 入口 ────────────────────────────────────────────────────────────────────

def main() -> int:
    p = argparse.ArgumentParser(
        prog="argosd",
        description="Argos background daemon — start / stop / status / restart",
    )
    # 全局选项(对所有子命令有效)
    p.add_argument("--runs-dir", default=str(_default_runs_dir()))
    p.add_argument("--index-path", default=str(_default_index_path()))
    p.add_argument("--socket-path", default=str(_default_socket_path()))
    p.add_argument("--pid-path", default=str(_default_pid_path()))
    p.add_argument("--log-level", default="info",
                   choices=["debug", "info", "warning", "error"])
    # --detach 仍保留(历史兼容;start 子命令时生效)
    p.add_argument("--detach", action="store_true",
                   help="detach from controlling tty (start subcommand only)")

    sub = p.add_subparsers(dest="subcmd")

    # start
    sub.add_parser("start", help="Start daemon (default when no subcommand given)")

    # stop
    stop_p = sub.add_parser("stop", help="Gracefully stop the running daemon")
    stop_p.add_argument("--timeout", type=float, default=10.0,
                        help="Seconds to wait for daemon to exit (default: 10)")

    # status
    sub.add_parser("status", help="Show daemon status (pid / socket / uptime / version)")

    # restart
    sub.add_parser("restart", help="Stop then start the daemon (detached)")

    args = p.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    pid_path = Path(args.pid_path).expanduser()
    socket_path = Path(args.socket_path).expanduser()

    # 无子命令 or "start" → 原有行为(启动 daemon)
    if args.subcmd in (None, "start"):
        if args.detach:
            _spawn_detached(args)
            print("[daemon] detached daemon started")
            return 0
        return asyncio.run(_serve(args))

    if args.subcmd == "stop":
        timeout = getattr(args, "timeout", 10.0)
        return _cmd_stop(pid_path, socket_path, timeout=timeout)

    if args.subcmd == "status":
        return _cmd_status(pid_path, socket_path)

    if args.subcmd == "restart":
        return _cmd_restart(args)

    # 未知子命令(argparse 应已拦截,但防御)
    p.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
