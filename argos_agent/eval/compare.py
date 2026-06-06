"""#7 T5 A/B 对比 + 报告生成器(md + json)。

- run_pair(runner, task, *, model_a, model_b) → (EvalResult, EvalResult)
- generate_report(a, b) → str(markdown)
- write_report(a, b, *, base=None) → Path
- write_report_json(a, b, *, base=None) → Path(机读;v1.1 自动分析用)

D14:md(给用户)+ json(给后续自动化)
D15:每 run 独立 worktree,清理独立
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from argos_agent.eval.corpus import EvalTask
from argos_agent.eval.results import append as append_result
from argos_agent.eval.runner import EvalResult, EvalRunner, PASS_PASSED

_REPORTS_DIR = Path.home() / ".argos" / "eval" / "reports"


def _reports_dir(base: Path | None = None) -> Path:
    return (base if base is not None else _REPORTS_DIR.parent) / "reports"


def run_pair(
    runner: EvalRunner, task: EvalTask, *, model_a: str, model_b: str,
    persist: bool = True,
) -> tuple[EvalResult, EvalResult]:
    """同 task,两个 model_tier 各跑一遍(spec §5.5)。

    每遍独立 worktree + 独立 EvalResult(落 2 条 JSONL,写到 runner.base_dir/runs/)。
    persist=False → 不落 JSONL(测试用)。
    """
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
    """cost 小的胜;无 cost 数据 → 'unknown'。"""
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
    """side-by-side markdown 报告(spec §3 / §7.3)。"""
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
    """写 markdown 报告到 ~/.argos/eval/reports/ab-<id>-<date>.md。"""
    root = _reports_dir(base)
    root.mkdir(parents=True, exist_ok=True)
    date = time.strftime("%Y-%m-%d", time.localtime(a.finished_at))
    p = root / f"ab-{a.task_id}-{date}.md"
    p.write_text(generate_report(a, b), encoding="utf-8")
    return p


def write_report_json(
    a: EvalResult, b: EvalResult, *, base: Path | None = None,
) -> Path:
    """写 json 报告(机读;v1.1 自动分析用)。"""
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
