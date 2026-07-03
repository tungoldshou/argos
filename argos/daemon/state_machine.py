from __future__ import annotations

import re
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from argos.daemon.index import StateIndex
    from argos.daemon.store import RunStore


STATES: frozenset[str] = frozenset({
    "pending", "running", "paused", "suspended",
    "completed", "failed", "cancelled",
})

TERMINAL_STATES: frozenset[str] = frozenset({"completed", "failed", "cancelled"})

ALLOWED: dict[str, set[str]] = {
    "pending":   {"running", "cancelled", "failed"},
    "running":   {"paused", "suspended", "completed", "failed", "cancelled"},
    "paused":    {"running", "cancelled", "failed", "suspended"},
    "suspended": {"running", "cancelled", "failed"},
    "completed": set(),
    "failed":    set(),
    "cancelled": set(),
}

RUN_ID_RE = re.compile(r"^[0-9a-f]{12}$")


class InvalidTransition(Exception):
    pass


def read_state(run_id: str, index: "StateIndex") -> str:
    entry = index.get(run_id)
    if entry is None:
        return "pending"
    return entry.state


def transition(
    *,
    current: str | None,
    target: str,
    index: "StateIndex",
    run_id: str,
    store: "RunStore | None",
    reason: str = "",
) -> str:
    if current is None:
        current = read_state(run_id, index)
    if current in TERMINAL_STATES:
        return current
    if target not in ALLOWED.get(current, set()):
        raise InvalidTransition(
            f"cannot transition run {run_id!r}: {current!r} -> {target!r} "
            f"(allowed: {sorted(ALLOWED.get(current, set()))})"
        )
    seq = 0
    if store is not None:
        seq = store.append(run_id, {
            "kind": "state_change",
            "ts": time.time(),
            "from": current,
            "to": target,
            "reason": reason,
        })
    now = time.time()
    entry = index.get(run_id)
    if entry is None:
        index.upsert(
            run_id, state=target, goal="", workspace="",
            created_at=now, updated_at=now, last_event_seq=seq,
        )
    elif seq > 0:
        index.upsert(run_id, state=target, updated_at=now, last_event_seq=seq)
    else:
        index.upsert(run_id, state=target, updated_at=now)
    return target
