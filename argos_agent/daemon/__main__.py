"""`python -m argos_agent.daemon` 入口(spec §2.10 + D13)。

`argos daemon` 子命令也走这个入口。
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import sys
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
    from argos_agent.daemon.manager import RunManager
    from argos_agent.daemon.pidfile import write_pid, remove as remove_pid
    from argos_agent.daemon.server import DaemonHTTPServer
    from argos_agent.daemon.socket import check_socket_available, ensure_socket_mode
    from argos_agent.daemon.supervision import graceful_shutdown, install_signal_handlers

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

    manager = RunManager(runs_dir=runs_dir, index_path=index_path)
    # 启动恢复
    recovered = manager.recover()
    if recovered:
        log.info("daemon: recovered %d runs: %s", len(recovered), recovered)

    server = DaemonHTTPServer(manager=manager, socket_path=socket_path)
    await server.start()

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
        await graceful_shutdown(manager, server, socket_path)
        remove_pid(pid_path)
    return 0


def main() -> int:
    p = argparse.ArgumentParser(
        prog="python -m argos_agent.daemon",
        description="Argos background daemon (long-running tasks)",
    )
    p.add_argument("--detach", action="store_true", help="detach from controlling tty")
    p.add_argument("--runs-dir", default=str(_default_runs_dir()))
    p.add_argument("--index-path", default=str(_default_index_path()))
    p.add_argument("--socket-path", default=str(_default_socket_path()))
    p.add_argument("--pid-path", default=str(_default_pid_path()))
    p.add_argument("--log-level", default="info",
                   choices=["debug", "info", "warning", "error"])
    args = p.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    return asyncio.run(_serve(args))


if __name__ == "__main__":
    sys.exit(main())
