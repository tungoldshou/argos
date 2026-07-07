from __future__ import annotations

import argparse
import json
import logging
import re
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

from argos.eval.corpus import EvalTask
from argos.i18n import t
from argos.eval.results import append as append_result
from argos.eval.runner import (
    EvalResult,
    EvalRunner,
    PASS_ERROR,
    PASS_FAILED,
    PASS_PASSED,
    PASS_SETUP_FAILED,
)

log = logging.getLogger(__name__)




def _parse_simple_yaml(text: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        raw = lines[i]
        line = raw.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            i += 1
            continue
        if line[:1].isspace():
            i += 1
            continue
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.*)$", line)
        if not m:
            i += 1
            continue
        key, val = m.group(1), m.group(2)
        if val == "|-":
            block: list[str] = []
            i += 1
            while i < len(lines):
                nxt = lines[i]
                if nxt and not nxt[:1].isspace():
                    break
                if nxt.strip():
                    block.append(nxt[2:] if nxt.startswith("  ") else nxt)
                i += 1
            out[key] = "\n".join(block).rstrip() + "\n"
            continue
        if val == "":
            items: list[str] = []
            i += 1
            while i < len(lines):
                nxt = lines[i]
                if not nxt[:2] == "  ":
                    break
                stripped = nxt.strip()
                if stripped.startswith("- "):
                    items.append(stripped[2:].strip())
                i += 1
            if items:
                out[key] = items
            continue
        out[key] = val.strip().strip('"').strip("'")
        i += 1
    return out


@dataclass(frozen=True, slots=True)
class TBTask:

    task_id: str
    source_dir: Path
    instruction: str
    difficulty: str
    category: str
    tags: tuple[str, ...]
    parser_name: str
    run_tests_sh: str
    dockerfile_lines: tuple[str, ...]
    dockerfile_runs: tuple[str, ...]
    has_dockerfile: bool
    has_compose: bool
    has_protected: bool


_HOST_PYTHON_BASES = (
    re.compile(r"^FROM\s+python:\d", re.IGNORECASE),
    re.compile(r"^FROM\s+ubuntu:", re.IGNORECASE),
    re.compile(r"^FROM\s+debian:", re.IGNORECASE),
)

_CUSTOM_IMAGE_BASE = re.compile(
    r"^FROM\s+ghcr\.io/laude-institute/t-bench/", re.IGNORECASE,
)


def _parse_dockerfile_runs(text: str) -> tuple[str, ...]:
    runs: list[str] = []
    buf: list[str] = []
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        if line.startswith("RUN "):
            buf.append(line[4:].strip())
        elif line.startswith("RUN\\") or line.startswith("RUN "):
            buf.append(line[4:].strip())
        elif buf and line.endswith("\\"):
            buf[-1] = buf[-1] + " " + line.rstrip("\\").strip()
    for r in buf:
        r = r.strip()
        if r:
            runs.append(r)
    return tuple(runs)


def _dockerfile_from_line(text: str) -> str:
    for line in text.splitlines():
        if line.strip().upper().startswith("FROM "):
            return line.strip()
    return ""


def load_tb_task(task_dir: str | Path) -> TBTask | None:
    d = Path(task_dir)
    if not d.is_dir():
        return None
    task_yaml = d / "task.yaml"
    run_tests = d / "run-tests.sh"
    if not task_yaml.is_file() or not run_tests.is_file():
        return None
    try:
        meta = _parse_simple_yaml(task_yaml.read_text(encoding="utf-8"))
    except OSError:
        return None
    instr = (meta.get("instruction") or "").strip()
    if not instr:
        return None
    run_tests_text = run_tests.read_text(encoding="utf-8").strip()
    dockerfile_p = d / "Dockerfile"
    dockerfile_text = dockerfile_p.read_text(encoding="utf-8") if dockerfile_p.is_file() else ""
    runs = _parse_dockerfile_runs(dockerfile_text) if dockerfile_text else ()
    from_line = _dockerfile_from_line(dockerfile_text) if dockerfile_text else ""
    tags_raw = meta.get("tags", "")
    if isinstance(tags_raw, list):
        tags = tuple(str(t).strip() for t in tags_raw if str(t).strip())
    elif isinstance(tags_raw, str):
        tags = tuple(t.strip() for t in tags_raw.split(",") if t.strip())
    else:
        tags = ()
    return TBTask(
        task_id=d.name,
        source_dir=d,
        instruction=instr,
        difficulty=(meta.get("difficulty") or "medium").lower(),
        category=meta.get("category") or "software-engineering",
        tags=tags,
        parser_name=meta.get("parser_name") or "pytest",
        run_tests_sh=run_tests_text,
        dockerfile_lines=(from_line,) if from_line else (),
        dockerfile_runs=runs,
        has_dockerfile=dockerfile_p.is_file(),
        has_compose=(d / "docker-compose.yaml").is_file(),
        has_protected=(d / "protected").is_dir(),
    )




