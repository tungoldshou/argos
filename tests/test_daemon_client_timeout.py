"""#1 排查修复:DaemonClient._request 必须真用 self._timeout 兜底。

daemon 是默认运行路径(always-on)。它接了 socket 却卡死/半写时,无界 readline/readexactly
会让 TUI 永远停在"思考中…"——app 层 try/except 抓异常,抓不住挂起。本测试证:往返受
self._timeout 硬约束,超时抛 DaemonError(让上层接住并诚实降级)。"""
from __future__ import annotations

import asyncio

import pytest

from argos.daemon.client import DaemonClient, DaemonError


@pytest.mark.asyncio
async def test_request_times_out_on_stalled_daemon(tmp_path):
    sock = tmp_path / "d.sock"
    accepted = asyncio.Event()

    async def _handler(reader, writer):
        accepted.set()
        try:
            await asyncio.sleep(1.5)   # 接了连接却(在 client 0.3s 超时窗内)不回应,模拟卡死
        except asyncio.CancelledError:
            pass
        finally:
            try:
                writer.close()
            except Exception:  # noqa: BLE001
                pass

    server = await asyncio.start_unix_server(_handler, path=str(sock))
    try:
        client = DaemonClient(sock, timeout=0.3)
        with pytest.raises(DaemonError) as ei:
            # 外层 wait_for 只是防测试本身挂死;真正该兜底的是 client 自己的 0.3s
            await asyncio.wait_for(client.health(), timeout=3.0)
        assert "无响应" in str(ei.value) or "超过" in str(ei.value), str(ei.value)
        assert accepted.is_set(), "server 应已接到连接(确实进了读阶段才超时)"
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_request_succeeds_within_timeout(tmp_path):
    """正常快速响应不被超时误伤。"""
    sock = tmp_path / "d.sock"

    async def _handler(reader, writer):
        await reader.readline()           # 吃掉请求行(够触发往返)
        body = b'{"ok": true}'
        resp = (
            b"HTTP/1.1 200 OK\r\n"
            b"Content-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body
        )
        writer.write(resp)
        await writer.drain()
        writer.close()

    server = await asyncio.start_unix_server(_handler, path=str(sock))
    try:
        client = DaemonClient(sock, timeout=5.0)
        out = await asyncio.wait_for(client.health(), timeout=3.0)
        assert out == {"ok": True}
    finally:
        server.close()
        await server.wait_closed()
