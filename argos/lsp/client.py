from __future__ import annotations

import asyncio
import json
from typing import AsyncIterable, AsyncIterator, Any


class LspProtocolError(Exception):
    pass


class LspStreamClosed(Exception):
    pass


def encode_frame(message: dict) -> bytes:
    body = json.dumps(message, ensure_ascii=False).encode("utf-8")
    header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
    return header + body


async def parse_frames(stream: AsyncIterable[bytes]) -> AsyncIterator[dict]:
    buffer = bytearray()
    async for chunk in stream:
        if not chunk:
            continue
        buffer.extend(chunk)
        while True:
            sep = buffer.find(b"\r\n\r\n")
            if sep == -1:
                break
            header = bytes(buffer[:sep])
            body_start = sep + 4
            content_length: int | None = None
            for line in header.split(b"\r\n"):
                if line.lower().startswith(b"content-length:"):
                    try:
                        content_length = int(line.split(b":", 1)[1].strip())
                    except ValueError as e:
                        raise LspProtocolError(f"bad Content-Length: {line!r}") from e
                    break
            if content_length is None:
                raise LspProtocolError(f"missing Content-Length header: {header!r}")
            if len(buffer) < body_start + content_length:
                break
            body = bytes(buffer[body_start:body_start + content_length])
            del buffer[:body_start + content_length]
            try:
                yield json.loads(body.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                raise LspProtocolError(f"malformed JSON-RPC body: {e}") from e
    if buffer:
        raise LspProtocolError(
            f"stream ended with partial frame in buffer ({len(buffer)} bytes)"
        )



class _StreamLike:

    def __init__(self, stdin: Any, stdout: Any) -> None:
        self.stdin = stdin
        self.stdout = stdout


class LspClient:

    def __init__(self, proc_or_streams: Any) -> None:
        self._proc = proc_or_streams
        self._next_id = 1
        self._pending: dict[int, asyncio.Future[dict]] = {}
        self._notifications: asyncio.Queue[dict] = asyncio.Queue()
        self._reader_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._reader_task is None:
            self._reader_task = asyncio.create_task(self._reader_loop())

    async def stop(self) -> None:
        if self._reader_task is not None:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._reader_task = None

    async def _reader_loop(self) -> None:
        stream = self._proc.stdout
        protocol_error: Exception | None = None
        try:
            async for msg in parse_frames(stream):
                msg_id = msg.get("id")
                if msg_id is not None and msg_id in self._pending:
                    fut = self._pending.pop(msg_id)
                    if "error" in msg:
                        fut.set_exception(
                            RuntimeError(f"LSP error: {msg['error']}")
                        )
                    else:
                        fut.set_result(msg.get("result"))
                else:
                    await self._notifications.put(msg)
        except asyncio.CancelledError:
            raise
        except LspProtocolError as e:
            protocol_error = e
        except Exception as e:  # noqa: BLE001
            protocol_error = e
        msg = "LSP stream closed" if protocol_error is None else f"LSP protocol error: {protocol_error}"
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(LspStreamClosed(msg))
        self._pending.clear()
        if protocol_error is not None:
            raise LspProtocolError(str(protocol_error))

    async def send_request(
        self, method: str, params: dict | None = None, *, timeout: float = 5.0,
    ) -> Any:
        msg_id = self._next_id
        self._next_id += 1
        loop = asyncio.get_event_loop()
        fut: asyncio.Future[dict] = loop.create_future()
        self._pending[msg_id] = fut
        msg = {"jsonrpc": "2.0", "id": msg_id, "method": method, "params": params or {}}
        stdin = self._proc.stdin
        stdin.write(encode_frame(msg))
        await stdin.drain()
        return await asyncio.wait_for(fut, timeout=timeout)

    async def send_notification(self, method: str, params: dict | None = None) -> None:
        msg = {"jsonrpc": "2.0", "method": method, "params": params or {}}
        stdin = self._proc.stdin
        stdin.write(encode_frame(msg))
        await stdin.drain()

    async def notifications(self) -> AsyncIterator[dict]:
        while True:
            msg = await self._notifications.get()
            yield msg
