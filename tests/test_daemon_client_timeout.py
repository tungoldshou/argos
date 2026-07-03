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
            await asyncio.sleep(1.5)
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
            await asyncio.wait_for(client.health(), timeout=3.0)
        assert "无响应" in str(ei.value) or "超过" in str(ei.value), str(ei.value)
        assert accepted.is_set(), "server 应已接到连接(确实进了读阶段才超时)"
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_request_succeeds_within_timeout(tmp_path):
    sock = tmp_path / "d.sock"

    async def _handler(reader, writer):
        await reader.readline()
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
