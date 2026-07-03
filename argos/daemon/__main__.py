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

from argos.i18n import t

log = logging.getLogger(__name__)

_LOG_FORMAT = "%(asctime)s %(name)s %(levelname)s %(message)s"
_RUN_LOG_MAX_BYTES = 2_000_000
_RUN_LOG_BACKUPS = 3


def _build_log_handlers(socket_path) -> list[logging.Handler]:
    run_log = Path(socket_path).expanduser().parent / "daemon.log"
    try:
        from logging.handlers import RotatingFileHandler
        run_log.parent.mkdir(parents=True, exist_ok=True)
        fh = RotatingFileHandler(
            run_log,
            maxBytes=_RUN_LOG_MAX_BYTES,
            backupCount=_RUN_LOG_BACKUPS,
            encoding="utf-8",
        )
        fh.setFormatter(logging.Formatter(_LOG_FORMAT))
        return [fh]
    except Exception:  # noqa: BLE001
        return [logging.StreamHandler()]


def _default_argos_dir() -> Path:
    from argos import config
    return Path(config.get("ARGOS_CONFIG_DIR") or (Path.home() / ".argos")).expanduser()


def _default_runs_dir() -> Path:
    return _default_argos_dir() / "runs"


def _default_index_path() -> Path:
    return _default_runs_dir() / "index.json"


def _default_socket_path() -> Path:
    from argos.daemon.socket import default_socket_path
    return default_socket_path()


def _default_pid_path() -> Path:
    return _default_argos_dir() / "daemon.pid"


def _default_conductor_dir() -> Path:
    return _default_argos_dir() / "conductor"


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

    try:
        check_socket_available(socket_path)
    except RuntimeError as e:
        print(f"[daemon] {e}", file=sys.stderr)
        return 1

    from argos.daemon.server import _NO_KEY
    loop_factory = _NO_KEY
    components = None
    try:
        from argos.app_factory import build_components, build_loop_factory
        components = build_components()
        loop_factory = build_loop_factory(components)
        log.info("daemon: AgentLoop factory 装配完成(model=%s)", components.config.model_tier)
    except RuntimeError as e:
        print(t("daemon.serve.warn_no_key", e=e), file=sys.stderr)
        log.warning("daemon: loop_factory 装配失败: %s", e)
    except Exception as e:  # noqa: BLE001
        print(t("daemon.serve.warn_assembly_error", e=e), file=sys.stderr)
        log.warning("daemon: loop_factory 装配异常: %s", e)

    manager = RunManager(runs_dir=runs_dir, index_path=index_path)
    recovered = manager.recover()
    if recovered:
        log.info("daemon: recovered %d runs: %s", len(recovered), recovered)

    from argos.daemon.conductor_supervisor import ConductorSupervisor, CONDUCTOR_RUN_ID
    conductor_orders_dir = _default_conductor_dir()

    async def _conductor_broadcast(ev_dict: dict) -> None:
        await manager.fanout(CONDUCTOR_RUN_ID, ev_dict)

    conductor_supervisor = ConductorSupervisor(
        orders_dir=conductor_orders_dir,
        tick_interval=float(os.environ.get("ARGOS_CONDUCTOR_TICK_INTERVAL", "30")),
        broadcast_fn=_conductor_broadcast,
    )

    from argos.ledger.store import LedgerStore
    ledger_store = LedgerStore()

    server = DaemonHTTPServer(
        manager=manager,
        socket_path=socket_path,
        components=components,
        loop_factory=loop_factory,
        gate=components.gate if components is not None else None,
        ledger_store=ledger_store,
        conductor_supervisor=conductor_supervisor,
    )
    await server.start()
    conductor_supervisor.start()

    write_pid(pid_path, os.getpid())
    ensure_socket_mode(socket_path)

    print(f"[daemon] started, socket={socket_path}, pid={os.getpid()}")

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
        try:
            await conductor_supervisor.stop()
        except Exception as e:  # noqa: BLE001
            log.warning("daemon: conductor_supervisor.stop() failed: %s", e)
        await graceful_shutdown(manager, server, socket_path)
        remove_pid(pid_path)
        if components is not None:
            try:
                components.close()
            except Exception as e:  # noqa: BLE001
                log.warning("daemon: components.close() failed: %s", e)
    return 0



