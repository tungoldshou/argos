"""CLI entrypoint for eval runs stored under ARGOS_CONFIG_DIR/eval."""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any

from argos.eval.corpus import corpus_version, list_tasks, load_task
from argos.eval.compare import run_pair, write_report, write_report_json
from argos.eval.results import list_runs, summary
from argos.eval.runner import EvalRunner, PASS_PASSED
from argos.daemon.worktree import WorktreeManager
from argos.i18n import t


class _ManagedEvalLoop:
    """Close eval components after the loop finishes."""

    def __init__(self, components, loop) -> None:
        self._components = components
        self._loop = loop

    async def run(self, goal: str, session_id: str = ""):
        try:
            async for ev in self._loop.run(goal, session_id):
                yield ev
        finally:
            self._components.close()


def _format_run(r) -> str:
    cost = f"${r.cost_usd:.4f}" if r.cost_usd is not None else "$N/A"
    date = time.strftime("%Y-%m-%d", time.localtime(r.finished_at))
    return (f"{r.run_id}  {date}  {r.task_id:<32}  {r.model_tier:<10}  "
            f"{r.pass_status:<14}  {cost}  {r.duration_s:.0f}s")


def _real_loop_factory(model_tier: str, wt_path: str, verify_cmd: str | None = None):
    """Build a real AgentLoop caged to the eval worktree."""
    from argos.app_factory import build_components, build_loop_factory
    from argos.approval import ApprovalLevel

    components = build_components(
        workspace=wt_path,
        model_override=model_tier,
        verify_cmd=verify_cmd,
        approval_level=ApprovalLevel.ACCEPT_EDITS,
    )
    gate = components.gate
    gate.set_ask_listener(lambda call_id, _payload: gate.respond(call_id, "deny"))
    return _ManagedEvalLoop(components, build_loop_factory(components)(verify_cmd))


def _make_runner(*, base: Path, keep_worktree: bool = False) -> EvalRunner:
    wm = WorktreeManager(base_dir=base / "worktrees")
    return EvalRunner(
        worktree=wm,
        base_dir=base,
        keep_worktree=keep_worktree,
        loop_factory=_real_loop_factory,
    )


def _eval_base() -> Path:
    from argos import config

    return Path(config.get("ARGOS_CONFIG_DIR") or (Path.home() / ".argos")).expanduser() / "eval"


# ── subcommand handlers ──────────────────────────────────────────────


def cmd_list(args: argparse.Namespace) -> int:
    runs = list_runs(limit=args.limit)
    if not runs:
        print(t("cli.eval.no_runs"))
        return 0
    header = (f"{'Run ID':<14} {'Date':<11} {'Task':<32} {'Tier':<10} "
              f"{'Status':<14} {'Cost':<10} {'Time':<5}")
    print(header)
    print("-" * len(header))
    for r in runs:
        print(_format_run(r))
    s = summary()
    if s:
        print("\nPass rate (last 7d):")
        for model, cats in s.items():
            print(f"  {model}:")
            for cat, stats in cats.items():
                rate = stats["pass_rate"] * 100
                print(f"    {cat:<14} {stats['passed']}/{stats['total']} ({rate:.0f}%)")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    try:
        task = load_task(args.task_id)
    except FileNotFoundError as e:
        print(t("cli.eval.task_not_found", err=e), file=sys.stderr)
        return 2
    base = _eval_base()
    model = args.model or _active_profile()
    print(f"[eval] task={task.id} category={task.category} difficulty={task.difficulty}")
    print(f"[eval] running model={model} budget=${args.budget:.2f} {args.budget_s}s ...")
    runner = _make_runner(base=base, keep_worktree=args.keep_worktree)
    runner._budget_cost_usd = args.budget
    runner._budget_s = args.budget_s
    result = runner.run(task, model_tier=model)
    from argos.eval.results import append as append_result
    append_result(result, base=base)
    cost = f"${result.cost_usd:.4f}" if result.cost_usd is not None else "$N/A"
    print(f"[eval] {result.pass_status}  cost={cost}  duration={result.duration_s:.0f}s  "
          f"steps={result.steps}  run_id={result.run_id}")
    if result.error:
        print(f"[eval] error: {result.error}", file=sys.stderr)
    return 0 if result.pass_status == PASS_PASSED else 1


