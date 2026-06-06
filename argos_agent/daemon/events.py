"""Daemon 专属 3 个事件 dataclass(spec §10.1)。

复刻 tui/events.py 模式:`@dataclass(frozen=True, slots=True)` + `kind` 类属性常量,
便于和现有 Event 联合 + _KIND_TO_CLASS 路由。

3 类分开的理由:`RunMeta` = 冷启判别;`RunCheckpoint` = 恢复点;`RunFailure` = 错误信息;
混在 `state_change` 里 = 失去类型化 + 活动栏无法按 type 路由。"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RunMeta:
    """JSONL 第一行(冷启时第一行非 RunMeta → corruption,RunStore.replay 报 corruption)。

    字段对齐 spec §2.3 + §10.1:`run_id` / `goal` / `workspace` / `model` / `created_at`
    / `approval_level` / `max_steps`(`parent_run_id` 留 v1.1 fork 关系)。"""
    run_id: str
    goal: str
    workspace: str
    model: str
    created_at: float
    approval_level: str
    max_steps: int = 200
    parent_run_id: str | None = None

    # 类属性(不参与 dataclass 字段;asdict 不序列化)
    kind = "run_meta"

    def to_dict(self) -> dict:
        return {
            "kind": "run_meta",
            "run_id": self.run_id,
            "goal": self.goal,
            "workspace": self.workspace,
            "model": self.model,
            "created_at": self.created_at,
            "approval_level": self.approval_level,
            "max_steps": self.max_steps,
            "parent_run_id": self.parent_run_id,
        }


@dataclass(frozen=True, slots=True)
class RunCheckpoint:
    """_transition 之前 append;resume 时唯一读源(replay 算 last_event_seq)。"""
    ts: float
    last_step: int
    messages_count: int
    last_event_seq: int
    phase: str = "act"
    pending_approvals: int = 0

    kind = "run_checkpoint"

    def to_dict(self) -> dict:
        return {
            "kind": "run_checkpoint",
            "ts": self.ts,
            "last_step": self.last_step,
            "messages_count": self.messages_count,
            "last_event_seq": self.last_event_seq,
            "phase": self.phase,
            "pending_approvals": self.pending_approvals,
        }


@dataclass(frozen=True, slots=True)
class RunFailure:
    """协程未捕获异常时写;state_change(failed) 之前落 JSONL(根因+栈供 inspect 查)。"""
    ts: float
    error: str
    error_type: str
    traceback: str
    step: int = 0

    kind = "run_failure"

    def to_dict(self) -> dict:
        return {
            "kind": "run_failure",
            "ts": self.ts,
            "error": self.error,
            "error_type": self.error_type,
            "traceback": self.traceback,
            "step": self.step,
        }
