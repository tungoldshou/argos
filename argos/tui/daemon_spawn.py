from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import time
from pathlib import Path

from argos import __version__ as _ARGOS_VERSION
from argos.protocol import PROTOCOL_VERSION

log = logging.getLogger(__name__)

_PROBE_TIMEOUT = 1.0
_SPAWN_TIMEOUT = 3.0
_WAIT_POLL    = 0.2
_KILL_GRACE_S = 0.6
_KILL_POLL_S  = 0.05


async def _probe(socket_path: Path) -> bool:
    req = b"GET /health HTTP/1.1\r\nHost: daemon\r\nUser-Agent: argos-tui/probe\r\nConnection: close\r\n\r\n"
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_unix_connection(str(socket_path)),
            timeout=_PROBE_TIMEOUT,
        )
        try:
            writer.write(req)
            await writer.drain()
            status_line = await asyncio.wait_for(reader.readline(), timeout=_PROBE_TIMEOUT)
            return b"200" in status_line
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:  # noqa: BLE001
                pass
    except Exception:  # noqa: BLE001
        return False


async def _daemon_version(socket_path: Path) -> dict | None:
    try:
        from argos.daemon.client import DaemonClient
        cli = DaemonClient(socket_path, timeout=_PROBE_TIMEOUT)
        status, _, raw = await cli._request("GET", "/version")
        if status != 200:
            return None
        return json.loads(raw.decode("utf-8"))
    except Exception:  # noqa: BLE001
        return None


_MTIME_GRACE_S = 2.0


def _argos_code_mtime() -> float:
    try:
        import argos
        root = os.path.dirname(os.path.abspath(argos.__file__))
        latest = 0.0
        for dirpath, _dirs, files in os.walk(root):
            for f in files:
                if f.endswith(".py"):
                    try:
                        m = os.path.getmtime(os.path.join(dirpath, f))
                        if m > latest:
                            latest = m
                    except OSError:
                        pass
        return latest
    except Exception:  # noqa: BLE001
        return 0.0


def _is_compatible(ver: dict) -> bool:
    if not (isinstance(ver, dict)
            and ver.get("daemon") == _ARGOS_VERSION
            and ver.get("protocol") == PROTOCOL_VERSION):
        return False
    started_at = ver.get("started_at")
    if isinstance(started_at, (int, float)) and started_at > 0:
        if _argos_code_mtime() > started_at + _MTIME_GRACE_S:
            return False
    return True


def _pid_alive(pid: int) -> bool:
    from argos.daemon.pidfile import is_alive
    return is_alive(pid)


def _daemon_pid_path(socket_path: Path) -> Path:
    return socket_path.parent / "daemon.pid"


def _kill_stale_daemon(socket_path: Path) -> None:
    from argos.daemon.pidfile import read_pid, remove
    pid_path = _daemon_pid_path(socket_path)
    pid = read_pid(pid_path)
    if pid is not None and _pid_alive(pid):
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
        else:
            waited = 0.0
            while waited < _KILL_GRACE_S and _pid_alive(pid):
                time.sleep(_KILL_POLL_S)
                waited += _KILL_POLL_S
            if _pid_alive(pid):
                try:
                    os.kill(pid, signal.SIGKILL)
                except OSError:
                    pass
    remove(pid_path)
    try:
        socket_path.unlink()
    except FileNotFoundError:
        pass


def _daemon_log_path(socket_path: Path) -> Path:
    return socket_path.parent / "daemon-boot.log"


def _tail(path: Path, n: int = 20) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        return "".join(lines[-n:]).rstrip()
    except OSError:
        return ""


async def probe_or_spawn(socket_path: Path) -> bool:
    if await _probe(socket_path):
        ver = await _daemon_version(socket_path)
        if _is_compatible(ver or {}):
            log.debug("daemon probe: compatible daemon alive at %s", socket_path)
            return True
        log.warning(
            "daemon probe: stale/incompatible daemon at %s (reported=%s, expected daemon=%s protocol=%s)"
            " — killing it and respawning a fresh daemon",
            socket_path, ver, _ARGOS_VERSION, PROTOCOL_VERSION,
        )
        _kill_stale_daemon(socket_path)
    elif socket_path.exists():
        log.warning(
            "daemon probe: socket %s exists but unresponsive (hung daemon?)"
            " — killing it before respawn",
            socket_path,
        )
        _kill_stale_daemon(socket_path)

    log.info("daemon probe: socket not ready, attempting to spawn argosd")
    log_path = _daemon_log_path(socket_path)
    try:
        log_fh = open(log_path, "wb")
    except OSError:
        log_fh = None
    out = log_fh if log_fh is not None else asyncio.subprocess.DEVNULL
    try:
        proc = await asyncio.create_subprocess_exec(
            "argosd",
            "--socket-path", str(socket_path),
            "--pid-path", str(_daemon_pid_path(socket_path)),
            stdout=out,
            stderr=out,
        )
    except FileNotFoundError:
        log.debug("daemon spawn: argosd not found in PATH, using inline mode")
        return False
    except Exception as e:  # noqa: BLE001
        log.warning("daemon spawn: failed to start argosd: %s", e)
        return False
    finally:
        if log_fh is not None:
            try:
                log_fh.close()
            except OSError:
                pass

    elapsed = 0.0
    while elapsed < _SPAWN_TIMEOUT:
        await asyncio.sleep(_WAIT_POLL)
        elapsed += _WAIT_POLL
        if await _probe(socket_path):
            log.info("daemon spawn: argosd ready after %.1fs", elapsed)
            return True
        if proc.returncode is not None:
            tail = _tail(log_path)
            log.warning(
                "daemon spawn: argosd exited early (rc=%s)%s",
                proc.returncode,
                f"; daemon.log tail:\n{tail}" if tail else "",
            )
            return False

    try:
        proc.kill()
    except Exception:  # noqa: BLE001
        pass
    tail = _tail(log_path)
    log.warning(
        "daemon spawn: argosd did not become ready within %.1fs%s",
        _SPAWN_TIMEOUT,
        f"; daemon.log tail:\n{tail}" if tail else "",
    )
    return False
