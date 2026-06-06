# Agent eval / 用户项目级 A/B — 实施计划

> Road-map #7 / spec `2026-06-07-agent-eval-design.md` 的 TDD 实施计划。
> **9 任务,1 任务 = 1 commit,合计 +40 测试,0 新外部依赖**(stdlib only:asyncio /
> subprocess / json / shutil)。

## 0. 总览

| 任务 | 标题 | 估测 | 关键文件 | 测试文件 |
|---|---|---|---|---|
| T1 | corpus schema + 14 个种子任务 | 25 min | `eval/corpus.py`(新) + `~/.argos/eval/corpus/` 种子(不 git 跟踪,脚本生成) | `test_eval_corpus.py` |
| T2 | Eval runner 核心 `run()` | 50 min | `eval/runner.py`(新) | `test_eval_runner.py` |
| T3 | Worktree 集成 + fallback | 20 min | `eval/runner.py` + `eval/__init__.py` | `test_eval_runner.py` 加测 |
| T4 | Result JSONL 持久化 | 25 min | `eval/runner.py` (append) + `eval/results.py`(新) | `test_eval_results.py` |
| T5 | A/B 对比 + 报告生成器 | 35 min | `eval/compare.py`(新) | `test_eval_compare.py` |
| T6 | `argos eval` CLI 子命令 | 30 min | `__main__.py` 扩 subparser + `cli/eval.py`(新) | `test_eval_cli.py` |
| T7 | TUI `/eval` 命令(列 + 摘要) | 25 min | `tui/commands.py` + `tui/app.py` | `test_eval_tui.py` |
| T8 | TUI `/eval run` + `/eval compare` | 30 min | `tui/app.py` + `tui/commands.py` | `test_eval_tui.py` 加测 |
| T9 | 文档 + CHANGELOG + 验收 + 5 种子真跑铁证 | 30 min | `CHANGELOG.md` + `docs/eval.md` + `README.md` | `test_eval_e2e.py` |

**注**:本期 9 任务(不是 spec §14 写的 10 个),合并 T1+T3 收 1 个 corpus + 1 个 worktree
测试文件。`corpus/` 14 个种子**不** git 跟踪(避免污染仓库 + 用户可改),由 `tests/eval/
seed_corpus.py` 在 conftest / test 启动时按需生成(tmp_path / `ARGOS_EVAL_CORPUS_DIR` env)。

## 1. 任务 T1:corpus schema + 任务解析

### 1.1 目标
- 新文件 `argos_agent/eval/corpus.py`:`load_task(task_id, *, root=None) -> EvalTask` /
  `list_tasks(*, root=None) -> list[EvalTask]` / `corpus_version(root=None) -> int`
- `EvalTask` dataclass(id / category / difficulty / title / goal / verify_cmd /
  setup_cmd / expected_files / working_dir)
- 路径:`root` 缺省 = `~/.argos/eval/corpus/`,可被 `ARGOS_EVAL_CORPUS_DIR` 覆盖
- 14 个种子任务由 `tests/eval/seed_corpus.py` 按需落盘到 `tmp_path`(测试隔离)

### 1.2 实现
```python
# argos_agent/eval/corpus.py
from __future__ import annotations
import os, json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

Category = Literal["bug_fix", "refactor", "test_write", "doc", "self_check"]
Difficulty = Literal["easy", "medium", "hard"]

@dataclass(frozen=True, slots=True)
class EvalTask:
    id: str
    category: Category
    difficulty: Difficulty
    title: str
    goal: str
    verify_cmd: str
    setup_cmd: str | None
    expected_files: tuple[str, ...]
    working_dir: Path
    corpus_version: int

def _corpus_root() -> Path:
    return Path(os.environ.get("ARGOS_EVAL_CORPUS_DIR") or (Path.home() / ".argos" / "eval" / "corpus"))

def corpus_version(*, root: Path | None = None) -> int:
    p = (root or _corpus_root()) / "corpus.json"
    if not p.exists():
        return 0
    return int(json.loads(p.read_text("utf-8")).get("version", 1))

def list_tasks(*, root: Path | None = None) -> list[EvalTask]:
    """读 corpus.json + 各 <id>/ 目录,返 EvalTask 列表(按 id 升序)。"""
    base = root or _corpus_root()
    manifest = base / "corpus.json"
    if not manifest.exists():
        return []
    data = json.loads(manifest.read_text("utf-8"))
    out: list[EvalTask] = []
    for t in data.get("tasks", []):
        out.append(_load_one(t["id"], base=base, version=int(data.get("version", 1))))
    return [t for t in out if t is not None]

def load_task(task_id: str, *, root: Path | None = None) -> EvalTask:
    base = root or _corpus_root()
    version = corpus_version(root=base)
    return _load_one(task_id, base=base, version=version)

def _load_one(task_id: str, *, base: Path, version: int) -> EvalTask:
    """读 <base>/<task_id>/{goal.md,verify_cmd,setup.sh?,difficulty,category,expected_files?,notes.md?}
    任一缺失 → raise FileNotFoundError(spec §10)。"""
    d = base / task_id
    if not d.is_dir():
        raise FileNotFoundError(f"corpus task dir not found: {d}")
    goal = (d / "goal.md").read_text("utf-8").strip()
    verify_cmd = (d / "verify_cmd").read_text("utf-8").strip()
    setup = (d / "setup.sh").read_text("utf-8").strip() if (d / "setup.sh").exists() else None
    diff = (d / "difficulty").read_text("utf-8").strip() or "medium"
    cat = (d / "category").read_text("utf-8").strip() or "bug_fix"
    title = (d / "notes.md").read_text("utf-8").splitlines()[0].lstrip("# ").strip() if (d / "notes.md").exists() else task_id
    exp = tuple((d / "expected_files").read_text("utf-8").splitlines()) if (d / "expected_files").exists() else ()
    return EvalTask(
        id=task_id, category=cat, difficulty=diff, title=title, goal=goal,
        verify_cmd=verify_cmd, setup_cmd=setup, expected_files=exp,
        working_dir=d, corpus_version=version,
    )
```

