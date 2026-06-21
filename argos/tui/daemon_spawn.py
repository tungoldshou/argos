"""daemon 探测 + 自动拉起辅助(v6 P3b)。

probe_or_spawn():
  1. socket 存在且 /health 200 → 直接复用（"argosd" 模式）
  2. socket 不存在 / 不可达 → 尝试拉起 argosd 子进程，等待最多 3s
  3. 拉起失败/超时 → 返回 None（调用方切 inline fallback，诚实显示）

诚实铁律：绝不假装 daemon 已就绪；失败时返 None，调用方显 "inline(单进程)"。
"""
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

_PROBE_TIMEOUT = 1.0    # 单次 health 探测超时（秒）
_SPAWN_TIMEOUT = 3.0    # 拉起后等待就绪的最大等待（秒）
_WAIT_POLL    = 0.2     # 等待就绪的轮询间隔（秒）
_KILL_GRACE_S = 0.6     # SIGTERM 后等优雅退出的宽限（秒）；超时仍活则升级 SIGKILL
_KILL_POLL_S  = 0.05    # 等待退出的轮询间隔（秒）


async def _probe(socket_path: Path) -> bool:
    """尝试连接 socket + GET /health；成功返 True，失败返 False。"""
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
    """GET /version,返回解析后的 dict;不可达 / 非 200 / 解析失败 → None。"""
    try:
        from argos.daemon.client import DaemonClient
        cli = DaemonClient(socket_path, timeout=_PROBE_TIMEOUT)
        status, _, raw = await cli._request("GET", "/version")
        if status != 200:
            return None
        return json.loads(raw.decode("utf-8"))
    except Exception:  # noqa: BLE001 — 任何失败都视为"拿不到版本"(降级为陈旧)
        return None


# dev 改码检测的小宽限(秒):防文件系统 mtime 与 time.time() 边界抖动误判。
_MTIME_GRACE_S = 2.0


def _argos_code_mtime() -> float:
    """argos 包内所有 .py 的最大 mtime。dev 改码检测用:daemon 启动后任一 .py 更新过
    → daemon 跑的是旧码 → 陈旧。异常(如打包环境路径异常)→ 返 0.0(降级为只按版本号判)。"""
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
    except Exception:  # noqa: BLE001 — 任何异常降级:不靠 mtime,只按版本号
        return 0.0


def _is_compatible(ver: dict) -> bool:
    """daemon 上报的版本 + 协议号是否与本 TUI 一致,且 daemon 启动后代码未改过。缺字段 = 不兼容。

    版本号相同但 dev 改了码(版本不 bump)时,靠 started_at vs 本地代码 mtime 抓陈旧 daemon:
    daemon 启动早于最新 .py → 它跑的是旧码 → 不兼容(杀重启)。started_at 缺失(更老的 daemon)
    → 保守只按版本号判(本次已手动杀,后续 daemon 都会上报 started_at)。
    """
    if not (isinstance(ver, dict)
            and ver.get("daemon") == _ARGOS_VERSION
            and ver.get("protocol") == PROTOCOL_VERSION):
        return False
    started_at = ver.get("started_at")
    if isinstance(started_at, (int, float)) and started_at > 0:
        if _argos_code_mtime() > started_at + _MTIME_GRACE_S:
            return False   # daemon 启动后代码改过 → 陈旧
    return True


def _pid_alive(pid: int) -> bool:
    """薄包装(便于测试 monkeypatch);委托 pidfile.is_alive。"""
    from argos.daemon.pidfile import is_alive
    return is_alive(pid)


def _kill_stale_daemon(socket_path: Path) -> None:
    """杀掉 daemon.pid 记录的陈旧/假死 daemon + 清 pid/sock,为 spawn 新的让路。

    安全:仅当 PID 仍存活才发信号(防 PID 复用误杀)。先 SIGTERM 给优雅退出机会;假死 daemon
    (事件循环 wedged)会忽略 SIGTERM —— 在 _KILL_GRACE_S 内仍未退出则升级 SIGKILL,杜绝孤儿
    泄漏(否则旧进程继续占着旧 socket inode,lsof 会见两个 daemon 绑同一路径)。无论杀否都清
    pid/sock 文件。
    """
    from argos.daemon.pidfile import read_pid, remove
    pid_path = socket_path.parent / "daemon.pid"
    pid = read_pid(pid_path)
    if pid is not None and _pid_alive(pid):
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:  # 已退 / 无权限——忽略,继续清文件
            pass
        else:
            # 等待优雅退出;超时仍活(假死忽略 SIGTERM)→ 升级 SIGKILL
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
    """TUI 截获 argosd 启动期 stdout/stderr(print + 未捕获 traceback)的日志;每次 spawn 截断。

    与 daemon 自身的运行日志(daemon.log,daemon 进程内 RotatingFileHandler 有界轮转)分离:
    两者若同名,fd 重定向会与轮转 rename 相互冲突,且运行日志会把 boot 日志灌满。
    """
    return socket_path.parent / "daemon-boot.log"


