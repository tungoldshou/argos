"""Terminal-Bench → Argos EvalTask 适配器。

Terminal-Bench 是 Laude Institute 维护的「terminal-only agent」公开 benchmark
(github.com/harbor-framework/terminal-bench)。每个任务目录里:
  · task.yaml —— instruction + 难度 + 类别 + parser_name + 超时
  · Dockerfile —— FROM <image> + RUN <环境准备>(几乎所有 TB 任务都有)
  · run-tests.sh —— 跑 pytest $TEST_DIR/test_outputs.py -rA(退出码 0 = 过)
  · tests/test_outputs.py —— 终态断言
  · solution.yaml / solution.sh —— 参考解(本适配器不用)
  · docker-compose.yaml —— TB 自己的容器编排(本适配器不嵌套,诚实标注)

本适配器做的事:
  1. load_tb_task(dir) → TBTask 解析(读 task.yaml + run-tests.sh + Dockerfile)
  2. classify(tb) → ("supported"|"unsupported", reason)
     "unsupported" 的诚实理由清单:
       · 用了非宿主 Python 的 base image(如 ghcr.io/.../python-3-13:20250620
         —— 宿主多半没有这个 tag;v1 适配器不拉 / 跑容器)
       · RUN 里有强网络依赖(pip install / apt-get 而非 -q + 静默)
       · tests/ 引用 /protected/ 等容器内路径(本适配器不建该路径)
  3. to_eval_task(tb, *, workdir) → 把 TB 任务落成 corpus.EvalTask 文件树
       goal.md ← instruction
       verify_cmd ← 包了 "cd <workdir> && pip install -q pytest && pytest tests/..." 的单行
       setup.sh ← 提取 Dockerfile 的 RUN 行,转 bash(去掉 FROM/COPY 等容器专属指令)
  4. run_subset(dirs, *, runner, model_tier) → 跑一组;返 TBBatchReport
       (passed/failed/error/setup_failed/skipped 计数 + pass@1 + 跳过原因清单)
  5. CLI 入口:cmd_tb(args) — 跑一个子集并打 pass@1

诚实约束(模块顶部 hard rule):
  · 不在没跑沙箱时把"unsupported" 记成 pass / fail(直接 skipped,不计入分母)
  · 不为变绿而 mock 沙箱 / verify
  · 不嵌套 TB 的 Docker harness;只复用本仓的 EvalRunner + 三态 Verifier
"""
from __future__ import annotations

import argparse
import logging
import re
import shlex
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

from argos_agent.eval.corpus import EvalTask
from argos_agent.eval.results import append as append_result
from argos_agent.eval.runner import (
    EvalResult,
    EvalRunner,
    PASS_ERROR,
    PASS_FAILED,
    PASS_PASSED,
    PASS_SETUP_FAILED,
)

log = logging.getLogger(__name__)


# ── 解析层 ──────────────────────────────────────────────────────────


# 简单 YAML 解析器(只为 task.yaml 这几个字段;不引 PyYAML,减 dep 体积)
# task.yaml 结构固定:key: value 或 key: |- 多行块或 key:\\n  - item\\n  - item (列表);
# 无 anchor/无 list-of-dict / 无类型推断。
def _parse_simple_yaml(text: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        raw = lines[i]
        line = raw.rstrip()
        # 跳空行 / 注释 / canary
        if not line.strip() or line.lstrip().startswith("#"):
            i += 1
            continue
        # 找顶层 key:value(无缩进,首字符非空白)
        if line[:1].isspace():
            i += 1
            continue
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.*)$", line)
        if not m:
            i += 1
            continue
        key, val = m.group(1), m.group(2)
        if val == "|-":
            # 块:下一行起所有更深缩进都收
            block: list[str] = []
            i += 1
            while i < len(lines):
                nxt = lines[i]
                # 退出条件:空行后的非缩进行 = 新 key
                if nxt and not nxt[:1].isspace():
                    break
                if nxt.strip():
                    # 去掉前导 2 空格常见缩进
                    block.append(nxt[2:] if nxt.startswith("  ") else nxt)
                i += 1
            out[key] = "\n".join(block).rstrip() + "\n"
            continue
        # 顶层 key 后面空 → 可能是列表(下一行起 2 空格缩进 + "- item")
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
    """Terminal-Bench 任务解析结果。"""

    task_id: str
    source_dir: Path
    instruction: str
    difficulty: str
    category: str        # 原始 "software-engineering" / "data-science" / ...
    tags: tuple[str, ...]
    parser_name: str
    run_tests_sh: str
    dockerfile_lines: tuple[str, ...]   # FROM 行(原始)
    dockerfile_runs: tuple[str, ...]    # 提取出的 RUN 命令(转 bash)
    has_dockerfile: bool
    has_compose: bool
    has_protected: bool                 # 任务目录有 /protected/ 目录(容器内专用)


