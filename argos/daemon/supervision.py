"""Internal documentation."""
from __future__ import annotations

import asyncio
import logging
import signal

log = logging.getLogger(__name__)


def install_signal_handlers(loop: asyncio.AbstractEventLoop, on_signal: callable) -> None:
    """Internal documentation."""
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, on_signal)
        except (NotImplementedError, RuntimeError):
            pass


async def graceful_shutdown(manager, server, socket_path) -> None:
    """Internal documentation."""
    log.info("daemon: graceful shutdown initiated")
    for rid, entry in list(manager.index.list()):
        if entry.state == "running":
            try:
                manager.mark_suspended(rid, last_step=0, msg_count=0,
                                       last_event_seq=entry.last_event_seq)
            except Exception as e:  # noqa: BLE001
                log.warning("graceful_shutdown: failed to suspend %s: %s", rid, e)
    try:
        await server.stop()
    except Exception as e:  # noqa: BLE001
        log.warning("graceful_shutdown: server.stop failed: %s", e)
    try:
        socket_path.unlink()
    except FileNotFoundError:
        pass
    log.info("daemon: graceful shutdown complete")
