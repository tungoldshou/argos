"""Internal documentation."""
from __future__ import annotations

import json
import uuid
import time
from dataclasses import dataclass
from typing import Any

from argos.protocol.events import Event, serialize_event, event_kind


@dataclass(frozen=True, slots=True)
class EventEnvelope:
    """Internal documentation."""
    v: int
    seq: int
    kind: str       # Event.kind
    id: str
    ts: float
    session: str    # session_id
    run: str
    data: dict

    def to_json(self) -> str:
        """Internal documentation."""
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
        """Internal documentation."""
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
    """Internal documentation."""
    import dataclasses
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
