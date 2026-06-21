"""Unix socket 路径 + 0600 权限检查。"""
from __future__ import annotations

import os
import socket as _stdlib_socket
from pathlib import Path

SOCKET_MODE = 0o600

# connect 成功后,等待 /health 响应的超时(秒)。连得上但此时间内不响应 = 假死 daemon。
_HEALTH_TIMEOUT = 0.5

_HEALTH_REQ = (
    b"GET /health HTTP/1.1\r\nHost: daemon\r\n"
    b"User-Agent: argos-daemon/socket-check\r\nConnection: close\r\n\r\n"
)


def default_socket_path() -> Path:
    return Path.home() / ".argos" / "daemon.sock"


def ensure_socket_mode(path: Path) -> None:
    """socket 文件 mode 必须 0o600(防其他 user 访问;不在则 chmod)。"""
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
    """检查 socket 是否被**活跃服务中**的 daemon 占用;占用则 raise RuntimeError,否则清理残留并返回。

    判活铁律:connect() 成功 ≠ daemon 活着。假死 daemon(事件循环 wedged)的内核 listen
    backlog 仍接受 connect(),但永不响应——若只看 connect 成功就判"占用",新 daemon 永远
    起不来,TUI 永久回退 inline(2026-06-22 真机死锁)。因此必须 connect 后真发 /health
    并要求在 _HEALTH_TIMEOUT 内拿到响应;无响应 = 假死 → 清掉 socket 让新 daemon 接管。
    """
    if not path.exists():
        return
    s = _stdlib_socket.socket(_stdlib_socket.AF_UNIX, _stdlib_socket.SOCK_STREAM)
    try:
        s.settimeout(_HEALTH_TIMEOUT)
        # 1) 连不上(ECONNREFUSED / 非 socket 残留文件 / 路径异常)→ 死 daemon → 清理
        try:
            s.connect(str(path))
        except PermissionError as e:
            raise RuntimeError(f"socket {path} permission denied: {e}")
        except OSError:
            _unlink_quiet(path)
            return
        # 2) 连得上 → 真发 /health,要求响应。无响应(假死)/非 200 → 清理接管。
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
