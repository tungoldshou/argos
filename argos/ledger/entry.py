"""Internal documentation."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Reversible = Literal["yes", "no", "unknown"]

UndoState = Literal["available", "done", "impossible"]


@dataclass(frozen=True, slots=True)
class LedgerEntry:
    """Internal documentation."""
    ts: float
    run_id: str
    seq: int
    action: str
    summary_human: str
    risk: str                         # "low" | "medium" | "high"
    reversible: Reversible
    undo_token: str | None
    receipt_sig: str
    undo_state: UndoState

    def to_dict(self) -> dict:
        """Internal documentation."""
        return {
            "ts": self.ts,
            "run_id": self.run_id,
            "seq": self.seq,
            "action": self.action,
            "summary_human": self.summary_human,
            "risk": self.risk,
            "reversible": self.reversible,
            "undo_token": self.undo_token,
            "receipt_sig": self.receipt_sig,
            "undo_state": self.undo_state,
        }

    @staticmethod
    def from_dict(d: dict) -> "LedgerEntry":
        """Internal documentation."""
        return LedgerEntry(
            ts=float(d["ts"]),
            run_id=str(d["run_id"]),
            seq=int(d["seq"]),
            action=str(d["action"]),
            summary_human=str(d["summary_human"]),
            risk=str(d["risk"]),
            reversible=d["reversible"],  # type: ignore[arg-type]
            undo_token=d.get("undo_token"),
            receipt_sig=str(d["receipt_sig"]),
            undo_state=d["undo_state"],  # type: ignore[arg-type]
        )

    def with_undo_state(self, state: UndoState) -> "LedgerEntry":
        """Internal documentation."""
        import dataclasses
        return dataclasses.replace(self, undo_state=state)
