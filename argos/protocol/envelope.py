"""ACP EventEnvelope — Argos Client Protocol 传输帧(v6 P0)。

P0 只定义帧格式,不接 server(P1 接线)。

字段语义:
  v        : 协议版本(整数,当前固定为 1)
  seq      : 单 run 内单调递增序号(从 0 起),用于客户端检测乱序/丢帧
  kind     : Event.kind 字符串(等价于 EventKind Literal)
  id       : 帧唯一标识符(UUID4 hex,幂等回放用)
  ts       : UNIX 时间戳(float, seconds),UTC
  session  : session_id(对应 ArgosStore.sessions 主键)
  run      : run_id(可选,无 run 上下文时为空串)
  data     : serialize_event 的 payload dict(Event 的 asdict 展开结果)

冻结 dataclass(frozen=True),与 Event 族保持一致风格。
"""
from __future__ import annotations

import json
import uuid
import time
from dataclasses import dataclass
from typing import Any

from argos.protocol.events import Event, serialize_event, event_kind


@dataclass(frozen=True, slots=True)
class EventEnvelope:
    """ACP 帧:把一个 Event 加上传输元数据包裹后序列化到线路上。

    P0 只定义格式;P1 接 server 时 wrap_event 会被 RunWorker 调用。
    """
    v: int          # 协议版本
    seq: int        # 单 run 内单调递增序号
    kind: str       # Event.kind
    id: str         # 帧唯一 ID(UUID4 hex)
    ts: float       # UNIX 时间戳(UTC seconds)
    session: str    # session_id
    run: str        # run_id(无则空串)
    data: dict      # Event payload(asdict 展开结果,与 serialize_event 内部一致)

    def to_json(self) -> str:
        """帧 → JSON 串(线路序列化)。ensure_ascii=False 保留中文。"""
        return json.dumps(
            {
                "v": self.v,
                "seq": self.seq,
                "kind": self.kind,
                "id": self.id,
                "ts": self.ts,
                "session": self.session,
                "run": self.run,
                "data": self.data,
            },
            ensure_ascii=False,
        )

    @classmethod
    def from_json(cls, blob: str) -> "EventEnvelope":
        """JSON 串 → 帧。字段缺失 → KeyError(fail-loud,坏数据不静默吞)。"""
        obj = json.loads(blob)
        return cls(
            v=obj["v"],
            seq=obj["seq"],
            kind=obj["kind"],
            id=obj["id"],
            ts=obj["ts"],
            session=obj["session"],
            run=obj["run"],
            data=obj["data"],
        )


def wrap_event(
    ev: Event,
    *,
    seq: int,
    session: str,
    run: str = "",
    ts: float | None = None,
    id: str | None = None,  # noqa: A002
) -> EventEnvelope:
    """把一个 Event 包裹成 EventEnvelope。

    参数:
        ev       : 要包裹的事件实例
        seq      : 调用方维护的单调序号
        session  : session_id
        run      : run_id(无则传 "" 或省略)
        ts       : UNIX 时间戳;None = time.time()
        id       : 帧 UUID hex;None = uuid.uuid4().hex

    返回值:
        冻结的 EventEnvelope 实例
    """
    import dataclasses
    # 从 serialize_event 复用 asdict 展开逻辑,保持 data 与持久化格式完全一致
    payload = dataclasses.asdict(ev)  # type: ignore[arg-type]
    return EventEnvelope(
        v=1,
        seq=seq,
        kind=event_kind(ev),
        id=id if id is not None else uuid.uuid4().hex,
        ts=ts if ts is not None else time.time(),
        session=session,
        run=run,
        data=payload,
    )