### 1.3 RED 测试(`tests/test_eval_corpus.py`)
```python
def test_load_task_missing_dir_raises(tmp_path)
def test_load_task_missing_goal_md_raises(tmp_path)
def test_load_task_happy_path(tmp_path)
def test_load_task_with_setup_sh(tmp_path)
def test_list_tasks_returns_all_14_seeds(seed_corpus)
def test_corpus_version_default_is_1(seed_corpus)
def test_corpus_env_var_overrides_root(monkeypatch, tmp_path)
def test_expected_files_parsed_as_tuple(tmp_path)
def test_category_and_difficulty_parsed(tmp_path)
```

### 1.4 验证
```bash
rtk pytest tests/test_eval_corpus.py -v
```
期望 9 全绿

### 1.5 Commit
```
feat(eval): #7 T1 corpus schema + 任务解析 + 14 种子生成 fixture
```

## 2. 任务 T2:Eval runner 核心 `run()`

### 2.1 目标
- 新文件 `argos_agent/eval/runner.py`
- `EvalTask` / `EvalResult` dataclass
- `EvalRunner` 类:接受 `WorktreeManager` / `base_dir` / `budget_s` / `budget_cost_usd`
- `run(task, model_tier) -> EvalResult`:走 worktree + 真 AgentLoop + 真 verify
- 失败模式:setup_failed / error / passed / failed / unverifiable
- **不**依赖真 LLM(单测用 fake model 桩;真 LLM 跑在 e2e + 真测)

### 2.2 实现(节选关键)
```python
# argos_agent/eval/runner.py
@dataclass(frozen=True, slots=True)
class EvalResult:
    task_id: str
    run_id: str
    model_tier: str
    started_at: float
    finished_at: float
    duration_s: float
    pass_status: str      # passed/failed/unverifiable/setup_failed/error
    verify_cmd: str
    verify_detail: str
    tampered: tuple[str, ...]
    tokens_in: int
    tokens_out: int
    cost_usd: float | None
    steps: int
    worktree_path: str
    isolation_fallback: str | None
    error: str | None
    corpus_version: int
    goal: str

class EvalRunner:
    def __init__(self, *, worktree: WorktreeManager, base_dir: Path,
                 budget_s: int = 600, budget_cost_usd: float = 1.0,
                 loop_factory: Callable[[str], Any] | None = None):
        self._worktree = worktree
        self._base = Path(base_dir)
        self._base.mkdir(parents=True, exist_ok=True)
        self._budget_s = budget_s
        self._budget_cost_usd = budget_cost_usd
        self._loop_factory = loop_factory   # 测试桩:可注入 fake model

    def run(self, task: EvalTask, *, model_tier: str) -> EvalResult:
        import time, uuid, subprocess
        run_id = uuid.uuid4().hex[:12]
        started = time.time()
        tokens_in = 0
        tokens_out = 0
        cost_usd: float | None = 0.0
        steps = 0
        tampered: list[str] = []
        wt_path = ""
        fallback = None
        try:
            wt_path = self._worktree.create(run_id=run_id, workspace=str(task.working_dir))
            fallback = "temp" if not (Path(wt_path) / ".git").exists() else None
            # setup
            if task.setup_cmd:
                r = subprocess.run(["bash", "-c", task.setup_cmd], cwd=wt_path, capture_output=True, text=True, timeout=60)
                if r.returncode != 0:
                    return self._result_error(task, run_id, model_tier, started,
                                              "setup_failed", f"setup exit {r.returncode}: {r.stderr[:200]}", wt_path, fallback)
            # loop
            if self._loop_factory is not None:
                loop = self._loop_factory(model_tier)
            else:
                # 真实模式:用 app_factory 装(本期不依赖,单测覆盖 fake 路径)
                raise RuntimeError("loop_factory required (本期 v1 全用 fake;真模式 v1.1)")
            verdict_status, verify_detail, tampered = self._drive(loop, task, wt_path, run_id)
            steps = getattr(loop, "steps", 0)
            tokens_in = getattr(loop, "tokens_in", 0)
            tokens_out = getattr(loop, "tokens_out", 0)
            cost_usd = getattr(loop, "cost_usd", 0.0)
            return self._result_pass(task, run_id, model_tier, started, verdict_status,
                                     verify_detail, tampered, tokens_in, tokens_out, cost_usd,
                                     steps, wt_path, fallback)
        except WorktreeError as e:
            return self._result_error(task, run_id, model_tier, started, "error",
                                      f"worktree_failed: {e}", "", fallback)
        except Exception as e:  # noqa: BLE001
            return self._result_error(task, run_id, model_tier, started, "error",
                                      f"{type(e).__name__}: {e}", wt_path, fallback)
        finally:
            try:
                self._worktree.cleanup(run_id)
            except Exception:  # noqa: BLE001
                pass
```

