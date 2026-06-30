"""#7 T2/T3 EvalRunner:接 task + model_tier + budget,跑 worktree + 真 loop + 真 verify。

不依赖真 LLM(测试用 fake_loop 桩,真 LLM 跑在 e2e + 真测)。

数据流(spec §5.3):
  1. WorktreeManager.create()   → 隔离 workspace
  2. setup.sh (optional)        → 准备环境
  3. loop_factory(model_tier)   → 装 AgentLoop
  4. loop.run(goal)             → CodeAct 跑,产 cost_update 事件
  5. Verifier.verify(verify_cmd)→ 退出码 0 = passed
  6. EvalResult.append_jsonl
  7. WorktreeManager.cleanup()  → finally 块,失败也清

D7:budget 超时 → cancel + 标 failed
D12:verify_cmd 走 host(不嵌套 sandbox,eval 是 dogfooding)
D16:keep_worktree=True 跳过 cleanup(调试用)
D20:报告存 ~/.argos/eval/ 同用户态数据
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import inspect
import logging
import os
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from argos.eval.corpus import EvalTask
from argos.i18n import t

log = logging.getLogger(__name__)

# Pass status 5 类(spec §5.4 + §9.1)
PASS_PASSED = "passed"
PASS_FAILED = "failed"
PASS_UNVERIFIABLE = "unverifiable"
PASS_SETUP_FAILED = "setup_failed"
PASS_ERROR = "error"


@dataclass(frozen=True, slots=True)
class EvalResult:
    """单次 eval 跑结果(spec §5.1)。

    pass_status 推导图(§9.1):
      setup.sh 失败       → setup_failed
      LLM/crash/IO 异常   → error
      verify 退出 0       → passed
      verify 退出非 0     → failed
      verify 超时         → failed
      篡改检测触发        → unverifiable
    """
    task_id: str
    run_id: str
    model_tier: str
    started_at: float
    finished_at: float
    duration_s: float
    pass_status: str
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

    def to_json(self) -> str:
        import json
        d = {
            "task_id": self.task_id, "run_id": self.run_id,
            "model_tier": self.model_tier,
            "started_at": self.started_at, "finished_at": self.finished_at,
            "duration_s": self.duration_s, "pass_status": self.pass_status,
            "verify_cmd": self.verify_cmd, "verify_detail": self.verify_detail,
            "tampered": list(self.tampered),
            "tokens_in": self.tokens_in, "tokens_out": self.tokens_out,
            "cost_usd": self.cost_usd, "steps": self.steps,
            "worktree_path": self.worktree_path, "isolation_fallback": self.isolation_fallback,
            "error": self.error, "corpus_version": self.corpus_version,
            "goal": self.goal,
        }
        return json.dumps(d, ensure_ascii=False, separators=(",", ":"))

    @classmethod
    def from_json(cls, s: str) -> "EvalResult":
        import json
        d = json.loads(s)
        return cls(
            task_id=d["task_id"], run_id=d["run_id"], model_tier=d["model_tier"],
            started_at=float(d["started_at"]), finished_at=float(d["finished_at"]),
            duration_s=float(d["duration_s"]), pass_status=d["pass_status"],
            verify_cmd=d["verify_cmd"], verify_detail=d.get("verify_detail", ""),
            tampered=tuple(d.get("tampered") or []),
            tokens_in=int(d.get("tokens_in", 0)), tokens_out=int(d.get("tokens_out", 0)),
            cost_usd=d.get("cost_usd"), steps=int(d.get("steps", 0)),
            worktree_path=d.get("worktree_path", ""),
            isolation_fallback=d.get("isolation_fallback"),
            error=d.get("error"), corpus_version=int(d.get("corpus_version", 1)),
            goal=d.get("goal", ""),
        )


# Loop factory contract(测试桩可注入):
#   loop = loop_factory(model_tier: str)
#   loop.run_sync(goal: str, workspace: Path) -> LoopOutcome
#   loop.steps / loop.tokens_in / loop.tokens_out / loop.cost_usd
#
# Or:loop is a "fake" object exposing the same attributes for unit tests.

@dataclass
class LoopOutcome:
    """loop.run() 的简版结果(测试桩用)。"""
    verdict_status: str           # passed/failed/unverifiable
    verify_detail: str = ""
    tampered: tuple[str, ...] = field(default_factory=tuple)
    steps: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float | None = 0.0


class WorktreeError_(Exception):
    """worktree 失败的占位异常(避免引 daemon.worktree 在单测里循环导入)。"""
    pass


# loop_factory 协议类型
LoopFactory = Callable[[str], Any]


class EvalRunner:
    """Eval 跑主控(spec §5)。

    - worktree:从 #5b 注入(测试可换 fake)
    - base_dir:~/.argos/eval/(可 env var 覆盖 ARGOS_EVAL_DIR,测试用)
    - budget_s / budget_cost_usd:D3 默认 $1 / 600s
    - loop_factory:测试桩;真模式 v1.1 接 app_factory.build_loop_factory
    - keep_worktree:调试 flag,D16
    """

    def __init__(
        self,
        *,
        worktree: Any,  # WorktreeManager 实例(避免硬引);protocol duck-typed
        base_dir: Path,
        budget_s: int | None = 600,
        budget_cost_usd: float | None = 1.0,
        loop_factory: LoopFactory | None = None,
        keep_worktree: bool = False,
    ):
        self._worktree = worktree
        self._base = Path(base_dir)
        self._base.mkdir(parents=True, exist_ok=True)
        self._budget_s = budget_s
        self._budget_cost_usd = budget_cost_usd
        self._loop_factory = loop_factory
        self._keep_worktree = keep_worktree

    @property
    def base_dir(self) -> Path:
        return self._base

    @property
    def budget_s(self) -> int | None:
        return self._budget_s

    @property
    def budget_cost_usd(self) -> float | None:
        return self._budget_cost_usd

    def run(self, task: EvalTask, *, model_tier: str) -> EvalResult:
        """跑单个 task。失败模式见 §5.4;最终返 EvalResult(必返,不抛)。"""
        run_id = uuid.uuid4().hex[:12]
        started = time.time()
        wt_path = ""
        fallback: str | None = None
        # 1. worktree
        try:
            wt_path = self._worktree.create(run_id=run_id, workspace=str(task.working_dir))
        except Exception as e:  # noqa: BLE001 — worktree 失败兜底成 error
            return self._mk_error(task, run_id, model_tier, started, "",
                                  f"worktree_failed: {e}", None)
        # finally 兜底:任何路径结束都尝试 cleanup(spec D16 keep_worktree=True 跳过)
        try:
            return self._do_run(task, run_id, model_tier, started, wt_path, fallback)
        finally:
            if not self._keep_worktree:
                try:
                    self._worktree.cleanup(run_id)
                except Exception as e:  # noqa: BLE001
                    log.warning("worktree cleanup failed for %s: %s", run_id, e)

    def _do_run(
        self, task: EvalTask, run_id: str, model_tier: str, started: float,
        wt_path: str, fallback: str | None,
    ) -> EvalResult:
        # fallback 判定(worktree 内部若是 git worktree → 无 fallback;temp dir → "temp")
        try:
            is_git = bool(getattr(self._worktree, "is_git_repo", lambda _: True)(str(task.working_dir)))
        except Exception:  # noqa: BLE001
            is_git = True
        fallback: str | None = None if is_git else "temp"
        # 2. setup
        if task.setup_cmd:
            try:
                r = subprocess.run(
                    ["bash", "-c", task.setup_cmd],
                    cwd=wt_path, capture_output=True, text=True, timeout=60,
                )
                if r.returncode != 0:
                    return self._mk_pass(
                        task, run_id, model_tier, started,
                        PASS_SETUP_FAILED,
                        f"setup exit {r.returncode}: {(r.stderr or r.stdout)[:200]}",
                        (), 0, 0, 0.0, 0, wt_path, fallback,
                    )
            except subprocess.TimeoutExpired:
                return self._mk_pass(
                    task, run_id, model_tier, started,
                    PASS_SETUP_FAILED, "setup_timeout", (), 0, 0, 0.0, 0, wt_path, fallback,
                )
            except Exception as e:  # noqa: BLE001
                return self._mk_pass(
                    task, run_id, model_tier, started,
                    PASS_SETUP_FAILED, f"setup_error: {type(e).__name__}: {e}",
                    (), 0, 0, 0.0, 0, wt_path, fallback,
                )
        # 3. loop factory
        if self._loop_factory is None:
            return self._mk_error(
                task, run_id, model_tier, started, wt_path,
                t("eval.runner.loop_factory_required"), fallback,
            )
        try:
            loop = self._loop_factory(model_tier)
        except Exception as e:  # noqa: BLE001
            return self._mk_error(task, run_id, model_tier, started, wt_path,
                                  f"loop_factory_failed: {type(e).__name__}: {e}", fallback)
        # 4. drive loop
        try:
            outcome = self._drive(loop, task, wt_path)
        except Exception as e:  # noqa: BLE001
            return self._mk_error(task, run_id, model_tier, started, wt_path,
                                  f"loop_crashed: {type(e).__name__}: {e}", fallback)
        # 5. result
        return self._mk_pass(
            task, run_id, model_tier, started,
            outcome.verdict_status, outcome.verify_detail, outcome.tampered,
            outcome.tokens_in, outcome.tokens_out, outcome.cost_usd,
            outcome.steps, wt_path, fallback,
        )

    # ── 内部 ────────────────────────────────────────────────────────────
    def _drive(self, loop: Any, task: EvalTask, wt_path: str) -> LoopOutcome:
        """跑 loop → 拿 LoopOutcome。

        loop 协议(单测桩必备):
          loop.run_sync(goal, workspace) -> LoopOutcome | raises

        Budget 强制(--budget 真实执行):
          - budget_s:挂线程计时器,超时 → timed_out
          - budget_cost_usd:跑完后检查 outcome.cost_usd,超限 → over_budget
        """
        # 桩模式:loop.run_sync 直接返 LoopOutcome
        if hasattr(loop, "run_sync"):
            # ponytail: thread timer for sync wall-clock timeout; asyncio.wait_for
            # won't help here since _drive is sync. Upgrade to async when real
            # AgentLoop streaming is wired in.
            timer: threading.Timer | None = None
            timed_out: threading.Event | None = None
            if self._budget_s is not None:
                timed_out = threading.Event()
                def _flag_timeout():
                    timed_out.set()
                timer = threading.Timer(self._budget_s, _flag_timeout)
                timer.daemon = True
                timer.start()
            try:
                outcome = loop.run_sync(task.goal, Path(wt_path))
            finally:
                if timer is not None:
                    timer.cancel()

            if self._budget_s is not None and timed_out.is_set():
                return LoopOutcome(
                    verdict_status=PASS_FAILED,
                    verify_detail=f"timed_out: exceeded {self._budget_s}s wall-clock budget",
                    steps=outcome.steps,
                    tokens_in=outcome.tokens_in,
                    tokens_out=outcome.tokens_out,
                    cost_usd=outcome.cost_usd,
                )

            if not isinstance(outcome, LoopOutcome):
                # 兜底:把任意对象转成 LoopOutcome
                outcome = LoopOutcome(
                    verdict_status=getattr(outcome, "verdict_status", "error"),
                    verify_detail=getattr(outcome, "verify_detail", ""),
                    tampered=tuple(getattr(outcome, "tampered", ())),
                    steps=int(getattr(outcome, "steps", 0)),
                    tokens_in=int(getattr(outcome, "tokens_in", 0)),
                    tokens_out=int(getattr(outcome, "tokens_out", 0)),
                    cost_usd=getattr(outcome, "cost_usd", 0.0),
                )

            # cost budget check (post-run; real streaming accumulation deferred to v1.1)
            if (
                self._budget_cost_usd is not None
                and outcome.cost_usd is not None
                and outcome.cost_usd > self._budget_cost_usd
            ):
                return LoopOutcome(
                    verdict_status=PASS_FAILED,
                    verify_detail=(
                        f"over_budget: cost ${outcome.cost_usd:.6f} exceeded"
                        f" ${self._budget_cost_usd:.6f} limit"
                    ),
                    steps=outcome.steps,
                    tokens_in=outcome.tokens_in,
                    tokens_out=outcome.tokens_out,
                    cost_usd=outcome.cost_usd,
                )

            return outcome

        # v1.1 real-loop adapter: loop has async def run (coroutine or async generator)
        _run_fn = getattr(type(loop), "run", None) or getattr(loop, "run", None)
        if hasattr(loop, "run") and _run_fn is not None and (
            inspect.iscoroutinefunction(_run_fn)
            or inspect.isasyncgenfunction(_run_fn)
        ):
            return self._drive_real_loop(loop, task, wt_path)

        return LoopOutcome(
            verdict_status=PASS_ERROR,
            verify_detail="loop has no run_sync or async run method",
        )

    def _drive_real_loop(self, loop: Any, task: "EvalTask", wt_path: str) -> LoopOutcome:
        """Drive a real AgentLoop (async def run) to completion, collecting events.

        Async/sync bridge mirrors argos/verify/self_test.py:reviewer_llm_proposer —
        run asyncio.run() in a fresh thread so this sync method works whether or not
        a running event loop exists on the caller's thread (no nested-loop crash).

        Workspace caging: the eval worktree wt_path is passed as session_id context;
        the loop itself must be constructed by a factory that sets workspace=wt_path
        (see worker.py _eval_loop_factory and build_run_stack). We do NOT re-cage
        here — we trust the factory, and document the requirement.
        """
        run_id = uuid.uuid4().hex[:8]
        session_id = f"eval-{run_id}"

        async def _collect() -> LoopOutcome:
            from argos.protocol.events import VerifyVerdict, CostUpdate, PhaseChange, CodeAction

            verdict_status = PASS_UNVERIFIABLE  # honest default: no verdict = unverifiable
            verify_detail = ""
            tokens_in = 0
            tokens_out = 0
            cost_usd: float | None = None
            steps = 0
            code_action_count = 0

            async for ev in loop.run(task.goal, session_id=session_id):
                if isinstance(ev, VerifyVerdict):
                    # Take the LAST verdict seen (loop may emit multiple)
                    verdict_status = ev.verdict.status
                    verify_detail = getattr(ev.verdict, "verify_detail", "") or ""
                elif isinstance(ev, CostUpdate):
                    tokens_in = ev.tokens_in
                    tokens_out = ev.tokens_out
                    cost_usd = ev.cost_usd
                elif isinstance(ev, PhaseChange):
                    steps = ev.actions
                elif isinstance(ev, CodeAction):
                    code_action_count += 1

            # Fallback steps: if PhaseChange never fired, use CodeAction count
            if steps == 0 and code_action_count:
                steps = code_action_count

            return LoopOutcome(
                verdict_status=verdict_status,
                verify_detail=verify_detail,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                cost_usd=cost_usd,
                steps=steps,
            )

        # Budget: wall-clock timer in a thread (same pattern as run_sync path above).
        timed_out: threading.Event | None = None
        timer: threading.Timer | None = None
        if self._budget_s is not None:
            timed_out = threading.Event()
            timer = threading.Timer(self._budget_s, timed_out.set)
            timer.daemon = True
            timer.start()

        # Async/sync bridge: run in a fresh thread with its own event loop so we
        # never nest event loops, whether called from sync or async context.
        # ponytail: one-thread executor, same pattern as self_test.reviewer_llm_proposer
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                fut = pool.submit(asyncio.run, _collect())
                timeout = float(self._budget_s) if self._budget_s is not None else None
                try:
                    outcome = fut.result(timeout=timeout)
                except concurrent.futures.TimeoutError:
                    fut.cancel()
                    if timer is not None:
                        timer.cancel()
                    return LoopOutcome(
                        verdict_status=PASS_FAILED,
                        verify_detail=f"timed_out: exceeded {self._budget_s}s wall-clock budget",
                    )
        finally:
            if timer is not None:
                timer.cancel()

        if timed_out is not None and timed_out.is_set():
            return LoopOutcome(
                verdict_status=PASS_FAILED,
                verify_detail=f"timed_out: exceeded {self._budget_s}s wall-clock budget",
                steps=outcome.steps,
                tokens_in=outcome.tokens_in,
                tokens_out=outcome.tokens_out,
                cost_usd=outcome.cost_usd,
            )

        # Cost budget check (mirrors run_sync path)
        if (
            self._budget_cost_usd is not None
            and outcome.cost_usd is not None
            and outcome.cost_usd > self._budget_cost_usd
        ):
            return LoopOutcome(
                verdict_status=PASS_FAILED,
                verify_detail=(
                    f"over_budget: cost ${outcome.cost_usd:.6f} exceeded"
                    f" ${self._budget_cost_usd:.6f} limit"
                ),
                steps=outcome.steps,
                tokens_in=outcome.tokens_in,
                tokens_out=outcome.tokens_out,
                cost_usd=outcome.cost_usd,
            )

        return outcome

    def _mk_error(
        self, task, run_id, model_tier, started, wt_path, error_msg, fallback,
    ) -> EvalResult:
        finished = time.time()
        return EvalResult(
            task_id=task.id, run_id=run_id, model_tier=model_tier,
            started_at=started, finished_at=finished,
            duration_s=finished - started, pass_status=PASS_ERROR,
            verify_cmd=task.verify_cmd, verify_detail="", tampered=(),
            tokens_in=0, tokens_out=0, cost_usd=0.0, steps=0,
            worktree_path=wt_path, isolation_fallback=fallback,
            error=error_msg, corpus_version=task.corpus_version, goal=task.goal,
        )

    def _mk_pass(
        self, task, run_id, model_tier, started, status, detail,
        tampered, tokens_in, tokens_out, cost_usd, steps, wt_path, fallback,
    ) -> EvalResult:
        finished = time.time()
        return EvalResult(
            task_id=task.id, run_id=run_id, model_tier=model_tier,
            started_at=started, finished_at=finished,
            duration_s=finished - started, pass_status=status,
            verify_cmd=task.verify_cmd, verify_detail=detail, tampered=tampered,
            tokens_in=tokens_in, tokens_out=tokens_out, cost_usd=cost_usd,
            steps=steps, worktree_path=wt_path, isolation_fallback=fallback,
            error=None, corpus_version=task.corpus_version, goal=task.goal,
        )

    def cleanup_worktree(self, run_id: str) -> None:
        """手动清理(keep_worktree 模式下 caller 用)。"""
        try:
            self._worktree.cleanup(run_id)
        except Exception as e:  # noqa: BLE001
            log.warning("worktree cleanup failed for %s: %s", run_id, e)
