"""Internal documentation."""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any

from argos import config, jsonl_log
from argos.eval.runner import EvalResult

_RUNS_DIR: Path | None = None
_WRITE_LOCK = threading.Lock()


def _runs_dir(base: Path | None = None) -> Path:
    """Internal documentation."""
    if base is not None:
        return base / "runs"
    if _RUNS_DIR is not None:
        return _RUNS_DIR
    return Path(
        config.get("ARGOS_CONFIG_DIR") or (Path.home() / ".argos")
    ).expanduser() / "eval" / "runs"


def _date_str(ts: float) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(ts))


def append(result: EvalResult, *, base: Path | None = None) -> None:
    """Internal documentation."""
    d = _runs_dir(base) / _date_str(result.finished_at)
    p = d / f"{result.run_id}.jsonl"
    line = result.to_json() + "\n"
    with _WRITE_LOCK:
        jsonl_log.append_line(p, line)


def list_runs(
    *, base: Path | None = None, date: str | None = None, limit: int = 50,
) -> list[EvalResult]:
    """Internal documentation."""
    out: list[EvalResult] = []
    root = _runs_dir(base)
    if not root.exists():
        return out
    if date is not None:
        dates = [date]
    else:
        try:
            dates = sorted(
                (d.name for d in root.iterdir() if d.is_dir()),
                reverse=True,
            )
        except OSError:
            return out
    for d in dates:
        day = root / d
        if not day.is_dir():
            continue
        try:
            files = sorted(day.glob("*.jsonl"), reverse=True)
        except OSError:
            continue
        for p in files:
            try:
                text = p.read_text("utf-8")
            except OSError:
                continue
            for line in text.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(EvalResult.from_json(line))
                except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                    continue
            if len(out) >= limit:
                return out[:limit]
    return out[:limit]


def load_run(run_id: str, *, base: Path | None = None) -> EvalResult | None:
    """Internal documentation."""
    root = _runs_dir(base)
    if not root.exists():
        return None
    try:
        days = sorted(
            (d for d in root.iterdir() if d.is_dir()),
            key=lambda x: x.name,
            reverse=True,
        )
    except OSError:
        return None
    for day in days:
        p = day / f"{run_id}.jsonl"
        if not p.is_file():
            continue
        try:
            text = p.read_text("utf-8")
        except OSError:
            continue
        for line in text.splitlines():
            line = line.strip()
            if line:
                try:
                    return EvalResult.from_json(line)
                except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                    continue
    return None


def summary(
    *, base: Path | None = None, since_days: int = 7,
) -> dict[str, dict[str, dict[str, Any]]]:
    """Internal documentation."""
    cutoff = time.time() - since_days * 86400
    runs = [r for r in list_runs(base=base, limit=10000) if r.finished_at >= cutoff]
    out: dict[str, dict[str, dict[str, Any]]] = {}
    for r in runs:
        cat = _category_of(r.task_id)
        m = out.setdefault(r.model_tier, {}).setdefault(
            cat, {"passed": 0, "total": 0, "pass_rate": 0.0},
        )
        m["total"] += 1
        if r.pass_status == "passed":
            m["passed"] += 1
    for m in out.values():
        for c in m.values():
            if c["total"]:
                c["pass_rate"] = round(c["passed"] / c["total"], 4)
    return out


def _category_of(task_id: str) -> str:
    """Internal documentation."""
    parts = task_id.split("_")
    cat_parts: list[str] = []
    for p in parts:
        if p.isdigit():
            break
        cat_parts.append(p)
    return "_".join(cat_parts) if cat_parts else task_id