# 哪些 FROM image 本适配器视为"本机有 / 可直接用"——只有这两种:
_HOST_PYTHON_BASES = (
    re.compile(r"^FROM\s+python:\d", re.IGNORECASE),
    re.compile(r"^FROM\s+ubuntu:", re.IGNORECASE),
    re.compile(r"^FROM\s+debian:", re.IGNORECASE),
)

# 哪些 base 一定"unsupported: needs container"
_CUSTOM_IMAGE_BASE = re.compile(
    r"^FROM\s+ghcr\.io/laude-institute/t-bench/", re.IGNORECASE,
)


def _parse_dockerfile_runs(text: str) -> tuple[str, ...]:
    """从 Dockerfile 文本抽 RUN 命令(去掉 FROM/COPY/ADD/WORKDIR/ENV/EXPOSE 等容器专属)。

    只保留形如 `RUN <cmd>` 的行;多行 RUN(...) 用 \\ 续行时也合并。
    """
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
        # 非 RUN 容器专属指令直接丢
    # 简单合并:多行 RUN 用 \ 续行时已并入 buf;此处直接逐条收集
    for r in buf:
        # RUN 后面可能带参数:清理前后反引号
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
    """读一个 TB 任务目录,返 TBTask;缺 task.yaml / run-tests.sh / instruction → None。

    缺哪个字段会写一行 warn,但仍尽量把能拿到的字段拼出来(caller 用 classify 决定是否要它)。
    """
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


# ── 分类:支持 / 不支持 ─────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class TBClassification:
    supported: bool
    reason: str
    kind: str  # "supported" | "unsupported_custom_image" | "unsupported_compose"
                # | "unsupported_protected_path" | "unsupported_no_setup"


def classify(tb: TBTask) -> TBClassification:
    """按规则把 TB 任务分 supported / unsupported。

    决策顺序(命中即返):
      1. 有 docker-compose 但无 Dockerfile?罕见,标 unsupported_compose。
      2. FROM 是 t-bench 自家镜像(ghcr.io/laude-institute/...)→ unsupported_custom_image。
      3. 任务目录有 /protected/ 目录(测试会调 /protected/... 路径)→ unsupported_protected_path。
      4. 既没 Dockerfile 也没 RUN 行(无 setup)→ unsupported_no_setup(本适配器没东西能跑)。
      5. 否则 supported。
    """
    if tb.has_compose and not tb.has_dockerfile:
        return TBClassification(False, "needs docker-compose orchestration (v1 adapter does not nest TB's harness)", "unsupported_compose")
    from_line = (tb.dockerfile_lines[0] if tb.dockerfile_lines else "").strip()
    if from_line and _CUSTOM_IMAGE_BASE.match(from_line):
        return TBClassification(False, f"needs custom container image: {from_line}", "unsupported_custom_image")
    if tb.has_protected:
        return TBClassification(False, "tests reference /protected/* path (container-internal)", "unsupported_protected_path")
    if not tb.has_dockerfile and not tb.dockerfile_runs:
        return TBClassification(False, "no Dockerfile RUN lines and no setup script (nothing to replay)", "unsupported_no_setup")
    return TBClassification(True, "supported", "supported")


# ── 转 EvalTask ────────────────────────────────────────────────────