def cmd_compare(args: argparse.Namespace) -> int:
    try:
        task = load_task(args.task_id)
    except FileNotFoundError as e:
        print(t("cli.eval.task_not_found", err=e), file=sys.stderr)
        return 2
    base = _eval_base()
    print(f"[eval] A/B: {args.model_a} vs {args.model_b} on {task.id} ...")
    runner = _make_runner(base=base, keep_worktree=args.keep_worktree)
    runner._budget_cost_usd = args.budget
    runner._budget_s = args.budget_s
    a, b = run_pair(runner, task, model_a=args.model_a, model_b=args.model_b)
    md_p = write_report(a, b, base=base)
    json_p = write_report_json(a, b, base=base)
    cost_a = f"${a.cost_usd:.4f}" if a.cost_usd is not None else "$N/A"
    cost_b = f"${b.cost_usd:.4f}" if b.cost_usd is not None else "$N/A"
    print(f"[eval]   {args.model_a:<10}  {a.pass_status}  {cost_a}  {a.duration_s:.0f}s")
    print(f"[eval]   {args.model_b:<10}  {b.pass_status}  {cost_b}  {b.duration_s:.0f}s")
    print(f"[eval] report: {md_p}")
    print(f"[eval] json:   {json_p}")
    return 0


def cmd_corpus(args: argparse.Namespace) -> int:
    tasks = list_tasks()
    v = corpus_version()
    print(f"corpus version {v} ({len(tasks)} tasks)")
    by_cat: dict[str, list] = {}
    for t in tasks:
        by_cat.setdefault(t.category, []).append(t)
    for cat, items in by_cat.items():
        print(f"  {cat} ({len(items)}):")
        for t in items:
            print(f"    {t.id:<32}  {t.difficulty:<8}  {t.title}")
    return 0


# ── helpers ──────────────────────────────────────────────────────────


def _active_profile() -> str:
    try:
        from argos import config as _cfg
        if _cfg._has_config_file():
            return _cfg.load_config().active
    except Exception:  # noqa: BLE001
        pass
    return "default"


def add_subparser(sub: Any) -> None:
    p = sub.add_parser("eval", help=t("cli.eval.help"))
    p.set_defaults(func=lambda _args, parser=p: (parser.print_help(), 2)[1])
    sp = p.add_subparsers(dest="eval_command")

    p_list = sp.add_parser("list", help=t("cli.eval.list.help"))
    p_list.add_argument("--limit", type=int, default=20)
    p_list.set_defaults(func=cmd_list)

    p_run = sp.add_parser("run", help=t("cli.eval.run.help"))
    p_run.add_argument("task_id", help=t("cli.eval.run.task_id.help"))
    p_run.add_argument("--model", default=None, help=t("cli.eval.run.model.help"))
    p_run.add_argument("--budget", type=float, default=1.0, help="cost cap USD")
    p_run.add_argument("--budget-s", type=int, default=600, help="time cap seconds")
    p_run.add_argument("--keep-worktree", action="store_true", help=t("cli.eval.run.keep_worktree.help"))
    p_run.set_defaults(func=cmd_run)

    p_cmp = sp.add_parser("compare", help=t("cli.eval.compare.help"))
    p_cmp.add_argument("task_id", help="task id")
    p_cmp.add_argument("model_a")
    p_cmp.add_argument("model_b")
    p_cmp.add_argument("--budget", type=float, default=1.0)
    p_cmp.add_argument("--budget-s", type=int, default=600)
    p_cmp.add_argument("--keep-worktree", action="store_true")
    p_cmp.set_defaults(func=cmd_compare)

    p_corpus = sp.add_parser("corpus", help=t("cli.eval.corpus.help"))
    p_corpus.set_defaults(func=cmd_corpus)

    from argos.eval.benchmarks.terminal_bench import add_tb_subparser
    add_tb_subparser(sp)