def _tail(path: Path, n: int = 20) -> str:
    """读日志文件最后 n 行(best-effort);读不到返空串。"""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        return "".join(lines[-n:]).rstrip()
    except OSError:
        return ""


async def probe_or_spawn(socket_path: Path) -> bool:
    """探测 daemon socket；不可达 / 陈旧时尝试拉起新 argosd 子进程。

    返回 True  = daemon 已就绪（argosd 模式）。
    返回 False = daemon 不可用（inline fallback 模式）。
    """
    # 1. 先探 health
    if await _probe(socket_path):
        # 1b. 握手 /version:陈旧 / 不兼容 daemon 绝不静默复用——否则它跑过期代码,
        #     run 会一启动就失败(如跨包改名后 sandbox child 模块找不到),TUI 却无限"思考中"。
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
        # socket 文件在但 /health 不响应 = 假死 daemon 占着 socket(事件循环 wedged,
        # 内核 backlog 仍接受 connect 但永不回应)。不清理的话,新 argosd 的
        # check_socket_available 会因 connect 成功误判"已占用" → rc=1 退出 → 永久 inline
        # 死锁(2026-06-22 真机)。spawn 前先杀掉它 + 清 pid/sock,为新 daemon 让路。
        log.warning(
            "daemon probe: socket %s exists but unresponsive (hung daemon?)"
            " — killing it before respawn",
            socket_path,
        )
        _kill_stale_daemon(socket_path)

    # 2. 尝试拉起 argosd。子进程输出重定向到 daemon.log(每次截断):spawn 失败时能回显原因,
    #    不再用 DEVNULL 静默吞掉致命启动错误(如 'daemon socket already in use')。
    log.info("daemon probe: socket not ready, attempting to spawn argosd")
    log_path = _daemon_log_path(socket_path)
    try:
        log_fh = open(log_path, "wb")
    except OSError:
        log_fh = None  # 打不开日志就退化 DEVNULL,绝不挡启动
    out = log_fh if log_fh is not None else asyncio.subprocess.DEVNULL
    try:
        proc = await asyncio.create_subprocess_exec(
            "argosd",
            # daemon argparse 只认 --socket-path(__main__.py);过去传 --socket → argosd rc=2
            # 退出 → 永远落 inline。修正 flag 名,让 argosd 在 PATH 时能真正拉起。
            "--socket-path", str(socket_path),
            stdout=out,
            stderr=out,
        )
    except FileNotFoundError:
        # argosd 不在 PATH（纯内嵌 / 测试环境）—— silent fallback
        log.debug("daemon spawn: argosd not found in PATH, using inline mode")
        return False
    except Exception as e:  # noqa: BLE001
        log.warning("daemon spawn: failed to start argosd: %s", e)
        return False
    finally:
        # 子进程已 dup 了 fd,父进程关掉自己的副本(防句柄泄漏)
        if log_fh is not None:
            try:
                log_fh.close()
            except OSError:
                pass

    # 3. 轮询等待就绪（最多 SPAWN_TIMEOUT 秒）
    elapsed = 0.0
    while elapsed < _SPAWN_TIMEOUT:
        await asyncio.sleep(_WAIT_POLL)
        elapsed += _WAIT_POLL
        if await _probe(socket_path):
            log.info("daemon spawn: argosd ready after %.1fs", elapsed)
            return True
        # 子进程已提前退出（失败）—— 回显 daemon.log 尾部,暴露根因
        if proc.returncode is not None:
            tail = _tail(log_path)
            log.warning(
                "daemon spawn: argosd exited early (rc=%s)%s",
                proc.returncode,
                f"; daemon.log tail:\n{tail}" if tail else "",
            )
            return False

    # 超时：杀掉子进程，诚实 fallback（同样回显日志尾部）
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