### 2.3 RED 测试(`tests/test_eval_runner.py`)
```python
# 测试用 fake model loop:返 verdict_status + tokens + cost
def test_run_happy_path_passes(eval_runner_with_fake_model)
def test_run_setup_failure_returns_setup_failed(eval_runner_with_fake_model)
def test_run_loop_crash_returns_error(eval_runner_with_fake_model)
def test_run_worktree_failure_returns_error(eval_runner_with_fake_model)
def test_run_captures_tokens_and_cost(eval_runner_with_fake_model)
def test_run_captures_duration(eval_runner_with_fake_model)
def test_run_pass_status_uses_verifier_not_model(eval_runner_with_fake_model)
def test_run_cleanup_called_on_terminal(eval_runner_with_fake_model)
```

### 2.4 验证
```bash
rtk pytest tests/test_eval_runner.py -v
```

### 2.5 Commit
```
feat(eval): #7 T2 EvalRunner.run() 核心 + EvalResult dataclass + 5 类失败模式
```

## 3. 任务 T3:Worktree 集成

### 3.1 目标
- `EvalRunner` 接 `WorktreeManager`(沿用 `#5b`)
- `isolation_fallback: "temp"` 字段落 EvalResult(workspace 非 git repo 时)
- `keep_worktree` 调试 flag:EvalRunner.run(..., keep_worktree=True) 跳过 cleanup
- 复用 `#5b` `WorktreeManager`,不重新实现 git worktree

### 3.2 实现
- 改 `EvalRunner.run()`:`wt_path = self._worktree.create(...)` + `fallback` 检测
  `Path(wt_path).parent.name` 是否 `temp` 或 `.git` 是否存在
- 改 `EvalRunner.__init__`:`keep_worktree: bool = False` 参数
- `finally` 块:`if not self._keep_worktree: self._worktree.cleanup(run_id)`

### 3.3 RED 测试(加到 `tests/test_eval_runner.py`)
```python
def test_run_uses_worktree_manager(eval_runner_with_fake_model, tmp_path)
def test_run_temp_fallback_records_fallback(eval_runner_with_fake_model, tmp_path)
def test_run_keep_worktree_skips_cleanup(eval_runner_with_fake_model, tmp_path)
def test_run_worktree_path_in_result(eval_runner_with_fake_model)
```

### 3.4 Commit
```
feat(eval): #7 T3 WorktreeManager 集成 + keep_worktree 调试 flag
```

## 4. 任务 T4:Result JSONL 持久化

### 4.1 目标
- 新文件 `argos_agent/eval/results.py`
- `append(result, *, base_dir) -> None`:写 `~/.argos/eval/runs/<date>/<run_id>.jsonl`
- `list_runs(*, base_dir, date=None, limit=50) -> list[EvalResult]`
- `load_run(run_id, *, base_dir) -> EvalResult | None`
- `summary(*, base_dir, since_days=7) -> dict`:pass rate per model per category

