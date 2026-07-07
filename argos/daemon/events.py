from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RunMeta:
    run_id: str
    goal: str
    workspace: str
    model: str
    created_at: float
    permission_mode: str
    session_id: str = ""
    max_steps: int = 200
    parent_run_id: str | None = None

    kind = "run_meta"

    def to_dict(self) -> dict:
        return {
            "kind": "run_meta",
            "run_id": self.run_id,
            "goal": self.goal,
            "workspace": self.workspace,
            "model": self.model,
            "created_at": self.created_at,
            "permission_mode": self.permission_mode,
            "session_id": self.session_id,
            "max_steps": self.max_steps,
            "parent_run_id": self.parent_run_id,
        }


@dataclass(frozen=True, slots=True)
class RunCheckpoint:
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
