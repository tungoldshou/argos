from __future__ import annotations

import os
import socket as _stdlib_socket
from pathlib import Path

SOCKET_MODE = 0o600

_HEALTH_TIMEOUT = 0.5

_HEALTH_REQ = (
    b"GET /health HTTP/1.1\r\nHost: daemon\r\n"
    b"User-Agent: argos-daemon/socket-check\r\nConnection: close\r\n\r\n"
)


def default_socket_path() -> Path:
    from argos import config
    configured = config.get("ARGOS_DAEMON_SOCKET")
    if configured:
        return Path(configured).expanduser()
    return (
        Path(config.get("ARGOS_CONFIG_DIR") or (Path.home() / ".argos")).expanduser()
        / "daemon.sock"
    )


def ensure_socket_mode(path: Path) -> None:
    if path.exists():
        try:
            os.chmod(path, SOCKET_MODE)
        except OSError:
            pass


def _unlink_quiet(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        pass


def check_socket_available(path: Path) -> None:
    if not path.exists():
        return
    s = _stdlib_socket.socket(_stdlib_socket.AF_UNIX, _stdlib_socket.SOCK_STREAM)
    try:
        s.settimeout(_HEALTH_TIMEOUT)
        try:
            s.connect(str(path))
        except PermissionError as e:
            raise RuntimeError(f"socket {path} permission denied: {e}")
        except OSError:
            _unlink_quiet(path)
            return
        try:
            s.sendall(_HEALTH_REQ)
            resp = s.recv(64)
        except OSError:
            resp = b""
        if b"200" in resp:
            raise RuntimeError(f"daemon socket already in use: {path}")
        _unlink_quiet(path)
        return
    finally:
        try:
            s.close()
        except OSError:
            pass