### 4.2 实现
```python
# argos_agent/eval/results.py
from __future__ import annotations
import json, time
from dataclasses import asdict
from pathlib import Path
from argos_agent.eval.runner import EvalResult

_RUNS_DIR = Path.home() / ".argos" / "eval" / "runs"
_WRITE_LOCK = threading.Lock()

def _runs_dir(base: Path | None = None) -> Path:
    return base or _RUNS_DIR

def _date_str(ts: float) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(ts))

def append(result: EvalResult, *, base: Path | None = None) -> None:
    d = _runs_dir(base) / _date_str(result.finished_at)
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{result.run_id}.jsonl"
    with _WRITE_LOCK:
        line = json.dumps(asdict(result), ensure_ascii=False, separators=(",", ":")) + "\n"
        with p.open("a", encoding="utf-8") as fh:
            fh.write(line)

def list_runs(*, base: Path | None = None, date: str | None = None,
              limit: int = 50) -> list[EvalResult]:
    out: list[EvalResult] = []
    root = _runs_dir(base)
    if not root.exists():
        return out
    if date:
        dates = [date]
    else:
        dates = sorted([d.name for d in root.iterdir() if d.is_dir()], reverse=True)
    for d in dates:
        day = root / d
        if not day.exists():
            continue
        for p in sorted(day.glob("*.jsonl"), reverse=True):
            for line in p.read_text("utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(EvalResult(**json.loads(line)))
                except (json.JSONDecodeError, TypeError):
                    continue
            if len(out) >= limit:
                return out[:limit]
    return out[:limit]

def load_run(run_id: str, *, base: Path | None = None) -> EvalResult | None:
    """按 run_id 扫所有日期目录,找第一个。"""
    root = _runs_dir(base)
    if not root.exists():
        return None
    for day in sorted(root.iterdir(), reverse=True):
        if not day.is_dir():
            continue
        p = day / f"{run_id}.jsonl"
        if p.exists():
            for line in p.read_text("utf-8").splitlines():
                line = line.strip()
                if line:
                    try:
                        return EvalResult(**json.loads(line))
                    except (json.JSONDecodeError, TypeError):
                        continue
    return None

def summary(*, base: Path | None = None, since_days: int = 7) -> dict:
    """{model_tier: {category: {passed: N, total: M, pass_rate: X}}}。"""
    cutoff = time.time() - since_days * 86400
    runs = [r for r in list_runs(base=base, limit=10000) if r.finished_at >= cutoff]
    out: dict[str, dict[str, dict[str, int | float]]] = {}
    for r in runs:
        m = out.setdefault(r.model_tier, {}).setdefault(r.task_id.rsplit("_", 1)[0],  # 粗分类
                                                       {"passed": 0, "total": 0})
        m["total"] += 1
        if r.pass_status == "passed":
            m["passed"] += 1
    for m in out.values():
        for c in m.values():
            c["pass_rate"] = c["passed"] / c["total"] if c["total"] else 0.0
    return out
```

### 4.3 RED 测试(`tests/test_eval_results.py`)
```python
def test_append_creates_date_dir(tmp_path)
def test_append_writes_single_jsonl_line(tmp_path)
def test_list_runs_returns_in_reverse_date_order(tmp_path)
def test_list_runs_limit_truncates(tmp_path)
def test_load_run_round_trip(tmp_path)
def test_load_run_missing_returns_none(tmp_path)
def test_summary_aggregates_per_model_per_category(tmp_path)
def test_summary_only_includes_past_7_days(tmp_path)
def test_corrupt_jsonl_line_skipped(tmp_path)
```

### 4.4 验证
```bash
rtk pytest tests/test_eval_results.py -v
```

### 4.5 Commit
```
feat(eval): #7 T4 Result JSONL 持久化 + list/load/summary
```

## 5. 任务 T5:A/B 对比 + 报告生成器

### 5.1 目标
- 新文件 `argos_agent/eval/compare.py`
- `run_pair(runner, task, *, model_a, model_b) -> tuple[EvalResult, EvalResult]`:同 task 两遍
- `generate_report(a, b) -> str`:side-by-side markdown 报告
- `write_report(a, b, *, base=None) -> Path`:落 `~/.argos/eval/reports/ab-<task_id>-<date>.md`

### 5.2 实现
```python
# argos_agent/eval/compare.py
from __future__ import annotations
import time
from pathlib import Path
from argos_agent.eval.runner import EvalResult, EvalRunner, EvalTask

def run_pair(runner: EvalRunner, task: EvalTask, *, model_a: str, model_b: str
             ) -> tuple[EvalResult, EvalResult]:
    ra = runner.run(task, model_tier=model_a)
    rb = runner.run(task, model_tier=model_b)
    return ra, rb

def generate_report(a: EvalResult, b: EvalResult) -> str:
    """side-by-side markdown 报告(spec §3 字段)。"""
    cost_a = f"${a.cost_usd:.4f}" if a.cost_usd is not None else "$N/A"
    cost_b = f"${b.cost_usd:.4f}" if b.cost_usd is not None else "$N/A"
    winner_cost = "a" if (a.cost_usd or 0) < (b.cost_usd or 0) else "b"
    winner_pass = "a" if a.pass_status == "passed" and b.pass_status != "passed" else \
                  ("b" if b.pass_status == "passed" and a.pass_status != "passed" else "tie")
    lines = [
        f"# A/B Eval Report: {a.task_id}",
        "",
        f"**Generated**: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())}  ",
        f"**Corpus version**: {a.corpus_version}  ",
        "",
        "| Field | A (model={a.model_tier}) | B (model={b.model_tier}) |",
        "|---|---|---|",
        f"| pass_status | {a.pass_status} | {b.pass_status} |",
        f"| duration_s | {a.duration_s:.1f} | {b.duration_s:.1f} |",
        f"| tokens_in | {a.tokens_in} | {b.tokens_in} |",
        f"| tokens_out | {a.tokens_out} | {b.tokens_out} |",
        f"| cost_usd | {cost_a} | {cost_b} |",
        f"| steps | {a.steps} | {b.steps} |",
        f"| tampered | {','.join(a.tampered) or '—'} | {','.join(b.tampered) or '—'} |",
        f"| worktree_path | {a.worktree_path} | {b.worktree_path} |",
        "",
        f"**Pass winner**: {winner_pass}  ",
        f"**Cost winner**: {winner_cost}  ",
        "",
        f"## Goal",
        "",
        "```",
        a.goal,
        "```",
        "",
        f"## A verify_cmd output",
        "```",
        a.verify_detail,
        "```",
        "",
        f"## B verify_cmd output",
        "```",
        b.verify_detail,
        "```",
        "",
    ]
    return "\n".join(lines)