@dataclass(frozen=True, slots=True)
class TBClassification:
    supported: bool
    reason: str
    kind: str  # "supported" | "unsupported_custom_image" | "unsupported_compose"
                # | "unsupported_protected_path" | "unsupported_no_setup"


def classify(tb: TBTask, *, docker_available: bool | None = None) -> TBClassification:
    if tb.has_compose and not tb.has_dockerfile:
        return TBClassification(False, "needs docker-compose orchestration (v1 adapter does not nest TB's harness)", "unsupported_compose")
    from_line = (tb.dockerfile_lines[0] if tb.dockerfile_lines else "").strip()
    if from_line and _CUSTOM_IMAGE_BASE.match(from_line):
        ok = _docker_ok() if docker_available is None else docker_available
        if ok:
            return TBClassification(True, "supported (in docker)", "supported_in_docker")
        return TBClassification(
            False,
            f"needs custom container image: {from_line} (docker not available in this env)",
            "unsupported_custom_image_no_docker",
        )
    if tb.has_protected:
        return TBClassification(False, "tests reference /protected/* path (container-internal)", "unsupported_protected_path")
    if not tb.has_dockerfile and not tb.dockerfile_runs:
        return TBClassification(False, "no Dockerfile RUN lines and no setup script (nothing to replay)", "unsupported_no_setup")
    return TBClassification(True, "supported", "supported")


def _docker_ok() -> bool:
    import shutil
    import subprocess
    if shutil.which("docker") is None:
        return False
    try:
        r = subprocess.run(
            ["docker", "info"], capture_output=True, text=True, timeout=5,
        )
        return r.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False




def to_eval_task(tb: TBTask, *, workdir: Path) -> EvalTask:
    import shutil

    task_dir = workdir / tb.task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    # goal
    (task_dir / "goal.md").write_text(tb.instruction + "\n", encoding="utf-8")
    cat = _map_category(tb.category)
    (task_dir / "category").write_text(cat + "\n", encoding="utf-8")
    (task_dir / "difficulty").write_text((tb.difficulty or "medium") + "\n", encoding="utf-8")
    src_tests = tb.source_dir / "tests"
    if src_tests.is_dir():
        dst_tests = task_dir / "tests"
        if dst_tests.exists():
            shutil.rmtree(dst_tests, ignore_errors=True)
        shutil.copytree(src_tests, dst_tests)
    verify_cmd = _build_verify_cmd(tb, workdir=task_dir)
    (task_dir / "verify_cmd").write_text(verify_cmd + "\n", encoding="utf-8")
    setup_text = _build_setup_script(tb)
    if setup_text:
        (task_dir / "setup.sh").write_text(setup_text, encoding="utf-8")
    # title
    title = tb.instruction.splitlines()[0][:80] if tb.instruction else tb.task_id
    return EvalTask(
        id=tb.task_id,
        category=cat,
        difficulty=tb.difficulty or "medium",
        title=title,
        goal=tb.instruction,
        verify_cmd=verify_cmd,
        setup_cmd=setup_text or None,
        expected_files=(),
        working_dir=task_dir,
        corpus_version=1,
    )


_CAT_MAP = {
    "software-engineering": "bug_fix",
    "system-administration": "bug_fix",
    "data-science": "refactor",
    "machine-learning": "refactor",
    "security": "bug_fix",
    "devops": "bug_fix",
    "database": "bug_fix",
    "web": "refactor",
    "debugging": "bug_fix",
    "troubleshooting": "bug_fix",
}


def _map_category(tb_category: str) -> str:
    return _CAT_MAP.get((tb_category or "").lower(), "bug_fix")


def _build_setup_script(tb: TBTask) -> str:
    if not tb.dockerfile_runs:
        return ""
    lines = ["#!/usr/bin/env bash", "set -e", ""]
    for r in tb.dockerfile_runs:
        cmd = r.replace("\\\n", " ").replace("\\\r\n", " ")
        lines.append(cmd)
        lines.append("")
    return "\n".join(lines)


