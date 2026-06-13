"""7 状态机 + ALLOWED 白名单 + InvalidTransition 异常(spec §2.2)。

- 7 状态:`pending` / `running` / `paused` / `suspended` / `completed` / `failed` / `cancelled`
- 终态:`completed` / `failed` / `cancelled` —— 不可再转,transition 入口 no-op
- from-state 动态读(transition 不传 current → 从 index 读):_transition 走单一真相源
- transition 副作用:append `state_change` 到 JSONL + index.upsert(state=...)

复刻 spec §2.2 表。"""
from __future__ import annotations

import re
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from argos.daemon.index import StateIndex
    from argos.daemon.store import RunStore


# 7 状态(spec §2.2 表)
STATES: frozenset[str] = frozenset({
    "pending", "running", "paused", "suspended",
    "completed", "failed", "cancelled",
})

TERMINAL_STATES: frozenset[str] = frozenset({"completed", "failed", "cancelled"})

# 白名单转换(spec §2.2 表)
ALLOWED: dict[str, set[str]] = {
    "pending":   {"running", "cancelled", "failed"},
    "running":   {"paused", "suspended", "completed", "failed", "cancelled"},
    "paused":    {"running", "cancelled", "failed", "suspended"},
    "suspended": {"running", "cancelled", "failed"},
    "completed": set(),
    "failed":    set(),
    "cancelled": set(),
}

# run_id 必须 12 hex(spec §2.3)
RUN_ID_RE = re.compile(r"^[0-9a-f]{12}$")


class InvalidTransition(Exception):
    """非法状态转换(spec §2.2)。"""


def read_state(run_id: str, index: "StateIndex") -> str:
    """从 index 读 run 状态;miss → 'pending'(新建 run 起点)。"""
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
    """执行状态转换(spec §2.2):

    1. 终态写保护:current ∈ TERMINAL_STATES → no-op,返 current
    2. dynamic from-state:current is None → 从 index 读
    3. 白名单校验:target ∈ ALLOWED[current] → 否则 InvalidTransition
    4. 副作用:append `state_change` 行到 JSONL(若 store 不为 None)
    5. index.upsert(state=target, updated_at=now)
    6. 返 target

    Args:
        current: 当前状态;None → 从 index 动态读
        target: 目标状态
        index: StateIndex 实例
        run_id: 12 hex
        store: RunStore 实例(可 None 用于纯状态机测试)
        reason: state_change 事件 reason 字段

    Returns:
        实际转换后的 target(= 当前状态,除非终态写保护命中返 current)
    """
    if current is None:
        current = read_state(run_id, index)
    # 终态写保护
    if current in TERMINAL_STATES:
        return current
    if target not in ALLOWED.get(current, set()):
        raise InvalidTransition(
            f"cannot transition run {run_id!r}: {current!r} -> {target!r} "
            f"(allowed: {sorted(ALLOWED.get(current, set()))})"
        )
    # 副作用
    if store is not None:
        store.append(run_id, {
            "kind": "state_change",
            "ts": time.time(),
            "from": current,
            "to": target,
            "reason": reason,
        })
    now = time.time()
    entry = index.get(run_id)
    if entry is None:
        # 没有 entry,创建一个最小 entry(target 状态)
        index.upsert(
            run_id, state=target, goal="", workspace="",
            created_at=now, updated_at=now, last_event_seq=0,
        )
    else:
        index.upsert(run_id, state=target, updated_at=now)
    return target
