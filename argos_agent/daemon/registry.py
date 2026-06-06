"""RunRegistry:daemon 内存注册表(spec #5b §4)。

- run_id → RunEntry(状态/累计 cost/focus/worktree_path)
- max_concurrent:5(可由 ARGOS_MAX_CONCURRENT 覆盖;本期硬编 5,D1)
- max_history:100(终态保留 N 条,超出按 created_at 升序删)

不在 RunStore JSONL 里 —— RunStore 仍是事件流真相源;registry 是 daemon 内存快查层。
"""
from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from argos_agent.daemon.state_machine import TERMINAL_STATES


@dataclass
class RunEntry:
    """内存注册表条目(spec #5b §4.1)。

    字段:
      run_id:12 hex(沿用 RunStore)
      state:7 状态之一
      goal:用户目标
      workspace:工作目录
      worktree_path:~/.argos/worktrees/<run_id> 或 temp
      created_at / updated_at:float epoch
      tokens_in / tokens_out:本 run 累计(由 CostUpdate 累加)
      cost_usd:累计(API 返 None 时为 None,不编造)
      focus_session_id:哪个 TUI session 把它当 active(None = 无)
      task:asyncio.Task(worker 句柄,内部用,repr=False)
      pause_event:asyncio.Event(默认 set = 不阻塞)
    """
    run_id: str
    state: str
    goal: str
    workspace: str
    worktree_path: str | None = None
    created_at: float = 0.0
    updated_at: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float | None = None
    focus_session_id: str | None = None
    task: asyncio.Task | None = field(default=None, repr=False)
    pause_event: asyncio.Event = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.pause_event is None:
            ev = asyncio.Event()
            ev.set()
            self.pause_event = ev


class RunRegistry:
    """并发安全(run_id → RunEntry)内存注册表。

    asyncio.Lock 保护 _entries 写(read 不持锁,dict 原子)。
    asyncio.Semaphore 控制最大并发(create_run 前 acquire,worker 终态时 release)。
    max_history 兜底终态条目数(超过按 created_at 升序删最旧)。
    """

    def __init__(self, *, max_concurrent: int = 5, max_history: int = 100):
        self._entries: dict[str, RunEntry] = {}
        self._max_concurrent = max_concurrent
        self._max_history = max_history
        self._lock = asyncio.Lock()
        self._sem = asyncio.Semaphore(max_concurrent)
        # 防 release_slot 滥用:记录已 acquire 的次数
        self._acquired_count: dict[str, int] = {}   # run_id → 已经 acquire 的次数(防御性)

    @property
    def max_concurrent(self) -> int:
        return self._max_concurrent

    @property
    def max_history(self) -> int:
        return self._max_history

    @property
    def active_count(self) -> int:
        """当前非终态 run 数。"""
        return sum(1 for e in self._entries.values() if e.state not in TERMINAL_STATES)

    @property
    def sem(self) -> asyncio.Semaphore:
        """暴露给上层(并发满判断)。"""
        return self._sem

    @property
    def size(self) -> int:
        return len(self._entries)

    async def register(
        self, *, run_id: str, goal: str, workspace: str,
        worktree_path: str | None = None,
    ) -> RunEntry:
        """注册新 run;返回 RunEntry(供调用方进一步配置)。"""
        now = time.time()
        entry = RunEntry(
            run_id=run_id, state="pending", goal=goal, workspace=workspace,
            worktree_path=worktree_path,
            created_at=now, updated_at=now,
        )
        async with self._lock:
            self._entries[run_id] = entry
        return entry

    def get(self, run_id: str) -> RunEntry | None:
        return self._entries.get(run_id)

    def list(self, *, state: str | None = None) -> list[RunEntry]:
        if state is None:
            return list(self._entries.values())
        return [e for e in self._entries.values() if e.state == state]

    def mark(self, *, run_id: str, state: str) -> None:
        """改状态(worker / server 调);不在锁里(只改一字段,读 snapshot 容忍)。"""
        e = self._entries.get(run_id)
        if e is None:
            return
        e.state = state
        e.updated_at = time.time()

    def add_cost(
        self, *, run_id: str, tokens_in_delta: int = 0,
        tokens_out_delta: int = 0, cost_usd_delta: float | None = None,
    ) -> None:
        """累加 cost(cost_usd_delta=None 不累加,保 None 语义)。"""
        e = self._entries.get(run_id)
        if e is None:
            return
        e.tokens_in += int(tokens_in_delta)
        e.tokens_out += int(tokens_out_delta)
        if cost_usd_delta is not None:
            e.cost_usd = (e.cost_usd or 0.0) + cost_usd_delta
        e.updated_at = time.time()

    def set_focus(self, *, run_id: str, session_id: str | None) -> None:
        e = self._entries.get(run_id)
        if e is None:
            return
        e.focus_session_id = session_id
        e.updated_at = time.time()

    def get_focus(self, *, run_id: str) -> str | None:
        e = self._entries.get(run_id)
        return e.focus_session_id if e is not None else None

    # ── semaphore ────────────────────────────────────────────────────

    async def acquire_slot(self) -> None:
        """抢一个并发槽(阻塞到有空位)。"""
        await self._sem.acquire()

    def release_slot(self) -> None:
        """还一个并发槽(worker 终态时调);多 release 防御性不抛。"""
        try:
            self._sem.release()
        except ValueError:
            # semaphore 已 full(>= initial value),吞掉
            pass

    def has_capacity(self) -> bool:
        """非阻塞:看是否有空槽。"""
        return not self._sem.locked() and self._sem._value > 0  # type: ignore[attr-defined]

    # ── cleanup / max_history ───────────────────────────────────────

    async def cleanup(self, *, run_id: str, terminal_state: str) -> None:
        """worker 终态时调:
          1. 标状态
          2. 释放 semaphore 槽位
          3. 缩 max_history(超 cap 删最旧终态)
        """
        async with self._lock:
            e = self._entries.get(run_id)
            if e is None:
                return
            e.state = terminal_state
            e.updated_at = time.time()
        # 释放槽位(即便 entry 不存在,防御性 release)
        self.release_slot()
        # 缩 cap
        await self._enforce_max_history()

    async def _enforce_max_history(self) -> None:
        """超 max_history → 删最旧终态(按 created_at 升序)。"""
        async with self._lock:
            terminal = [e for e in self._entries.values() if e.state in TERMINAL_STATES]
            if len(terminal) <= self._max_history:
                return
            # 排序:最旧在前
            terminal.sort(key=lambda e: e.created_at)
            to_remove = terminal[: len(terminal) - self._max_history]
            for e in to_remove:
                self._entries.pop(e.run_id, None)

    def snapshot(self) -> list[dict[str, Any]]:
        """返所有 entry 的字典列表(供调试 / health)。"""
        out = []
        for e in self._entries.values():
            out.append({
                "run_id": e.run_id, "state": e.state, "goal": e.goal,
                "workspace": e.workspace, "worktree_path": e.worktree_path,
                "created_at": e.created_at, "updated_at": e.updated_at,
                "tokens_in": e.tokens_in, "tokens_out": e.tokens_out,
                "cost_usd": e.cost_usd, "focus_session_id": e.focus_session_id,
            })
        return out


# ── module-level helper ────────────────────────────────────────────────


def new_run_id() -> str:
    """12 hex run_id(沿用 #5a RunManager.create_run)。"""
    return uuid.uuid4().hex[:12]