def _build_docker_verify_cmd(tb: TBTask, *, workdir: Path) -> str:
    from .terminal_bench_docker import TBContainerExecutor

    py_inner = (
        "import sys;"
        "from argos.eval.benchmarks.terminal_bench_docker import TBContainerExecutor;"
        "from argos import runtime;"
        "ctx = runtime.current();"
        "worktree = str(ctx.verify_dir);"
        f" source_dir = {repr(str(tb.source_dir))};"
        " import os;"
        " os.environ.setdefault('ARGOS_TB_DOCKER_NETWORK', '1');"
        " from pathlib import Path;"
        f" src = Path(source_dir);"
        f" wt = Path(worktree);"
        " from argos.eval.benchmarks.terminal_bench import load_tb_task;"
        f" tb = load_tb_task(src);"
        " exec_ = TBContainerExecutor(timeout=600);  # 240s can time out while installing packages; see terminal_bench_docker._DEFAULT_VERIFY_TIMEOUT"
        " rc = exec_.verify_in_container(tb, task_dir=wt);"
        " sys.exit(0 if rc.exit_code == 0 else (2 if rc.setup_failed else 1))"
    )
    return f"python -c {shlex.quote(py_inner)}"


def _build_verify_cmd(tb: TBTask, *, workdir: Path) -> str:
    inner = tb.run_tests_sh.replace("\n", " && ")
    test_dir = str(workdir)
    inner = inner.replace("${TEST_DIR}", test_dir).replace("$TEST_DIR", test_dir)
    py_inner = (
        "import subprocess, sys;"
        " sys.exit(subprocess.call(['bash', '-c', sys.argv[1]]))"
    )
    return f"python -c {shlex.quote(py_inner)} bash -c {shlex.quote(inner)}"




@dataclass(frozen=True, slots=True)
class TBBatchReport:
    total_seen: int
    supported: int
    unsupported: int
    passed: int
    failed: int
    error: int
    setup_failed: int
    skipped: int
    pass_at_1: float
    results: tuple[EvalResult, ...]
    unsupported_reasons: Mapping[str, int]
    per_task_status: Mapping[str, tuple[str, str]]


def _classify_tb_dir(task_dir: str | Path) -> TBClassification:
    tb = load_tb_task(task_dir)
    if tb is None:
        return TBClassification(False, "task.yaml/instruction/run-tests.sh missing or unparsable", "unsupported_no_setup")
    return classify(tb)


def run_subset(
    task_dirs: Iterable[str | Path],
    *,
    runner: EvalRunner,
    model_tier: str,
    workdir: Path,
    persist: bool = True,
    docker_available: bool | None = None,
) -> TBBatchReport:
    workdir.mkdir(parents=True, exist_ok=True)
    supported_count = 0
    unsupported_count = 0
    passed = failed = err = setup_failed = 0
    results: list[EvalResult] = []
    reasons: dict[str, int] = {}
    per_task: dict[str, tuple[str, str]] = {}

    for d in task_dirs:
        tb_loaded = load_tb_task(d)
        if tb_loaded is None:
            cls = TBClassification(
                False,
                "task.yaml/instruction/run-tests.sh missing or unparsable",
                "unsupported_no_setup",
            )
        else:
            cls = classify(tb_loaded, docker_available=docker_available)
        tb = tb_loaded
        if tb is None:
            unsupported_count += 1
            reasons[cls.kind] = reasons.get(cls.kind, 0) + 1
            per_task[Path(d).name] = ("skipped", cls.reason)
            continue
        if not cls.supported:
            unsupported_count += 1
            reasons[cls.kind] = reasons.get(cls.kind, 0) + 1
            per_task[tb.task_id] = ("skipped", cls.reason)
            log.info("[tb] skip %s — %s", tb.task_id, cls.reason)
            continue
        task = to_eval_task(tb, workdir=workdir)
        supported_count += 1
        try:
            r = runner.run(task, model_tier=model_tier)
        except Exception as e:  # noqa: BLE001
            err += 1
            per_task[tb.task_id] = ("error", f"{type(e).__name__}: {e}")
            log.warning("[tb] runner crashed on %s: %s", tb.task_id, e)
            continue
        if persist:
            append_result(r, base=runner.base_dir)
        results.append(r)
        if r.pass_status == PASS_PASSED:
            passed += 1
            per_task[tb.task_id] = ("passed", r.verify_detail or "")
        elif r.pass_status == PASS_SETUP_FAILED:
            setup_failed += 1
            per_task[tb.task_id] = ("setup_failed", r.verify_detail or "")
        elif r.pass_status == PASS_ERROR:
            err += 1
            per_task[tb.task_id] = ("error", r.error or r.verify_detail or "")
        else:
            failed += 1
            per_task[tb.task_id] = ("failed", r.verify_detail or "")

    denom = passed + failed + err + setup_failed
    pass_at_1 = (passed / denom) if denom else 0.0
    return TBBatchReport(
        total_seen=supported_count + unsupported_count,
        supported=supported_count,
        unsupported=unsupported_count,
        passed=passed, failed=failed, error=err, setup_failed=setup_failed,
        skipped=unsupported_count,
        pass_at_1=pass_at_1,
        results=tuple(results),
        unsupported_reasons=reasons,
        per_task_status=per_task,
    )