def write_report(a: EvalResult, b: EvalResult, *, base: Path | None = None) -> Path:
    root = base or (Path.home() / ".argos" / "eval" / "reports")
    root.mkdir(parents=True, exist_ok=True)
    date = time.strftime("%Y-%m-%d", time.localtime(a.finished_at))
    p = root / f"ab-{a.task_id}-{date}.md"
    p.write_text(generate_report(a, b), encoding="utf-8")
    return p
```

### 5.3 RED 测试(`tests/test_eval_compare.py`)
```python
def test_run_pair_runs_both_models(eval_runner_with_fake_model)
def test_generate_report_includes_all_fields(eval_runner_with_fake_model)
def test_generate_report_picks_pass_winner(eval_runner_with_fake_model)
def test_generate_report_picks_cost_winner(eval_runner_with_fake_model)
def test_write_report_creates_file(eval_runner_with_fake_model, tmp_path)
def test_write_report_filename_format(eval_runner_with_fake_model, tmp_path)
def test_generate_report_handles_none_cost(eval_runner_with_fake_model)
```

### 5.4 验证
```bash
rtk pytest tests/test_eval_compare.py -v
```

### 5.5 Commit
```
feat(eval): #7 T5 A/B run_pair + 报告生成器(md) + write_report
```

## 6. 任务 T6:`argos eval` CLI 子命令

### 6.1 目标
- 改 `argos_agent/__main__.py` 加 subparser `eval`
- 新文件 `argos_agent/cli/eval.py`:`cmd_list` / `cmd_run` / `cmd_compare` / `cmd_corpus`
- 用 argparse 子命令,无 click
- `--model <tier>` / `--budget <usd>` / `--budget-s <seconds>` / `--corpus <dir>` flags

### 6.2 实现
```python
# argos_agent/cli/eval.py
from __future__ import annotations
import argparse
from pathlib import Path
from argos_agent.eval.corpus import list_tasks, load_task, corpus_version
from argos_agent.eval.runner import EvalRunner
from argos_agent.eval.results import list_runs, load_run
from argos_agent.eval.compare import run_pair, write_report
from argos_agent.daemon.worktree import WorktreeManager

def _format_run(r) -> str:
    cost = f"${r.cost_usd:.4f}" if r.cost_usd is not None else "$N/A"
    return (f"{r.run_id}  {time.strftime('%Y-%m-%d', time.localtime(r.finished_at))}  "
            f"{r.task_id:<32}  {r.model_tier:<10}  {r.pass_status:<14}  "
            f"{cost}  {r.duration_s:.0f}s")

def cmd_list(args) -> int:
    runs = list_runs(limit=args.limit)
    if not runs:
        print("No eval runs yet.")
        return 0
    print(f"{'Run ID':<14} {'Date':<11} {'Task':<32} {'Tier':<10} {'Status':<14} {'Cost':<10} {'Time':<5}")
    for r in runs:
        print(_format_run(r))
    return 0

def cmd_run(args) -> int:
    task = load_task(args.task_id)
    wm = WorktreeManager(base_dir=Path.home() / ".argos" / "eval" / "worktrees")
    runner = EvalRunner(worktree=wm,
                        base_dir=Path.home() / ".argos" / "eval",
                        budget_s=args.budget_s, budget_cost_usd=args.budget)
    result = runner.run(task, model_tier=args.model)
    print(f"[eval] {result.pass_status}  cost={'${:.4f}'.format(result.cost_usd) if result.cost_usd is not None else '$N/A'}  duration={result.duration_s:.0f}s")
    return 0 if result.pass_status == "passed" else 1

def cmd_compare(args) -> int:
    task = load_task(args.task_id)
    wm = WorktreeManager(base_dir=Path.home() / ".argos" / "eval" / "worktrees")
    runner = EvalRunner(worktree=wm, base_dir=Path.home() / ".argos" / "eval",
                        budget_s=args.budget_s, budget_cost_usd=args.budget)
    a, b = run_pair(runner, task, model_a=args.model_a, model_b=args.model_b)
    p = write_report(a, b)
    print(f"[eval] report: {p}")
    print(f"[eval]   {args.model_a:<10}  {a.pass_status}  ${a.cost_usd:.4f if a.cost_usd else 'N/A'}  {a.duration_s:.0f}s")
    print(f"[eval]   {args.model_b:<10}  {b.pass_status}  ${b.cost_usd:.4f if b.cost_usd else 'N/A'}  {b.duration_s:.0f}s")
    return 0

def cmd_corpus(args) -> int:
    tasks = list_tasks()
    v = corpus_version()
    print(f"corpus version {v} ({len(tasks)} tasks)")
    by_cat: dict[str, list] = {}
    for t in tasks:
        by_cat.setdefault(t.category, []).append(t)
    for cat, items in by_cat.items():
        print(f"  {cat} ({len(items)}):")
        for t in items:
            print(f"    {t.id:<32}  {t.difficulty}")
    return 0

# argos_agent/__main__.py 扩 subparser
sp_eval = sub.add_parser("eval", help="Agent 自我评估 + A/B 对比(#7)")
sp_eval_sp = sp_eval.add_subparsers(dest="eval_command")
sp_eval_sp.add_parser("list", help="列最近 run").set_defaults(func=lambda a: cmd_list(a))
sp_run = sp_eval_sp.add_parser("run", help="跑单个 task")
sp_run.add_argument("task_id")
sp_run.add_argument("--model", default=None, help="model profile name(默认 = active)")
sp_run.add_argument("--budget", type=float, default=1.0, help="cost cap USD")
sp_run.add_argument("--budget-s", type=int, default=600, help="time cap seconds")
sp_run.set_defaults(func=cmd_run)
sp_cmp = sp_eval_sp.add_parser("compare", help="A/B 对比")
sp_cmp.add_argument("task_id")
sp_cmp.add_argument("model_a")
sp_cmp.add_argument("model_b")
sp_cmp.add_argument("--budget", type=float, default=1.0)
sp_cmp.add_argument("--budget-s", type=int, default=600)
sp_cmp.set_defaults(func=cmd_compare)
sp_eval_sp.add_parser("corpus", help="列 corpus 任务").set_defaults(func=cmd_corpus)
```

### 6.3 RED 测试(`tests/test_eval_cli.py`)
```python
def test_eval_list_no_runs_prints_message(capsys, tmp_path, monkeypatch)
def test_eval_list_with_runs_prints_table(capsys, tmp_path, monkeypatch)
def test_eval_run_invokes_runner(capsys, tmp_path, monkeypatch)
def test_eval_run_returns_nonzero_on_failure(capsys, tmp_path, monkeypatch)
def test_eval_compare_writes_report(capsys, tmp_path, monkeypatch)
def test_eval_corpus_prints_task_list(capsys, tmp_path, monkeypatch)
def test_eval_subcommand_registered_in_main(monkeypatch)
def test_eval_run_unknown_task_raises(capsys, tmp_path, monkeypatch)
```

### 6.4 验证
```bash
rtk pytest tests/test_eval_cli.py -v
```

### 6.5 Commit
```
feat(eval): #7 T6 argos eval CLI 子命令(list/run/compare/corpus)
```

## 7. 任务 T7:TUI `/eval` 命令(列 + 摘要)

### 7.1 目标
- `tui/commands.py` `COMMAND_HELP` 加 `eval` 段
- `tui/app.py` `_dispatch_slash` 加 `elif cmd.name == "eval"` → `_eval_cmd(log, arg)`
- `_eval_cmd`:
  - 无参:列最近 20 条 + 摘要(走 `eval.results.list_runs` + `summary()`)
  - 有参:`/eval run <task_id>` / `/eval compare <a> <b>`(走 T8)

### 7.2 实现
```python
# tui/app.py
async def _eval_cmd(self, log, arg):
    from argos_agent.eval.results import list_runs, summary
    if not arg.strip():
        runs = list_runs(limit=20)
        if not runs:
            await log.append_line("尚未跑过 eval。试试 /eval run <task_id>", kind="system")
            return
        lines = ["最近 eval runs(最多 20):",
                 f"  {'Date':<11} {'Task':<32} {'Tier':<10} {'Status':<14} {'Cost':<8} {'Time':<5}"]
        for r in runs:
            cost = f"${r.cost_usd:.4f}" if r.cost_usd is not None else "$N/A"
            lines.append(f"  {time.strftime('%Y-%m-%d', time.localtime(r.finished_at)):<11} "
                         f"{r.task_id:<32} {r.model_tier:<10} {r.pass_status:<14} "
                         f"{cost:<8} {r.duration_s:.0f}s")
        s = summary()
        if s:
            lines.append("\nPass rate (last 7d):")
            for m, cats in s.items():
                lines.append(f"  {m}:")
                for c, stats in cats.items():
                    lines.append(f"    {c}: {stats['passed']}/{stats['total']} ({stats['pass_rate']*100:.0f}%)")
        await log.append_line("\n".join(lines), kind="system")
        return
    # 有参:解析 "run <id>" / "compare <a> <b>"
    parts = arg.split()
    if parts[0] == "run" and len(parts) == 2:
        await self._eval_run_cmd(log, parts[1])
    elif parts[0] == "compare" and len(parts) == 3:
        await self._eval_compare_cmd(log, parts[1], parts[2])
    else:
        await log.append_line("用法:/eval [run <task_id> | compare <a> <b>]", kind="error")
