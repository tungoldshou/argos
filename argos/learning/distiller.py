"""Internal documentation."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Protocol

from argos.i18n import t
from argos.memory.auto import _redact_secrets


class _EventSource(Protocol):
    """Internal documentation."""
    def replay(self, run_id: str) -> Iterable[dict]: ...  # noqa: D401, ANN001


@dataclass(frozen=True, slots=True)
class SkillCandidate:
    """Internal documentation."""

    name: str
    body_markdown: str
    verify_cmd: str | None
    skill_md_path: Path
    # Performance metrics captured from replay events (all default-safe for old candidates)
    verdict_status: str | None = None      # from verify_verdict: "passed"|"failed"|"unverifiable"
    tokens_in: int = 0                     # from cost_update (cumulative last seen)
    tokens_out: int = 0                    # from cost_update (cumulative last seen)
    cost_usd: float | None = None          # from cost_update; None = unknown
    steps: int = 0                         # from phase_change actions count at verify phase


def slugify_goal(goal: str, fallback: str = "learned") -> str:
    g = (goal or "").strip().lower()
    if not g:
        return fallback
    g = re.sub(r"[^a-z0-9]+", "-", g)
    g = re.sub(r"-+", "-", g).strip("-")
    if not g:
        return fallback
    return g[:40]


_slugify_goal = slugify_goal


def _format_code_block(snippets: list[str]) -> str:
    """Internal documentation."""
    if not snippets:
        return ""
    body = "\n\n".join(snippets)
    return f"```python\n{body.rstrip()}\n```"


def _build_markdown(
    *,
    name: str,
    goal: str,
    verify_cmd: str | None,
    code_snippets: list[str],
    source_run_id: str,
) -> str:
    """Internal documentation."""
    safe_goal = _redact_secrets(goal or "(no goal)")
    safe_snippets = [_redact_secrets(s) for s in code_snippets]

    fm_lines = [
        "---",
        f"name: {name}",
        "capabilities: []",
        "enabled: false",
        f"source_run: {source_run_id}",
        "---",
        "",
        f"# {name}",
        "",
        f"**Goal**: {safe_goal}",
        "",
        "## What worked",
        "",
        t("learn.distiller.what_worked_intro"),
        "",
    ]
    body = "\n".join(fm_lines)
    if safe_snippets:
        body += "### Key code\n\n"
        body += _format_code_block(safe_snippets) + "\n\n"
    if verify_cmd:
        body += "## Verify (re-runnable)\n\n"
        body += f"```bash\n{verify_cmd}\n```\n\n"
        body += t("learn.distiller.verify_footer")
    return body


def _read_jsonl_relaxed(path: Path) -> list[dict]:
    """Internal documentation."""
    out: list[dict] = []
    if not path.exists():
        return out
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return out
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out


def _events_from_store(store: Any, run_id: str) -> list[dict]:
    """Internal documentation."""
    try:
        if hasattr(store, "replay"):
            return list(store.replay(run_id))
    except Exception:  # noqa: BLE001
        pass
    runs_dir = getattr(store, "runs_dir", None) or getattr(store, "_runs_dir", None)
    if runs_dir is not None:
        p = Path(runs_dir) / f"{run_id}.jsonl"
        return _read_jsonl_relaxed(p)
    return []


def distill_run_to_skill(
    *,
    run_id: str,
    store: Any,
    goal: str,
    verify_cmd: str | None,
    skills_root: Path,
) -> SkillCandidate | None:
    """Internal documentation."""
    events = _events_from_store(store, run_id)
    if not events:
        return None

    snippets: list[str] = []
    verdict_status: str | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float | None = None
    steps: int = 0
    for ev in events:
        if not isinstance(ev, dict):
            continue
        kind = ev.get("kind")
        if kind == "code_action":
            code = ev.get("code")
            if isinstance(code, str) and code.strip():
                snippets.append(code.strip())
        elif kind == "verify_verdict":
            verdict = ev.get("verdict") or {}
            if isinstance(verdict, dict):
                verdict_status = verdict.get("status") or verdict_status
        elif kind == "cost_update":
            # Keep last-seen cumulative cost; cost_usd may be None (unknown price)
            ti = ev.get("tokens_in")
            to = ev.get("tokens_out")
            cu = ev.get("cost_usd")
            if isinstance(ti, int):
                tokens_in = ti
            if isinstance(to, int):
                tokens_out = to
            if cu is not None:
                cost_usd = float(cu)
        elif kind == "phase_change":
            # actions count at last phase_change (typically highest at verify phase)
            ac = ev.get("actions")
            if isinstance(ac, int):
                steps = ac

    if not snippets:
        return None

    name = _slugify_goal(goal, fallback=f"learned-{run_id[:8]}")
    body = _build_markdown(
        name=name, goal=goal, verify_cmd=verify_cmd,
        code_snippets=snippets, source_run_id=run_id,
    )
    skill_md_path = skills_root / name / "SKILL.md"
    return SkillCandidate(
        name=name, body_markdown=body,
        verify_cmd=verify_cmd, skill_md_path=skill_md_path,
        verdict_status=verdict_status,
        tokens_in=tokens_in, tokens_out=tokens_out,
        cost_usd=cost_usd, steps=steps,
    )
