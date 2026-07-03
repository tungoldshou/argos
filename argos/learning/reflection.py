from __future__ import annotations

from pathlib import Path
from typing import Any


def reflect_failure(
    *,
    run_id: str,
    store_dir: Path,
    goal: str,
    verify_cmd: str | None,
    verdict_status: str,
    self_verified: bool = False,
    skills_root: Path | None = None,
) -> None:
    snippet: str = ""
    try:
        from argos.daemon.store import RunStore
        rs = RunStore(runs_dir=store_dir)
        last_code_result = None
        for ev in rs.replay(run_id):
            if ev.get("kind") == "code_result" and not ev.get("ok", True):
                last_code_result = ev
                break
        if last_code_result:
            snippet = (last_code_result.get("exc") or "")[:200]
    except Exception:  # noqa: BLE001
        snippet = "(store unreadable)"

    try:
        from argos.memory.auto import capture_event as _capture
        _capture(
            "task_reflection",
            run_id=run_id,
            goal=(goal or "")[:120],
            verify_cmd=(verify_cmd or "")[:120] if verify_cmd else None,
            verdict=verdict_status,
            self_verified=bool(self_verified),
            last_exc_snippet=snippet or None,
        )
    except Exception:  # noqa: BLE001
        pass
