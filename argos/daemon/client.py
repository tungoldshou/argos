"""DaemonClient:TUI 侧 HTTP/SSE 客户端(spec §2.5)。

自写 stdlib HTTP client + SSE 解析(~100 LOC),0 新依赖。
Unix socket 走 `socket` 模块直接接 httpx 不可用,这里用 asyncio.open_unix_connection。
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, AsyncIterator

from argos.i18n import t

log = logging.getLogger(__name__)


class DaemonError(Exception):
    """daemon 端返非 2xx / 5xx 错误(含 code / message)。"""


class DaemonClient:
    """Unix socket HTTP client + SSE 订阅。

    用法:
        client = DaemonClient(socket_path)
        sid = await client.create_session()
        rid = await client.create_run(goal="x", session_id=sid)
        async for ev in client.subscribe_events(rid, sid):
            ...
    """

    def __init__(self, socket_path: Path, *, timeout: float = 30.0):
        self._socket_path = Path(socket_path)
        self._timeout = timeout

    @property
    def socket_path(self) -> Path:
        return self._socket_path

    # ── low-level HTTP ──────────────────────────────────────────────

    async def _request(
        self,
        method: str,
        path: str,
        *,
        session_id: str | None = None,
        body: dict | None = None,
    ) -> tuple[int, dict[str, str], bytes]:
        """发 HTTP/1.1 请求,返 (status, headers, body_bytes)。"""
        payload = b""
        if body is not None:
            payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers = {
            "Host": "daemon",
            "User-Agent": "argos-tui/0.2.0",
            "Content-Length": str(len(payload)),
            "Connection": "close",
        }
        if session_id is not None:
            headers["X-Argos-Session"] = session_id
        if body is not None:
            headers["Content-Type"] = "application/json"
        req_lines = [f"{method} {path} HTTP/1.1"]
        for k, v in headers.items():
            req_lines.append(f"{k}: {v}")
        raw = ("\r\n".join(req_lines) + "\r\n\r\n").encode("latin-1") + payload

        async def _roundtrip() -> tuple[int, dict[str, str], bytes]:
            reader, writer = await asyncio.open_unix_connection(str(self._socket_path))
            try:
                writer.write(raw)
                await writer.drain()
                # 读 status line
                status_line = await reader.readline()
                if not status_line:
                    raise DaemonError("empty response")
                try:
                    _, status_str, _ = status_line.decode("latin-1").rstrip("\r\n").split(" ", 2)
                    status = int(status_str)
                except (ValueError, UnicodeDecodeError) as e:
                    raise DaemonError(f"bad status line: {e}")
                # 读 headers
                resp_headers: dict[str, str] = {}
                while True:
                    line = await reader.readline()
                    if line in (b"\r\n", b"\n", b""):
                        break
                    try:
                        k, v = line.decode("latin-1").rstrip("\r\n").split(":", 1)
                        resp_headers[k.strip().lower()] = v.strip()
                    except ValueError:
                        continue
                # 读 body
                cl = resp_headers.get("content-length")
                body_bytes = b""
                if cl:
                    try:
                        body_bytes = await reader.readexactly(int(cl))
                    except (ValueError, asyncio.IncompleteReadError):
                        pass
                return status, resp_headers, body_bytes
            finally:
                try:
                    writer.close()
                    await writer.wait_closed()
                except Exception:  # noqa: BLE001
                    pass

        # 整个往返受 self._timeout 硬约束:daemon 接了 socket 却卡死/半写时,无界 readline/
        # readexactly 会让"思考中…"永远转(daemon 是默认运行路径)。超时抛 DaemonError,
        # 让上层 try/except 接住并诚实降级 —— 而不是冻住界面(2026-06-18 排查 #1)。
        try:
            return await asyncio.wait_for(_roundtrip(), timeout=self._timeout)
        except asyncio.TimeoutError:
            raise DaemonError(
                t("daemon.srv.client_timeout",
                  timeout=self._timeout, method=method, path=path)
            )

    def _parse_json(self, status: int, body: bytes) -> dict:
        try:
            return json.loads(body.decode("utf-8") or "{}")
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise DaemonError(f"bad JSON body: {e} (status {status})")

    def _check(self, status: int, body: dict, expected: tuple[int, ...]) -> dict:
        if status not in expected:
            code = body.get("code", "")
            msg = body.get("error", "")
            raise DaemonError(f"HTTP {status} (code={code}): {msg}")
        return body

    # ── Public API ────────────────────────────────────────────────

    async def health(self) -> dict:
        status, _, raw = await self._request("GET", "/health")
        return self._parse_json(status, raw)

    async def version(self) -> dict:
        status, _, raw = await self._request("GET", "/version")
        return self._check(status, self._parse_json(status, raw), (200,))

    async def create_session(self) -> str:
        status, _, raw = await self._request("POST", "/sessions")
        body = self._check(status, self._parse_json(status, raw), (201,))
        return body["session_id"]

    async def heartbeat(self, session_id: str) -> dict:
        status, _, raw = await self._request(
            "POST", f"/sessions/{session_id}/heartbeat", session_id=session_id,
        )
        return self._check(status, self._parse_json(status, raw), (200,))

    async def delete_session(self, session_id: str) -> None:
        await self._request("DELETE", f"/sessions/{session_id}", session_id=session_id)

    async def list_runs(self, session_id: str, *, state: str | None = None) -> list[dict]:
        path = "/runs"
        if state:
            path = f"/runs?state={state}"
        status, _, raw = await self._request("GET", path, session_id=session_id)
        return self._check(status, self._parse_json(status, raw), (200,))

    async def create_run(
        self, session_id: str, *, goal: str, workspace: str = "",
        model: str = "", approval_level: str = "confirm", attachments=None,
    ) -> str:
        from argos.daemon.attachments_wire import encode_attachments
        body = {"goal": goal, "workspace": workspace, "model": model,
                "approval_level": approval_level}
        wire = encode_attachments(attachments)
        if wire:
            body["attachments"] = wire   # 图片 base64;无附件时不加键(请求体与现状一致)
        status, _, raw = await self._request(
            "POST", "/runs", session_id=session_id, body=body,
        )
        body_out = self._check(status, self._parse_json(status, raw), (201,))
        return body_out["run_id"]

    async def get_run(self, session_id: str, run_id: str) -> dict:
        status, _, raw = await self._request(
            "GET", f"/runs/{run_id}", session_id=session_id,
        )
        return self._check(status, self._parse_json(status, raw), (200,))

    async def pause(self, session_id: str, run_id: str) -> dict:
        status, _, raw = await self._request(
            "POST", f"/runs/{run_id}/pause", session_id=session_id,
        )
        return self._check(status, self._parse_json(status, raw), (202, 409))

    async def resume(self, session_id: str, run_id: str) -> dict:
        status, _, raw = await self._request(
            "POST", f"/runs/{run_id}/resume", session_id=session_id,
        )
        return self._check(status, self._parse_json(status, raw), (202, 409))

    async def cancel(self, session_id: str, run_id: str) -> dict:
        status, _, raw = await self._request(
            "POST", f"/runs/{run_id}/cancel", session_id=session_id,
        )
        return self._check(status, self._parse_json(status, raw), (202, 409))

    async def submit_approval(
        self, session_id: str, run_id: str, call_id: str, decision: str,
    ) -> dict:
        status, _, raw = await self._request(
            "POST", f"/runs/{run_id}/approval/{call_id}",
            session_id=session_id,
            body={"decision": decision},
        )
        return self._check(status, self._parse_json(status, raw), (200,))

    # ── SSE 订阅(长连接)───────────────────────────────────────────

    async def subscribe_events(
        self,
        run_id: str,
        session_id: str,
        *,
        since: int = 0,
    ) -> AsyncIterator[dict[str, Any]]:
        """订阅 run 事件流;每条 event yield 一个 dict。

        自写 SSE 解析:每行 `data: {...}` + 空行分隔。
        """
        req = (
            f"GET /runs/{run_id}/events?since={since} HTTP/1.1\r\n"
            f"Host: daemon\r\n"
            f"User-Agent: argos-tui/0.2.0\r\n"
            f"X-Argos-Session: {session_id}\r\n"
            f"Accept: text/event-stream\r\n"
            f"Connection: keep-alive\r\n\r\n"
        ).encode("latin-1")
        reader, writer = await asyncio.open_unix_connection(str(self._socket_path))
        try:
            writer.write(req)
            await writer.drain()
            # 跳过 status + headers
            status_line = await reader.readline()
            if not status_line:
                return
            while True:
                line = await reader.readline()
                if line in (b"\r\n", b"\n", b""):
                    break
            # 读 SSE 流
            current_event: str | None = None
            data_buf: list[str] = []
            while True:
                line = await reader.readline()
                if not line:
                    return
                # SSE 数据体是 UTF-8(server encode("utf-8"));latin-1 会把中文打成 mojibake。
                # SSE 按行分帧,UTF-8 多字节不含 \n,逐行 utf-8 解码安全。
                text = line.decode("utf-8", errors="replace").rstrip("\r\n")
                if not text:
                    # 空行 → 一个 event 结束
                    if data_buf:
                        data_str = "\n".join(data_buf)
                        try:
                            payload = json.loads(data_str)
                            payload["_event"] = current_event
                            yield payload
                        except json.JSONDecodeError as e:
                            log.warning("SSE bad JSON: %s", e)
                    current_event = None
                    data_buf = []
                    continue
                if text.startswith(":"):
                    # SSE comment(keepalive)→ 跳过
                    continue
                if text.startswith("event:"):
                    current_event = text[len("event:"):].strip()
                    continue
                if text.startswith("data:"):
                    data_buf.append(text[len("data:"):].lstrip())
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:  # noqa: BLE001
                pass
