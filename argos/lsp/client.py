"""pygls 薄 async 适配层(spec §2.1 / D1)。

pygls(BSD-3,~5k LOC)处理 JSON-RPC 帧 + handshake + 能力协商 + cancel + progress 等
LSP 规范边角;Argos 贡献此薄包装:
- `encode_frame(message)`:把 dict 编码为 Content-Length framed bytes
- `parse_frames(stream)`:从 async byte stream 切帧,返 async iterator of dict
- `LspClient`:桥 pygls 同步 stdin/stdout 与 asyncio(进程级 asyncio subprocess 包装)

不手写 JSON-RPC 协议细节(交给 pygls 的 framing);不引协议层 stdlib 替代品。
"""
from __future__ import annotations

import asyncio
import json
from typing import AsyncIterable, AsyncIterator, Any


class LspProtocolError(Exception):
    """LSP 帧 / JSON 解析失败 → manager 走 crash 路径(spec §3)。"""


class LspStreamClosed(Exception):
    """LSP server 流关闭(EOF)→ manager 走 crash 路径(spec §3)。"""


def encode_frame(message: dict) -> bytes:
    """dict → `Content-Length: N\\r\\n\\r\\n{json}` bytes(N 按 UTF-8 字节数)。"""
    body = json.dumps(message, ensure_ascii=False).encode("utf-8")
    header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
    return header + body


async def parse_frames(stream: AsyncIterable[bytes]) -> AsyncIterator[dict]:
    """async byte stream → async iterator of JSON-RPC messages。

    - 按 Content-Length 头切帧,bytes 累加
    - 半帧残留留在 buffer(下次继续)
    - 声称 length > EOF → 抛 LspProtocolError
    """
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
    # stream ended → buffer 残留半帧则视同协议错(manager 走 crash 路径)
    if buffer:
        raise LspProtocolError(
            f"stream ended with partial frame in buffer ({len(buffer)} bytes)"
        )


# ── LspClient:进程 stdio ↔ asyncio 桥 ─────────────────────────────

class _StreamLike:
    """Stream 适配层:接受 (StreamWriter, StreamReader) OR asyncio.Stream 对,统一
    暴露 `stdin.write` / `stdin.drain` / `stdout` 属性 —— 让 LspClient 不依赖
    asyncio.subprocess.Process 的具体形态(in-process fake 协程也能塞进来)。"""

    def __init__(self, stdin: Any, stdout: Any) -> None:
        self.stdin = stdin
        self.stdout = stdout


class LspClient:
    """单 server 进程 + 双向 stdio 桥。

    使用方式:
        proc = await asyncio.create_subprocess_exec(...)
        client = LspClient(proc)   # proc.stdin / proc.stdout 可用
        # 写请求:await client.send_request("initialize", {...})  → 响应 dict
        # 收通知:async for notif in client.notifications(): ...
    """

    def __init__(self, proc_or_streams: Any) -> None:
        # proc_or_streams 可为 asyncio.subprocess.Process 或任何有 .stdin / .stdout 的对象
        self._proc = proc_or_streams
        self._next_id = 1
        self._pending: dict[int, asyncio.Future[dict]] = {}
        self._notifications: asyncio.Queue[dict] = asyncio.Queue()
        self._reader_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """起后台 reader 协程。"""
        if self._reader_task is None:
            self._reader_task = asyncio.create_task(self._reader_loop())

    async def stop(self) -> None:
        """取消 reader 协程(进程由调用方 close / kill)。"""
        if self._reader_task is not None:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._reader_task = None

    async def _reader_loop(self) -> None:
        """持续从 proc.stdout 读帧;response 按 id 路由,notification 入队。

        异常处理:
        - LspProtocolError(帧格式坏字)→ 让所有 pending future 失败
        - 任何非 CancelledError 异常 → 同样让所有 pending future 失败
        - 正常 EOF(stream ended,buffer empty)→ 让所有 pending future 失败(manager 走 crash)
        """
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
        # 流结束(EOF 或协议错):让所有挂起 future 失败,manager 据此走 crash 路径
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
        """发 request → 等 response(5s 默认超时,spec §2.6)。"""
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
        """发 notification(无 id,不期待响应)。"""
        msg = {"jsonrpc": "2.0", "method": method, "params": params or {}}
        stdin = self._proc.stdin
        stdin.write(encode_frame(msg))
        await stdin.drain()

    async def notifications(self) -> AsyncIterator[dict]:
        """async iter 所有 server 主动发的消息(诊断/日志/进度等)。"""
        while True:
            msg = await self._notifications.get()
            yield msg