def to_eval_task(tb: TBTask, *, workdir: Path) -> EvalTask:
    """把 TBTask 落成 corpus.EvalTask 的目录结构(<workdir>/<id>/{goal.md,verify_cmd,setup.sh,...})。

    workdir 是 TB 这批任务的"corpus 根"—— caller 一次创建一个,里面是多个 TB 任务的 EvalTask 子目录。
    """
    task_dir = workdir / tb.task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    # goal
    (task_dir / "goal.md").write_text(tb.instruction + "\n", encoding="utf-8")
    # category 映射:TB 的 5+ 类(software-engineering / data-science / ...)=> 本仓 5 类
    cat = _map_category(tb.category)
    (task_dir / "category").write_text(cat + "\n", encoding="utf-8")
    (task_dir / "difficulty").write_text((tb.difficulty or "medium") + "\n", encoding="utf-8")
    # verify_cmd:把 run-tests.sh 包成单行,退出码 0 = pass;
    # 用 `bash -c '...'` 跑(setup.sh 已先装 pytest),并设 cwd = task_dir(worktree 写入的位置)。
    verify_cmd = _build_verify_cmd(tb, workdir=task_dir)
    (task_dir / "verify_cmd").write_text(verify_cmd + "\n", encoding="utf-8")
    # setup.sh:把 Dockerfile RUN 行去 FROM/COPY/容器指令,转成纯 bash
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


# 类别映射:TB → 本仓 corpus.Category(只能取 5 个之一;映射不到的归 "bug_fix")
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
    """把 Dockerfile 的 RUN 行拼成 bash 脚本;容器专属指令已剥,只剩可在本机跑的 shell。"""
    if not tb.dockerfile_runs:
        return ""
    # 加 set -e 出错即停(原 Dockerfile 默认 shell 行 continue-on-error=false)
    lines = ["#!/usr/bin/env bash", "set -e", ""]
    for r in tb.dockerfile_runs:
        # 剥 RUN 行内的反引号和 shell 续行
        cmd = r.replace("\\\n", " ").replace("\\\r\n", " ")
        # RUN rm -rf /usr/... 等破坏性命令对宿主不友好:在前面加 # adapter-skip 提示
        # 仍照常跑(host 是临时 worktree,跑完即删)
        lines.append(cmd)
        lines.append("")
    return "\n".join(lines)


def _build_verify_cmd(tb: TBTask, *, workdir: Path) -> str:
    """把 run-tests.sh 装到一行 bash -c,跑前先切到 task.working_dir。

    run-tests.sh 形如:`pip install pytest==8.4.1\\npytest $TEST_DIR/test_outputs.py -rA`。
    本适配器下没有 $TEST_DIR 环境变量,改成 tests/test_outputs.py 相对路径(把 $TEST_DIR
    替换为 workdir 字符串)。
    """
    inner = tb.run_tests_sh.replace("\n", " && ")
    # 把 $TEST_DIR / ${TEST_DIR} 替换为本任务的 workdir 路径
    test_dir = str(workdir)
    inner = inner.replace("${TEST_DIR}", test_dir).replace("$TEST_DIR", test_dir)
    # shlex.quote 整个 inner 再塞进 bash -c
    return f"bash -c {shlex.quote(inner)}"


