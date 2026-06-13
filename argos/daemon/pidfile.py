"""~/.argos/daemon.pid 锁(简单持有,启动时若已存在则检测 alive / 接管)。"""
from __future__ import annotations

import os
from pathlib import Path

PID_FILE_MODE = 0o600


def write_pid(path: Path, pid: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{pid}\n", encoding="utf-8")
    os.chmod(path, PID_FILE_MODE)


def read_pid(path: Path) -> int | None:
    if not path.exists():
        return None
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def is_alive(pid: int) -> bool:
    """检测 pid 是否在跑(支持 Unix;Windows 退路用 os.path.exists 不可靠,本期不支持)。"""
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def remove(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass
