"""Internal documentation."""
from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


CURRENT_VERSION: int = 1


@dataclass
class IndexEntry:
    state: str
    goal: str
    workspace: str
    created_at: float
    updated_at: float
    last_event_seq: int = 0
    pid: int | None = None
    model: str = ""
    approval_level: str = "confirm"
    session_id: str = ""


class StateIndex:
    """Internal documentation."""

    def __init__(self, path: Path):
        self._path = Path(path)
        self._runs: dict[str, IndexEntry] = {}

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> None:
        """Internal documentation."""
        if not self._path.exists():
            self._runs = {}
            return
        try:
            blob = json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            self._runs = {}
            return
        runs = blob.get("runs", {}) if isinstance(blob, dict) else {}
        self._runs = {}
        for rid, raw in runs.items():
            if not isinstance(raw, dict):
                continue
            try:
                self._runs[rid] = IndexEntry(
                    state=raw.get("state", "pending"),
                    goal=raw.get("goal", ""),
                    workspace=raw.get("workspace", ""),
                    created_at=float(raw.get("created_at", 0.0)),
                    updated_at=float(raw.get("updated_at", 0.0)),
                    last_event_seq=int(raw.get("last_event_seq", 0)),
                    pid=raw.get("pid"),
                    model=raw.get("model", ""),
                    approval_level=raw.get("approval_level", "confirm"),
                    session_id=raw.get("session_id", ""),
                )
            except (TypeError, ValueError):
                continue

    def save(self) -> None:
        """Internal documentation."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        payload = {
            "version": CURRENT_VERSION,
            "runs": {rid: asdict(e) for rid, e in self._runs.items()},
        }
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self._path)

    def get(self, run_id: str) -> IndexEntry | None:
        return self._runs.get(run_id)

    def list(self) -> list[tuple[str, IndexEntry]]:
        return list(self._runs.items())

    def upsert(
        self,
        run_id: str,
        *,
        state: str | None = None,
        goal: str | None = None,
        workspace: str | None = None,
        created_at: float | None = None,
        updated_at: float | None = None,
        last_event_seq: int | None = None,
        pid: int | None = None,
        model: str | None = None,
        approval_level: str | None = None,
        session_id: str | None = None,
    ) -> None:
        """Internal documentation."""
        existing = self._runs.get(run_id)
        now = time.time()
        if existing is None:
            self._runs[run_id] = IndexEntry(
                state=state or "pending",
                goal=goal or "",
                workspace=workspace or "",
                created_at=created_at if created_at is not None else now,
                updated_at=updated_at if updated_at is not None else now,
                last_event_seq=last_event_seq or 0,
                pid=pid,
                model=model or "",
                approval_level=approval_level or "confirm",
                session_id=session_id or "",
            )
        else:
            if state is not None:
                existing.state = state
            if goal is not None:
                existing.goal = goal
            if workspace is not None:
                existing.workspace = workspace
            if created_at is not None:
                existing.created_at = created_at
            if updated_at is not None:
                existing.updated_at = updated_at
            if last_event_seq is not None:
                existing.last_event_seq = last_event_seq
            if pid is not None:
                existing.pid = pid
            if model is not None:
                existing.model = model
            if approval_level is not None:
                existing.approval_level = approval_level
            if session_id is not None:
                existing.session_id = session_id

    def remove(self, run_id: str) -> None:
        """Internal documentation."""
        self._runs.pop(run_id, None)