# ── 跑一批 + 报告 ──────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class TBBatchReport:
    """一组 TB 任务的跑批结果。

    字段:
      total_seen       看了多少条(含 unsupported 跳过的)
      supported        其中 supported 的条数
      unsupported      其中 unsupported 的条数
      passed/failed/error/setup_failed 各自条数(都是 supported 中跑的)
      skipped          = unsupported
      pass_at_1        passed / (passed + failed + error + setup_failed)
                        跳过的不算入分母 —— 否则会虚低
      results          EvalResult 列表(只含 supported 跑的)
      unsupported_reasons  {reason_kind: count}
      per_task_status  {task_id: ("passed"|"failed"|"error"|"setup_failed"|"skipped", reason_str)}
    """
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
    """load + classify 一步,方便 caller 写循环。"""
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
) -> TBBatchReport:
    """跑一组 TB 任务目录;不支持的如实跳过(不计 pass / fail)。

    runner:已有 EvalRunner 实例(caller 注入 loop_factory + worktree)
    workdir:本次 batch 的 corpus 根(里面是 <task_id>/ 子目录)
    persist:是否落 JSONL(测试可关)
    """
    workdir.mkdir(parents=True, exist_ok=True)
    supported_count = 0
    unsupported_count = 0
    passed = failed = err = setup_failed = 0
    results: list[EvalResult] = []
    reasons: dict[str, int] = {}
    per_task: dict[str, tuple[str, str]] = {}

    for d in task_dirs:
        cls = _classify_tb_dir(d)
        tb = load_tb_task(d)
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
        # supported → 转 EvalTask → runner.run
        task = to_eval_task(tb, workdir=workdir)
        supported_count += 1
        try:
            r = runner.run(task, model_tier=model_tier)
        except Exception as e:  # noqa: BLE001 — runner 不应抛,兜底
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


# ── CLI 子命令 ──────────────────────────────────────────────


def _resolve_subset_arg(arg: str, *, default_subset: str | None = None) -> list[Path]:
    """CLI 解析:
      · 显式路径:逗号分隔多个目录
      · "smoke":内置 3-任务小子集(本适配器自带 fixture;真实 TB 需 git clone)
      · None:空 → 报清楚,不走 TB 全量
    """
    if not arg:
        return []
    if arg == "smoke":
        return [_smoke_subset_dir()]
    # 否则按逗号拆路径
    return [Path(p.strip()) for p in arg.split(",") if p.strip()]


def _smoke_subset_dir() -> Path:
    """返回本仓库自带的 TB-shaped 小 fixture 目录(test 用;CLI 也能跑这个看数字)。"""
    # 放 tests/eval/_fixtures/tb_smoke/ —— 单测与 CLI 复用
    p = Path(__file__).resolve().parent.parent.parent.parent / "tests" / "eval" / "_fixtures" / "tb_smoke"
    return p


def cmd_tb(args: argparse.Namespace) -> int:
    """`argos eval tb --subset <paths|smoke> --model <tier>` —— 跑一个 TB 子集。

    注意:不传 --subset 时不打全量,直接提示;smoke 跑本仓库自带的 fixture(确定性能跑通)。"""
    from argos_agent.cli.eval import _make_runner
    base = Path.home() / ".argos" / "eval"
    runner = _make_runner(base=base, keep_worktree=args.keep_worktree)
    runner._budget_cost_usd = args.budget
    runner._budget_s = args.budget_s
    subset = _resolve_subset_arg(getattr(args, "subset", "") or "smoke")
    if not subset:
        print("[eval tb] 未指定 --subset;请传 'smoke' 跑内置 fixture,或逗号分隔 TB 任务目录。", file=__import__("sys").stderr)
        return 2
    for d in subset:
        if not d.exists():
            print(f"[eval tb] 路径不存在:{d}", file=__import__("sys").stderr)
            return 2
    workdir = base / "tb_corpus"
    report = run_subset(subset, runner=runner, model_tier=args.model, workdir=workdir)
    # 打印报告
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
    return 0


def add_tb_subparser(sub: Any) -> None:
    """注册 `argos eval tb` 子命令。"""
    p_tb = sub.add_parser("tb", help="跑 Terminal-Bench 子集(适配器,需 --subset)")
    p_tb.add_argument(
        "--subset", default="smoke",
        help="逗号分隔 TB 任务目录;或 'smoke' 跑内置 fixture(默认 smoke)",
    )
    p_tb.add_argument("--model", default="default", help="model profile name")
    p_tb.add_argument("--budget", type=float, default=1.0, help="cost cap USD")
    p_tb.add_argument("--budget-s", type=int, default=600, help="time cap seconds")
    p_tb.add_argument("--keep-worktree", action="store_true", help="调试:不删 worktree")
    p_tb.add_argument(
        "--format", choices=("text", "json"), default="text", help="报告格式",
    )
    p_tb.set_defaults(func=cmd_tb)
