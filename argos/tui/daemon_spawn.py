"""daemon 探测 + 自动拉起辅助(v6 P3b)。

probe_or_spawn():
  1. socket 存在且 /health 200 → 直接复用（"argosd" 模式）
  2. socket 不存在 / 不可达 → 尝试拉起 argosd 子进程，等待最多 3s
  3. 拉起失败/超时 → 返回 None（调用方切 inline fallback，诚实显示）

诚实铁律：绝不假装 daemon 已就绪；失败时返 None，调用方显 "inline(单进程)"。
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

log = logging.getLogger(__name__)

_PROBE_TIMEOUT = 1.0    # 单次 health 探测超时（秒）
_SPAWN_TIMEOUT = 3.0    # 拉起后等待就绪的最大等待（秒）
_WAIT_POLL    = 0.2     # 等待就绪的轮询间隔（秒）


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


async def probe_or_spawn(socket_path: Path) -> bool:
    """探测 daemon socket；不可达时尝试拉起 argosd 子进程。

    返回 True  = daemon 已就绪（argosd 模式）。
    返回 False = daemon 不可用（inline fallback 模式）。
    """
    # 1. 先探一次
    if await _probe(socket_path):
        log.debug("daemon probe: socket alive at %s", socket_path)
        return True

    # 2. 尝试拉起 argosd
    log.info("daemon probe: socket not ready, attempting to spawn argosd")
    try:
        proc = await asyncio.create_subprocess_exec(
            "argosd",
            # daemon argparse 只认 --socket-path(__main__.py);过去传 --socket → argosd rc=2
            # 退出 → 永远落 inline。修正 flag 名,让 argosd 在 PATH 时能真正拉起。
            "--socket-path", str(socket_path),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except FileNotFoundError:
        # argosd 不在 PATH（纯内嵌 / 测试环境）—— silent fallback
        log.debug("daemon spawn: argosd not found in PATH, using inline mode")
        return False
    except Exception as e:  # noqa: BLE001
        log.warning("daemon spawn: failed to start argosd: %s", e)
        return False

    # 3. 轮询等待就绪（最多 SPAWN_TIMEOUT 秒）
    elapsed = 0.0
    while elapsed < _SPAWN_TIMEOUT:
        await asyncio.sleep(_WAIT_POLL)
        elapsed += _WAIT_POLL
        if await _probe(socket_path):
            log.info("daemon spawn: argosd ready after %.1fs", elapsed)
            return True
        # 子进程已提前退出（失败）
        if proc.returncode is not None:
            log.warning("daemon spawn: argosd exited early (rc=%s)", proc.returncode)
            return False

    # 超时：杀掉子进程，诚实 fallback
    try:
        proc.kill()
    except Exception:  # noqa: BLE001
        pass
    log.warning("daemon spawn: argosd did not become ready within %.1fs", _SPAWN_TIMEOUT)
    return False