def _resolve_subset_arg(arg: str, *, default_subset: str | None = None) -> list[Path]:
    if not arg:
        return []
    if arg == "smoke":
        root = _smoke_subset_dir()
        if not root.exists():
            return [root]
        return sorted(p for p in root.iterdir() if (p / "task.yaml").is_file())
    return [Path(p.strip()) for p in arg.split(",") if p.strip()]


def _smoke_subset_dir() -> Path:
    p = Path(__file__).resolve().parent.parent.parent.parent / "tests" / "eval" / "_fixtures" / "tb_smoke"
    return p


def cmd_tb(args: argparse.Namespace) -> int:
    from argos.cli.eval import _eval_base, _make_runner
    base = _eval_base()
    runner = _make_runner(base=base, keep_worktree=args.keep_worktree)
    runner._budget_cost_usd = args.budget
    runner._budget_s = args.budget_s
    subset = _resolve_subset_arg(getattr(args, "subset", "") or "smoke")
    if not subset:
        print(t("eval.tb.no_subset"), file=sys.stderr)
        return 2
    for d in subset:
        if not d.exists():
            print(t("eval.tb.path_not_found", path=d), file=sys.stderr)
            return 2
    workdir = base / "tb_corpus"
    report = run_subset(subset, runner=runner, model_tier=args.model, workdir=workdir)
    if getattr(args, "format", "text") == "json":
        print(json.dumps({
            "total_seen": report.total_seen,
            "supported": report.supported,
            "unsupported": report.unsupported,
            "passed": report.passed,
            "failed": report.failed,
            "error": report.error,
            "setup_failed": report.setup_failed,
            "skipped": report.skipped,
            "pass_at_1": report.pass_at_1,
            "unsupported_reasons": dict(report.unsupported_reasons),
            "per_task_status": dict(report.per_task_status),
        }, ensure_ascii=False))
        return 0
    _print_tb_report(report)
    return 0


def _print_tb_report(report: TBBatchReport) -> None:
    print(f"[eval tb] seen={report.total_seen}  supported={report.supported}  "
          f"skipped={report.skipped}")
    if report.unsupported_reasons:
        for k, n in report.unsupported_reasons.items():
            print(f"[eval tb]   skip reason: {k} × {n}")
    print(f"[eval tb] passed={report.passed}  failed={report.failed}  "
          f"setup_failed={report.setup_failed}  error={report.error}  "
          f"pass@1={report.pass_at_1 * 100:.1f}%")
    for tid, (status, why) in report.per_task_status.items():
        line = f"  {tid:<48}  {status}"
        if status == "skipped":
            line += f"  — {why}"
        print(line)


def add_tb_subparser(sub: Any) -> None:
    p_tb = sub.add_parser("tb", help=t("eval.tb.cmd_help"))
    p_tb.add_argument(
        "--subset", default="smoke",
        help=t("eval.tb.subset_help"),
    )
    p_tb.add_argument("--model", default="default", help="model profile name")
    p_tb.add_argument("--budget", type=float, default=1.0, help="cost cap USD")
    p_tb.add_argument("--budget-s", type=int, default=600, help="time cap seconds")
    p_tb.add_argument("--keep-worktree", action="store_true", help=t("eval.tb.keep_worktree_help"))
    p_tb.add_argument(
        "--format", choices=("text", "json"), default="text", help=t("eval.tb.format_help"),
    )
    p_tb.set_defaults(func=cmd_tb)
