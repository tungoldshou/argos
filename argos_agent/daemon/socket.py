"""Unix socket 路径 + 0600 权限检查。"""
from __future__ import annotations

import os
import socket as _stdlib_socket
from pathlib import Path

SOCKET_MODE = 0o600


def default_socket_path() -> Path:
    return Path.home() / ".argos" / "daemon.sock"


def ensure_socket_mode(path: Path) -> None:
    """socket 文件 mode 必须 0o600(防其他 user 访问;不在则 chmod)。"""
    if path.exists():
        try:
            os.chmod(path, SOCKET_MODE)
        except OSError:
            pass


def check_socket_available(path: Path) -> None:
    """检查 socket 是否可用(不存在 or 已死);raise RuntimeError 若仍活。"""
    if not path.exists():
        return
    # 试 connect:成功说明有 daemon 活
    s = _stdlib_socket.socket(_stdlib_socket.AF_UNIX, _stdlib_socket.SOCK_STREAM)
    try:
        s.settimeout(0.3)
        try:
            s.connect(str(path))
            s.close()
            raise RuntimeError(f"daemon socket already in use: {path}")
        except (ConnectionRefusedError, FileNotFoundError):
            # ECONNREFUSED → 死 daemon;清理
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            return
    except PermissionError as e:
        raise RuntimeError(f"socket {path} permission denied: {e}")
    finally:
        try:
            s.close()
        except OSError:
            pass
