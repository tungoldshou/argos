"""Internal documentation."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import AsyncIterator

from argos.i18n import t

log = logging.getLogger(__name__)

_MAX_RETRIES = 3
_BACKOFF = (0.5, 1.0, 2.0)


class DaemonEventSource:
    """Internal documentation."""

    def __init__(
        self,
        socket_path: Path,
        run_id: str,
        session_id: str,
        *,
        since: int = 0,
        max_retries: int = _MAX_RETRIES,
    ) -> None:
        self._socket_path = Path(socket_path)
        self._run_id = run_id
        self._session_id = session_id
        self._since = since
        self._max_retries = max_retries
        self._stopped = False
        self._last_seq: int = since

    def stop(self) -> None:
        """Internal documentation."""
        self._stopped = True

    def __aiter__(self) -> "DaemonEventSource":
        return self

    async def __anext__(self):
        """Internal documentation."""
        if self._stopped:
            raise StopAsyncIteration
        raise StopAsyncIteration

    async def stream(self) -> AsyncIterator:
        """Internal documentation."""
        from argos.protocol.events import deserialize_event, Error as ErrorEvent

        retries = 0
        while not self._stopped:
            try:
                async for ev_dict in self._subscribe_once(since=self._last_seq):
                    if self._stopped:
                        return
                    seq = ev_dict.pop("_seq", None)
                    if isinstance(seq, int) and seq > self._last_seq:
                        self._last_seq = seq
                    kind = ev_dict.get("kind", "")
                    typed = self._try_deserialize(kind, ev_dict)
                    if typed is not None:
                        yield typed
                return
            except asyncio.CancelledError:
                return
            except Exception as e:  # noqa: BLE001
                retries += 1
                if retries > self._max_retries:
                    log.warning(
                        "DaemonEventSource: max retries exceeded for run %s: %s",
                        self._run_id, e,
                    )
                    yield ErrorEvent(
                        message=t(
                            "daemon.srv.reconnect_failed",
                            run_id=self._run_id,
                            max_retries=self._max_retries,
                            error=e,
                        ),
                        chain=[f"{type(e).__name__}: {e}"],
                    )
                    return
                backoff = _BACKOFF[min(retries - 1, len(_BACKOFF) - 1)]
                log.info(
                    "DaemonEventSource: retry %d/%d in %.1fs (run=%s, err=%s)",
                    retries, self._max_retries, backoff, self._run_id, e,
                )
                await asyncio.sleep(backoff)

    async def _subscribe_once(self, since: int = 0) -> AsyncIterator[dict]:
        """Internal documentation."""
        import json

        req = (
            f"GET /runs/{self._run_id}/events?since={since} HTTP/1.1\r\n"
            f"Host: daemon\r\n"
            f"User-Agent: argos-tui/0.2.0\r\n"
            f"X-Argos-Session: {self._session_id}\r\n"
            f"Accept: text/event-stream\r\n"
            f"Connection: keep-alive\r\n\r\n"
        ).encode("latin-1")

        reader, writer = await asyncio.open_unix_connection(str(self._socket_path))
        try:
            writer.write(req)
            await writer.drain()

            status_line = await reader.readline()
            if not status_line:
                raise ConnectionError("daemon: empty response")
            status_str = status_line.decode("latin-1", errors="replace")
            parts = status_str.split(" ", 2)
            if len(parts) >= 2:
                try:
                    code = int(parts[1])
                    if code != 200:
                        raise ConnectionError(f"daemon SSE: HTTP {code}")
                except ValueError:
                    pass

            while True:
                hdr = await reader.readline()
                if hdr in (b"\r\n", b"\n", b""):
                    break

            current_event: str | None = None
            data_buf: list[str] = []
            while True:
                line = await reader.readline()
                if not line:
                    if data_buf:
                        data_str = "\n".join(data_buf)
                        try:
                            payload = json.loads(data_str)
                            payload["_event"] = current_event
                            yield payload
                        except json.JSONDecodeError:
                            pass
                    return
                text = line.decode("utf-8", errors="replace").rstrip("\r\n")
                if not text:
                    if data_buf:
                        data_str = "\n".join(data_buf)
                        try:
                            payload = json.loads(data_str)
                            payload["_event"] = current_event
                            yield payload
                        except json.JSONDecodeError as e:
                            log.warning("DaemonEventSource: bad JSON: %s", e)
                    current_event = None
                    data_buf = []
                    continue
                if text.startswith(":"):
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

    def _try_deserialize(self, kind: str, ev_dict: dict):
        """Internal documentation."""
        import json
        from argos.protocol.events import deserialize_event, _KIND_TO_CLASS

        _SKIP_KINDS = {
            "approval_response",
            "plan_decision_response",
            "state_change",
            "undo_done",
        }
        if kind in _SKIP_KINDS:
            return None
        if kind not in _KIND_TO_CLASS:
            return None

        inner = {k: v for k, v in ev_dict.items() if k not in ("_event", "kind")}
        blob = json.dumps({"kind": kind, "data": inner}, ensure_ascii=False)
        try:
            return deserialize_event(blob)
        except Exception as e:  # noqa: BLE001
            log.debug("DaemonEventSource: deserialize failed kind=%s: %s", kind, e)
            return None
