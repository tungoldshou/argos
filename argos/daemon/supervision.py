"""SIGTERM / SIGINT 优雅退出 handler(spec §2.3 + §3)。

daemon 收 SIGTERM(谁发的?TUI 退时显式 `kill -TERM $(cat ~/.argos/daemon.pid)`?或
daemon 自监听 TUI 的 SSE 断开?)→ 优雅路径:把所有 `running` 标 `suspended` +
写 checkpoint + 落 index.json + exit。

#5a 简化:handler 接受一个 `RunManager` + 退出事件,daemon 进程入口装上。
"""
from __future__ import annotations

import asyncio
import logging
import signal

log = logging.getLogger(__name__)


def install_signal_handlers(loop: asyncio.AbstractEventLoop, on_signal: callable) -> None:
    """装 SIGTERM / SIGINT handler → on_signal()。

    入口:daemon 进程 startup 时调一次。Windows 退路:仅 SIGINT。
    """
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, on_signal)
        except (NotImplementedError, RuntimeError):
            # Windows / 不支持 → 退路:不装,daemon 用其他方式优雅
            pass


async def graceful_shutdown(manager, server, socket_path) -> None:
    """优雅退出:
      1. 把所有 running 改 suspended(写 checkpoint)
      2. 关 server(断所有 SSE 连接)
      3. 关 socket 文件
      4. 退出

    注:manager / server 由调用方注入,避免 import cycle。
    """
    log.info("daemon: graceful shutdown initiated")
    for rid, entry in list(manager.index.list()):
        if entry.state == "running":
            try:
                manager.mark_suspended(rid, last_step=0, msg_count=0,
                                       last_event_seq=entry.last_event_seq)
            except Exception as e:  # noqa: BLE001
                log.warning("graceful_shutdown: failed to suspend %s: %s", rid, e)
    # 关 server
    try:
        await server.stop()
    except Exception as e:  # noqa: BLE001
        log.warning("graceful_shutdown: server.stop failed: %s", e)
    # 清 socket
    try:
        socket_path.unlink()
    except FileNotFoundError:
        pass
    log.info("daemon: graceful shutdown complete")
