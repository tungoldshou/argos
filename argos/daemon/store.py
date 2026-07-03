from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Iterator

log = logging.getLogger(__name__)


class CorruptionError(Exception):
    pass


class RunStore:

    def __init__(self, runs_dir: Path):
        self._dir = Path(runs_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._seq: dict[str, int] = {}

    @property
    def runs_dir(self) -> Path:
        return self._dir

    def _path_for(self, run_id: str) -> Path:
        return self._dir / f"{run_id}.jsonl"

    def exists(self, run_id: str) -> bool:
        return self._path_for(run_id).exists()

    def list_runs(self) -> list[str]:
        if not self._dir.exists():
            return []
        return sorted(p.stem for p in self._dir.glob("*.jsonl"))

    def append(self, run_id: str, event: dict[str, Any]) -> int:
        if run_id.startswith("_"):
            raise ValueError(
                f"refusing to persist virtual stream {run_id!r} to the run store "
                "(`_`-prefixed streams are live-only broadcast buses, never persisted)"
            )
        path = self._path_for(run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        is_meta = event.get("kind") == "run_meta"
        seq = 0
        if not is_meta:
            seq = self._next_seq(run_id)
            event["_seq"] = seq
        line = json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n"
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line)
            if is_meta:
                fh.flush()
                os.fsync(fh.fileno())
        return seq

    def _next_seq(self, run_id: str) -> int:
        cur = self._seq.get(run_id)
        if cur is None:
            cur = self._max_seq_in_file(run_id)
        nxt = cur + 1
        self._seq[run_id] = nxt
        return nxt

    def _max_seq_in_file(self, run_id: str) -> int:
        path = self._path_for(run_id)
        if not path.exists():
            return 0
        m = 0
        with path.open("r", encoding="utf-8") as fh:
            for raw in fh:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    ev = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                s = ev.get("_seq") if isinstance(ev, dict) else None
                if isinstance(s, int) and s > m:
                    m = s
        return m

    def replay(
        self,
        run_id: str,
        since_seq: int = 0,
    ) -> Iterator[dict[str, Any]]:
        path = self._path_for(run_id)
        if not path.exists():
            return
        meta_seen = False
        with path.open("r", encoding="utf-8") as fh:
            for raw in fh:
                raw = raw.rstrip("\n").rstrip("\r")
                if not raw:
                    continue
                try:
                    ev = json.loads(raw)
                except json.JSONDecodeError as e:
                    log.warning("RunStore.replay: corrupt line in %s: %s (skipping)", path, e)
                    continue
                if not isinstance(ev, dict):
                    log.warning("RunStore.replay: non-dict line in %s (skipping)", path)
                    continue
                if not meta_seen:
                    if ev.get("kind") != "run_meta":
                        raise CorruptionError(
                            f"first line of {path} is not run_meta: {ev.get('kind')!r}"
                        )
                    meta_seen = True
                    yield ev
                    continue
                ev_seq = ev.get("_seq")
                if ev_seq is None:
                    if since_seq <= 0:
                        yield ev
                    continue
                if ev_seq > since_seq:
                    yield ev

    def last_state(self, run_id: str) -> str | None:
        last: str | None = None
        for ev in self.replay(run_id):
            if ev.get("kind") == "state_change":
                last = ev.get("to")
        return last

    def last_checkpoint(self, run_id: str) -> dict[str, Any] | None:
        last: dict[str, Any] | None = None
        for ev in self.replay(run_id):
            if ev.get("kind") == "run_checkpoint":
                last = ev
        return last
