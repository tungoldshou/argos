"""DaemonEventSource — SSE 适配器(v6 P3b)。

将 GET /runs/{id}/events SSE 流 → envelope dict → deserialize_event() → yield typed Event,
让 TUI 现有渲染路径（async for ev in bus）零改动复用。

特性：
  · since=N 续传（seq 断点恢复，seq 字段来自 _seq 附加字段）
  · 断线自动重连（指数退避 0.5/1/2 s，最多 3 次）
  · 断连超阈值 → 投诚实 Error 事件并停止（不假装连通）
  · 未知 kind → pass 跳过（协议前向兼容）
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import AsyncIterator

log = logging.getLogger(__name__)

# 最大重连次数（超过后投 Error 事件并停止）
_MAX_RETRIES = 3
# 退避延迟序列（秒）
_BACKOFF = (0.5, 1.0, 2.0)


class DaemonEventSource:
    """SSE 事件源适配器。

    用法::

        source = DaemonEventSource(socket_path, run_id, session_id)
        async for ev in source:
            # ev 是 protocol.events 的 typed Event 实例
            await bus.emit(ev)

    停止后调用 stop() 或 break async for 即可。
    """

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
        self._last_seq: int = since   # 追踪已消费的最大 seq，断线重连用

    def stop(self) -> None:
        """外部停止信号（Esc / cancel 后调用）。"""
        self._stopped = True

    def __aiter__(self) -> "DaemonEventSource":
        return self

    async def __anext__(self):
        """一次性把"直到流断"的所有事件全部 yield，内部递归重试。"""
        # 已被外部停止
        if self._stopped:
            raise StopAsyncIteration
        raise StopAsyncIteration  # 实际实现在 _stream() 里，这里仅为类型协议占位

    async def stream(self) -> AsyncIterator:
        """主 async generator：带断线重连的 typed Event 流。

        调用方式::

            async for ev in source.stream():
                await bus.emit(ev)
        """
        from argos_agent.protocol.events import deserialize_event, Error as ErrorEvent

        retries = 0
        while not self._stopped:
            try:
                async for ev_dict in self._subscribe_once(since=self._last_seq):
                    if self._stopped:
                        return
                    # 更新续传游标
                    seq = ev_dict.pop("_seq", None)
                    if isinstance(seq, int) and seq > self._last_seq:
                        self._last_seq = seq
                    # 尝试反序列化
                    kind = ev_dict.get("kind", "")
                    typed = self._try_deserialize(kind, ev_dict)
                    if typed is not None:
                        yield typed
                # 流正常结束（run 完成）—— 停止
                return
            except asyncio.CancelledError:
                return
            except Exception as e:  # noqa: BLE001
                retries += 1
                if retries > self._max_retries:
                    # 超阈值：投诚实 Error 事件并停止
                    log.warning(
                        "DaemonEventSource: max retries exceeded for run %s: %s",
                        self._run_id, e,
                    )
                    yield ErrorEvent(
                        message=(
                            f"daemon 连接断开（run={self._run_id!r}），"
                            f"重连 {self._max_retries} 次仍失败：{e}"
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
        """单次 SSE 订阅（since=N 续传）。遇到 EOF / 连接断 raise 异常让上层重试。"""
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

            # 读 status line
            status_line = await reader.readline()
            if not status_line:
                raise ConnectionError("daemon: empty response")
            status_str = status_line.decode("latin-1", errors="replace")
            # 简单取 HTTP 状态码
            parts = status_str.split(" ", 2)
            if len(parts) >= 2:
                try:
                    code = int(parts[1])
                    if code != 200:
                        raise ConnectionError(f"daemon SSE: HTTP {code}")
                except ValueError:
                    pass

            # 跳过响应头
            while True:
                hdr = await reader.readline()
                if hdr in (b"\r\n", b"\n", b""):
                    break

            # 读 SSE 流
            current_event: str | None = None
            data_buf: list[str] = []
            while True:
                line = await reader.readline()
                if not line:
                    # EOF：run 已完成或连接断
                    if data_buf:
                        data_str = "\n".join(data_buf)
                        try:
                            payload = json.loads(data_str)
                            payload["_event"] = current_event
                            yield payload
                        except json.JSONDecodeError:
                            pass
                    return
                text = line.decode("latin-1", errors="replace").rstrip("\r\n")
                if not text:
                    # 空行 = 一个 SSE event 结束
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
                    # keepalive comment → 跳过
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
        """dict → typed Event；未知 kind 返 None（前向兼容）。

        两条路径：
          1. kind 对应已知类型 → deserialize_event(json_str) 还原 frozen dataclass
          2. 未知 kind → None（协议前向兼容，新版 daemon 推的新事件不崩老 TUI）
        """
        import json
        from argos_agent.protocol.events import deserialize_event, _KIND_TO_CLASS

        # 过滤非事件类 dict（keepalive 残留、audit-only 事件等）
        _SKIP_KINDS = {
            "approval_response",  # 只是审计广播，TUI inline 自己处理
            "plan_decision_response",
            "state_change",
            "undo_done",
        }
        if kind in _SKIP_KINDS:
            return None
        if kind not in _KIND_TO_CLASS:
            return None

        # 重组 {"kind": k, "data": {...}} 格式给 deserialize_event
        inner = {k: v for k, v in ev_dict.items() if k not in ("_event", "kind")}
        blob = json.dumps({"kind": kind, "data": inner}, ensure_ascii=False)
        try:
            return deserialize_event(blob)
        except Exception as e:  # noqa: BLE001
            log.debug("DaemonEventSource: deserialize failed kind=%s: %s", kind, e)
            return None
