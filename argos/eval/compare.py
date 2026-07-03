from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from argos import config
from argos.eval.corpus import EvalTask
from argos.eval.results import append as append_result
from argos.eval.runner import EvalResult, EvalRunner, PASS_PASSED

_REPORTS_DIR: Path | None = None


def _reports_dir(base: Path | None = None) -> Path:
    if base is not None:
        return base / "reports"
    if _REPORTS_DIR is not None:
        return _REPORTS_DIR
    return Path(
        config.get("ARGOS_CONFIG_DIR") or (Path.home() / ".argos")
    ).expanduser() / "eval" / "reports"


def run_pair(
    runner: EvalRunner, task: EvalTask, *, model_a: str, model_b: str,
    persist: bool = True,
) -> tuple[EvalResult, EvalResult]:
    a = runner.run(task, model_tier=model_a)
    b = runner.run(task, model_tier=model_b)
    if persist:
        append_result(a, base=runner.base_dir)
        append_result(b, base=runner.base_dir)
    return a, b


def _fmt_cost(cost: float | None) -> str:
    if cost is None:
        return "$N/A"
    return f"${cost:.4f}"


def _winner_pass(a: EvalResult, b: EvalResult) -> str:
    a_pass = a.pass_status == PASS_PASSED
    b_pass = b.pass_status == PASS_PASSED
    if a_pass and not b_pass:
        return "a"
    if b_pass and not a_pass:
        return "b"
    return "tie"


def _winner_cost(a: EvalResult, b: EvalResult) -> str:
    if a.cost_usd is None and b.cost_usd is None:
        return "unknown"
    if a.cost_usd is None:
        return "b"
    if b.cost_usd is None:
        return "a"
    if a.cost_usd < b.cost_usd:
        return "a"
    if b.cost_usd < a.cost_usd:
        return "b"
    return "tie"


def generate_report(a: EvalResult, b: EvalResult) -> str:
    winner_pass = _winner_pass(a, b)
    winner_cost = _winner_cost(a, b)
    lines: list[str] = [
        f"# A/B Eval Report: {a.task_id}",
        "",
        f"**Generated**: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())}  ",
        f"**Corpus version**: {a.corpus_version}  ",
        "",
        f"| Field | A (model={a.model_tier}) | B (model={b.model_tier}) |",
        "|---|---|---|",
        f"| pass_status | {a.pass_status} | {b.pass_status} |",
        f"| duration_s | {a.duration_s:.1f} | {b.duration_s:.1f} |",
        f"| tokens_in | {a.tokens_in} | {b.tokens_in} |",
        f"| tokens_out | {a.tokens_out} | {b.tokens_out} |",
        f"| cost_usd | {_fmt_cost(a.cost_usd)} | {_fmt_cost(b.cost_usd)} |",
        f"| steps | {a.steps} | {b.steps} |",
        f"| tampered | {','.join(a.tampered) or '—'} | {','.join(b.tampered) or '—'} |",
        f"| worktree | `{a.worktree_path or '—'}` | `{b.worktree_path or '—'}` |",
        "",
        f"**Pass winner**: `{winner_pass}`  ",
        f"**Cost winner**: `{winner_cost}`  ",
        "",
        "## Goal",
        "",
        "```",
        a.goal,
        "```",
        "",
        f"## A verify_cmd output (status={a.pass_status})",
        "",
        "```",
        (a.verify_detail or a.error or "(no detail)"),
        "```",
        "",
        f"## B verify_cmd output (status={b.pass_status})",
        "",
        "```",
        (b.verify_detail or b.error or "(no detail)"),
        "```",
        "",
    ]
    return "\n".join(lines)


def write_report(
    a: EvalResult, b: EvalResult, *, base: Path | None = None,
) -> Path:
    root = _reports_dir(base)
    root.mkdir(parents=True, exist_ok=True)
    date = time.strftime("%Y-%m-%d", time.localtime(a.finished_at))
    p = root / f"ab-{a.task_id}-{date}.md"
    p.write_text(generate_report(a, b), encoding="utf-8")
    return p


def write_report_json(
    a: EvalResult, b: EvalResult, *, base: Path | None = None,
) -> Path:
    root = _reports_dir(base)
    root.mkdir(parents=True, exist_ok=True)
    date = time.strftime("%Y-%m-%d", time.localtime(a.finished_at))
    p = root / f"ab-{a.task_id}-{date}.json"
    payload: dict[str, Any] = {
        "task_id": a.task_id,
        "corpus_version": a.corpus_version,
        "a": json.loads(a.to_json()),
        "b": json.loads(b.to_json()),
        "winner_pass": _winner_pass(a, b),
        "winner_cost": _winner_cost(a, b),
    }
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return p