```

### 7.3 RED 测试(`tests/test_eval_tui.py`)
```python
def test_eval_command_no_args_lists_runs(tmp_path)
def test_eval_command_no_runs_prints_message(tmp_path)
def test_eval_command_includes_summary(tmp_path)
def test_eval_command_unknown_subcommand_errors(tmp_path)
def test_eval_command_help_text_in_commands_dict()
```

### 7.4 验证
```bash
rtk pytest tests/test_eval_tui.py -v
```

### 7.5 Commit
```
feat(tui): #7 T7 /eval slash 列最近 + 摘要(7d pass rate)
```

## 8. 任务 T8:TUI `/eval run` + `/eval compare`

### 8.1 目标
- 完善 `_eval_run_cmd` + `_eval_compare_cmd`
- 走 `EvalRunner` + `run_pair`
- transcript 落 markdown 报告(> 200 行截断 + 提示 `cat ~/.argos/eval/reports/`)
- sync 跑(本期不接受后台)

### 8.2 实现
```python
# tui/app.py
async def _eval_run_cmd(self, log, task_id: str):
    from argos_agent.eval.corpus import load_task
    from argos_agent.eval.runner import EvalRunner
    from argos_agent.eval.results import append as append_result
    from argos_agent.daemon.worktree import WorktreeManager
    try:
        task = load_task(task_id)
    except FileNotFoundError as e:
        await log.append_line(f"未找到 task: {e}", kind="error")
        return
    await log.append_line(f"[eval] task={task.id} category={task.category} difficulty={task.difficulty}")
    # 用 config active model(本期不热切换)
    from argos_agent import config as _cfg
    model_tier = _cfg.load_config().active if _cfg._has_config_file() else "default"
    wm = WorktreeManager(base_dir=Path.home() / ".argos" / "eval" / "worktrees")
    runner = EvalRunner(worktree=wm, base_dir=Path.home() / ".argos" / "eval")
    await log.append_line(f"[eval] running model={model_tier} ...")
    result = runner.run(task, model_tier=model_tier)
    append_result(result)
    cost = f"${result.cost_usd:.4f}" if result.cost_usd is not None else "$N/A"
    await log.append_line(
        f"[eval] {result.pass_status}  cost={cost}  duration={result.duration_s:.0f}s  "
        f"steps={result.steps}  run_id={result.run_id}",
        kind="done" if result.pass_status == "passed" else "error",
    )

async def _eval_compare_cmd(self, log, a: str, b: str):
    from argos_agent.eval.corpus import load_task
    from argos_agent.eval.runner import EvalRunner
    from argos_agent.eval.compare import run_pair, write_report
    from argos_agent.daemon.worktree import WorktreeManager
    # 解析 a/b:<id>:<model> 或纯 run_id
    def _parse(spec: str) -> tuple[str | None, str | None]:
        if ":" in spec:
            tid, m = spec.split(":", 1)
            return tid, m
        return None, spec  # 视为 run_id
    ta, ma = _parse(a)
    tb, mb = _parse(b)
    if not (ta and tb and ma and mb):
        await log.append_line("用法:/eval compare <task_id>:<model_a> <task_id>:<model_b>", kind="error")
        return
    task = load_task(ta)
    if task.id != tb:
        await log.append_line(f"task_id 不一致:{ta} vs {tb}", kind="error")
        return
    wm = WorktreeManager(base_dir=Path.home() / ".argos" / "eval" / "worktrees")
    runner = EvalRunner(worktree=wm, base_dir=Path.home() / ".argos" / "eval")
    await log.append_line(f"[eval] A/B: {ma} vs {mb} on {ta} ...")
    ra, rb = run_pair(runner, task, model_a=ma, model_b=mb)
    p = write_report(ra, rb)
    md = p.read_text("utf-8")
    if md.count("\n") > 200:
        await log.append_line(md[:8000] + "\n\n... (truncated, 完整报告看:cat " + str(p) + ")", kind="system")
    else:
        await log.append_line(md, kind="system")
