from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

from argos.i18n import t

log = logging.getLogger(__name__)

_DEFAULT_CANDIDATES_DIR: Path | None = None
_DEFAULT_SKILLS_DIR: Path | None = None


def _argos_dir() -> Path:
    from argos import config

    return Path(config.get("ARGOS_CONFIG_DIR") or (Path.home() / ".argos")).expanduser()


def _dreams_dir() -> Path:
    env = os.environ.get("ARGOS_DREAMS_DIR")
    return Path(env).expanduser() if env else _argos_dir() / "dreams"


def _memory_dir() -> Path:
    env = os.environ.get("ARGOS_MEMORY_DIR")
    return Path(env).expanduser() if env else _argos_dir() / "memory"


def _candidates_root() -> Path:
    from argos.learning.candidates import default_root

    return default_root(_DEFAULT_CANDIDATES_DIR)


def _skills_root() -> Path:
    from argos.skills import user_dir

    return user_dir(_DEFAULT_SKILLS_DIR)


def _latest_report() -> dict | None:
    d = _dreams_dir()
    if not d.exists():
        return None
    files = sorted(d.glob("*.jsonl"))
    if not files:
        return None
    latest = files[-1]
    last_line = None
    try:
        for line in latest.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                last_line = line
    except Exception as e:  # noqa: BLE001
        log.warning("dream CLI: 读报告文件失败: %s", e)
        return None
    if not last_line:
        return None
    try:
        return json.loads(last_line)
    except json.JSONDecodeError as e:  # noqa: BLE001
        log.warning("dream CLI: 报告行 JSON 解析失败: %s", e)
        return None


def _fmt_report(r: dict) -> str:
    return t(
        "cli.dream.report_fmt",
        units_total=r.get("units_total", 0),
        promoted=r.get("promoted", 0),
        rejected=r.get("rejected", 0),
        skipped=r.get("skipped", 0),
        memory_merged=r.get("memory_merged", 0),
        memory_archived=r.get("memory_archived", 0),
    )


def run_dream(args: Any) -> int:
    if getattr(args, "report", False):
        report = _latest_report()
        if report is None:
            print(t("cli.dream.no_report"))
            return 0
        if not isinstance(report, dict):
            print(t("cli.dream.report_bad_type", type_name=type(report).__name__))
            return 0
        print(_fmt_report(report))
        return 0

    has_key = True
    comps = None
    try:
        from argos.app_factory import build_components
        comps = build_components()          # RuntimeError(no key) → memory-only fallback
    except RuntimeError as e:
        if "key" in str(e).lower():
            has_key = False
        else:
            print(t("cli.dream.pipeline_failed", err=e), file=sys.stderr)
            return 1
    except Exception as e:  # noqa: BLE001
        print(t("cli.dream.pipeline_failed", err=e), file=sys.stderr)
        return 1

    if not has_key:
        print(t("cli.dream.no_key_notice"))
        print(t("cli.dream.no_key_setup_hint"))
        mem_dir = _memory_dir()
        try:
            from argos.memory.consolidate import consolidate
            rep = consolidate(mem_dir)
            print(t("cli.dream.memory_tidy", merged=rep.merged, archived=rep.archived))
        except Exception as e:  # noqa: BLE001
            log.warning("dream CLI: 记忆整理失败: %s", e)
            print(t("cli.dream.memory_tidy_failed", err=e))
        try:
            from argos.learning.candidates import list_unconsumed
            cands = list_unconsumed(_candidates_root())
            print(t("cli.dream.candidates_count", n=len(cands)))
        except Exception as e:  # noqa: BLE001
            log.warning("dream CLI: 候选区盘点失败: %s", e)
        return 0

    import asyncio

    dreams_dir = _dreams_dir()
    dreams_dir.mkdir(parents=True, exist_ok=True)
    mem_dir = _memory_dir()
    mem_dir.mkdir(parents=True, exist_ok=True)

    candidates_root = _candidates_root()
    skills_root = _skills_root()

    from argos.app_factory import build_run_stack

    _narrate = None
    if comps is not None:
        try:
            _model = comps.model

            async def _narrate(prompt: str) -> str:
                return await _model.complete(
                    [{"role": "user", "content": prompt}],
                    system="你是知识提炼助手,只输出纯文字摘要,不输出代码。",
                )
        except Exception:  # noqa: BLE001
            _narrate = None

    _runner_factory = None
    if comps is not None:
        try:
            from argos.eval.runner import EvalRunner
            from argos.daemon.worktree import WorktreeManager
            from argos.learning.dream import HintedRunner
            eval_base = dreams_dir / "eval"
            wm = WorktreeManager(base_dir=eval_base / "worktrees")
            run_stack = build_run_stack(comps, workspace=None, session_id="dream-eval")

            def _eval_loop_factory(model_tier: str):
                return run_stack.loop_factory()

            base_runner = EvalRunner(worktree=wm, base_dir=eval_base,
                                     loop_factory=_eval_loop_factory)

            def _runner_factory(hint: str | None):
                return HintedRunner(inner=base_runner, hint=hint) if hint else base_runner
        except Exception:  # noqa: BLE001
            _runner_factory = None

    if _runner_factory is None:
        print(t("cli.dream.no_runner_warning"))
        return 0

    from argos.learning.dream import DreamPipeline

    pipeline = DreamPipeline(
        candidates_root=candidates_root,
        skills_root=skills_root,
        memory_dir=mem_dir,
        dreams_dir=dreams_dir,
        runner_factory=_runner_factory,
        narrate=_narrate,
        broadcast_fn=None,
    )

    print(t("cli.dream.starting"))
    try:
        report = asyncio.run(pipeline.run())
    except Exception as e:  # noqa: BLE001
        print(t("cli.dream.pipeline_failed", err=e), file=__import__("sys").stderr)
        return 1

    if report is None:
        print(t("cli.dream.already_running"))
        return 0

    print(_fmt_report({
        "units_total": report.units_total,
        "promoted": report.promoted,
        "rejected": report.rejected,
        "skipped": report.skipped,
        "memory_merged": report.memory_merged,
        "memory_archived": report.memory_archived,
    }))
    if report.report_path:
        print(t("cli.dream.report_written", path=report.report_path))
    return 0


def add_subparser(sub: Any) -> None:
    p = sub.add_parser(
        "dream",
        help=t("cli.dream.help"),
    )
    p.add_argument(
        "--report",
        action="store_true",
        help=t("cli.dream.report.help"),
    )
    p.set_defaults(func=run_dream)