def _socket_alive(socket_path: Path) -> bool:
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
    from argos.daemon.pidfile import read_pid, is_alive

    pid = read_pid(pid_path)

    if pid is None and not socket_path.exists():
        print(t("daemon.stop.not_running"))
        return 0

    if pid is not None and not is_alive(pid):
        try:
            pid_path.unlink(missing_ok=True)
        except OSError:
            pass
        if not socket_path.exists():
            print(t("daemon.stop.stale_pid_cleaned"))
            return 0

    if pid is None:
        print(t("daemon.stop.socket_no_pid", socket_path=socket_path), file=sys.stderr)
        return 1

    try:
        os.kill(pid, signal.SIGTERM)
        print(t("daemon.stop.sigterm_sent", pid=pid))
    except ProcessLookupError:
        print(t("daemon.stop.process_gone"))
        pid_path.unlink(missing_ok=True)
        return 0
    except PermissionError as e:
        print(t("daemon.stop.no_permission", e=e), file=sys.stderr)
        return 1

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _socket_alive(socket_path):
            print(t("daemon.stop.stopped"))
            return 0
        time.sleep(0.2)

    print(t("daemon.stop.timeout_warning", timeout=f"{timeout:.0f}", socket_path=socket_path),
          file=sys.stderr)
    return 1


def _cmd_status(
    pid_path: Path,
    socket_path: Path,
) -> int:
    from argos.daemon.pidfile import read_pid, is_alive

    pid = read_pid(pid_path)
    alive = pid is not None and is_alive(pid)
    socket_ok = _socket_alive(socket_path)

    if not alive and not socket_ok:
        print(t("daemon.status.not_running"))
        if pid is not None:
            print(t("daemon.status.stale_pid_note", pid_path=pid_path, pid=pid))
        return 1

    status_lines: list[str] = []
    status_lines.append(t("daemon.status.running"))
    if pid is not None:
        status_lines.append(t("daemon.status.pid_line", pid=pid))
    status_lines.append(t("daemon.status.pid_file_line", pid_path=pid_path))
    connectivity = t("daemon.status.socket_connectable") if socket_ok else t("daemon.status.socket_not_connectable")
    status_lines.append(t("daemon.status.socket_line", socket_path=socket_path, connectivity=connectivity))

    if pid_path.exists():
        try:
            start_ts = pid_path.stat().st_mtime
            uptime_s = time.time() - start_ts
            h, rem = divmod(int(uptime_s), 3600)
            m, s = divmod(rem, 60)
            status_lines.append(t("daemon.status.uptime_line", uptime=f"{h:02d}:{m:02d}:{s:02d}"))
        except OSError:
            pass

    if socket_ok:
        try:
            version_info = _query_version_sync(socket_path)
            if version_info:
                status_lines.append(t("daemon.status.version_line", version_info=version_info))
        except Exception:  # noqa: BLE001
            pass

    print("\n".join(status_lines))
    return 0


def _query_version_sync(socket_path: Path) -> str | None:
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
        if b"\r\n\r\n" in raw:
            body_bytes = raw.split(b"\r\n\r\n", 1)[1]
            import json as _json
            data = _json.loads(body_bytes.decode("utf-8", errors="replace"))
            return data.get("version") or str(data)
        return None
    except Exception:  # noqa: BLE001
        return None


def _cmd_restart(args: argparse.Namespace) -> int:
    pid_path = Path(args.pid_path).expanduser()
    socket_path = Path(args.socket_path).expanduser()

    # stop
    rc = _cmd_stop(pid_path, socket_path)
    if rc != 0:
        return rc

    # start (detached subprocess)
    print(t("daemon.restart.restarting"))
    _spawn_detached(args)
    print(t("daemon.restart.restarted"))
    return 0


def _spawn_detached(args: argparse.Namespace) -> None:
    cmd = [
        sys.executable, "-m", "argos.daemon",
        "--runs-dir", args.runs_dir,
        "--index-path", args.index_path,
        "--socket-path", args.socket_path,
        "--pid-path", args.pid_path,
        "--log-level", args.log_level,
    ]
    subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )



def main() -> int:
    p = argparse.ArgumentParser(
        prog="argosd",
        description="Argos background daemon — start / stop / status / restart",
    )
    p.add_argument("--runs-dir", default=str(_default_runs_dir()))
    p.add_argument("--index-path", default=str(_default_index_path()))
    p.add_argument("--socket-path", default=str(_default_socket_path()))
    p.add_argument("--pid-path", default=str(_default_pid_path()))
    p.add_argument("--log-level", default="info",
                   choices=["debug", "info", "warning", "error"])
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
        format=_LOG_FORMAT,
        handlers=_build_log_handlers(args.socket_path),
    )

    pid_path = Path(args.pid_path).expanduser()
    socket_path = Path(args.socket_path).expanduser()

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

    p.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