```

### 8.3 RED 测试(加到 `tests/test_eval_tui.py`)
```python
def test_eval_run_unknown_task_errors(tmp_path)
def test_eval_run_happy_path_appends_and_prints(tmp_path, monkeypatch)
def test_eval_compare_requires_colon_separator(tmp_path)
def test_eval_compare_writes_report_and_prints(tmp_path, monkeypatch)
def test_eval_compare_truncates_long_report(tmp_path, monkeypatch)
```

### 8.4 验证
```bash
rtk pytest tests/test_eval_tui.py -v
```

### 8.5 Commit
```
feat(tui): #7 T8 /eval run + /eval compare(sync 跑 + transcript 报告)
```

## 9. 任务 T9:文档 + CHANGELOG + 验收 + 5 种子真跑铁证

### 9.1 目标
- `CHANGELOG.md` `[Unreleased]` 加 1 段(对齐 #5b / #9 风格)
- `docs/eval.md` 用户文档(简明 + 例子,对照 `docs/auto-memory.md` 风格)
- `README.md` 段提"eval 一行跑通,看 A/B 报告"(30 字内)
- 端到端铁证:`tests/test_eval_e2e.py`
  - fake model 跑 2 个 task(cheap + strong 各一遍)
  - `run_pair` 返 2 个 EvalResult
  - 报告生成 + 读 markdown 断言字段在
- 全量 `rtk pytest` 绿;测试数 1320 → 1360(+40)

### 9.2 实现
- 端到端铁证(节选):
```python
# tests/test_eval_e2e.py
def test_e2e_pair_run_compare_against_fake_model(tmp_path, seed_corpus, monkeypatch)
def test_e2e_passing_task_recorded_as_passed(tmp_path, seed_corpus, monkeypatch)
def test_e2e_failing_task_recorded_as_failed(tmp_path, seed_corpus, monkeypatch)
def test_e2e_report_file_created_with_pass_rate(tmp_path, seed_corpus, monkeypatch)
```

### 9.3 验收清单
- [ ] `rtk pytest tests/ -q` 全绿,1320 → 1360+(+40,含 1 e2e)
- [ ] 9 commit 全落本地(不 push remote)
- [ ] `tests/test_eval_corpus.py` / `test_eval_runner.py` / `test_eval_results.py` /
      `test_eval_compare.py` / `test_eval_cli.py` / `test_eval_tui.py` / `test_eval_e2e.py`
      7 个文件全绿
- [ ] `docs/eval.md` 用户文档存在 + CHANGELOG Unreleased 段加好
- [ ] 14 个种子任务落 `~/.argos/eval/corpus/`(test fixture,不 git 跟踪)

### 9.4 Commit
```
docs(eval): #7 T9 文档 + CHANGELOG + 验收铁证 + 7 测试文件
```

## 10. 风险与回退

- T2 `loop_factory` 抽象要稳:测试桩必须能让"fake model"返真 verdict,不能只测 happy path →
  5 类失败模式覆盖全(setup_failed / error / passed / failed / unverifiable)
- T4 `load_run` 扫所有日期可能慢:`run_id` 12 hex 短,扫一遍几百 JSONL 文件 OK(< 1s)
- T6 `__main__.py` 改 subparser 解析时不要破坏现有 `setup` / `self-update` 测试
- T8 `/eval run` 同步跑(用户等 ≤ 5 分钟);若 v1.1 加后台,改走 daemon registry(spec §8.4 不冲突)
- 不在 spec/plan 允许范围外的文件(除 `eval/` 新目录 + `cli/eval.py` 新 + `tui/commands.py` 改
  + `tui/app.py` 扩 dispatch + `__main__.py` 扩 subparser + `tests/test_eval_*.py` 新 +
  `CHANGELOG.md` / `docs/eval.md` / `README.md` 文档)不做任何改动

## 11. 时间线

- 9 任务串行(每任务内部全 TDD 闭环)
- T1 → T2 → T3 串行(corpus → runner → worktree)
- T4 独立,可在 T2 后并行
- T5 等 T2 + T3 都完
- T6 紧跟 T4 + T5
- T7 / T8 紧跟 T6

## 12. 完成判据

- [ ] 9 commit 全推本地(不 push remote)
- [ ] 测试数 1320 → 1360+(+40,含 1 e2e)
- [ ] CHANGELOG Unreleased 含 #7 段
- [ ] `docs/eval.md` 用户文档存在
- [ ] 端到端铁证 1 份(test 输出)
- [ ] 14 个 corpus 种子由测试 fixture 落,不污染 git
- [ ] `argos eval list` 0 runs → "尚未跑过 eval" 友好提示(不假绿)
- [ ] `argos eval run bug_fix_001_off_by_one` 跑通(fake model)→ 落 JSONL + 显结果
- [ ] `argos eval compare bug_fix_001 cheap strong` 跑通 → 写 markdown 报告
