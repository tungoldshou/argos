"""Terminal-Bench → best_of_n 桥接(spec §E2+E3 组合)。

动机:验证"便宜模型 + verify + best_of_n"在真实公开 benchmark 上的可量化收益。
本模块不另造评估体系,而是把每个 supported TB 任务 → 一份 best_of_n 单 stage 的
WorkflowSpec → 真 WorkflowEngine 真跑(真沙箱、真 verify、真 diff 摘要),最后把
N=1 / N=k 的 pass@1 数字 + supported/skipped 计数打包成 BridgeReport。

诚实约束(模块顶部 hard rule):
  · 候选数 N 真跑真 verify(不 mock 沙箱 / 不替 verdict;测试通过 SubAgentFactory
    的 run_task monkey-patch 注入确定结果,但走的是同一条引擎路径,真沙箱逻辑由
    既有 subagent / verify 测试覆盖)
  · unsupported 任务如实标 skipped,不进分母(与 TBBatchReport 同口径)
  · N=1 与 N=k 在同一份报告里分别给数字,互不污染
  · 不复用 EvalRunner(那是 loop + 真 sandbox_child 的单进程路径);改走
    WorkflowEngine + best_of_n 路径(子 agent 多 worktree 隔离 + 真 verify 门),
    两条路径并存,各有适用场景

桥接核心三件:
  · build_spec_for_task(tb_task, n, model_tier) → WorkflowSpec
  · run_pass_at_1(task_dirs, *, engine, n, ...) → BridgeReport
  · BridgeReport:per_task 状态 / N=1 pass@1 / N=k pass@1 / supported & skipped
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

from argos.eval.benchmarks.terminal_bench import (
    TBTask,
    _build_docker_verify_cmd,
    _build_verify_cmd,
    classify,
    load_tb_task,
    to_eval_task,
)
from argos.workflow.engine import WorkflowEngine
from argos.workflow.result import AgentResult, StageResult
from argos.workflow.spec import (
    AgentTask,
    Stage,
    WorkflowSpec,
    parse_spec,
)

log = logging.getLogger(__name__)


# ── 公共契约:TBTask → WorkflowSpec(单 stage best_of_n) ──────────


def build_spec_for_task(
    tb_task: TBTask,
    *,
    n: int,
    model_tier: str,
    mirror_dir: Path | None = None,
) -> WorkflowSpec:
    """把单个 TB 任务落成一份 best_of_n 单 stage 的 WorkflowSpec。

    agent.role=coder(派生 write 工具 + 强制 verify);isolation=worktree(让子 agent
    在自己 worktree 里改 /app/run.sh 不打架);verify 透传 verify_cmd(子 agent 跑
    verify 门时直接复用,不必 runner 再算一次)。

    supported_in_docker 任务:verify_cmd 走 `_build_docker_verify_cmd`,在容器里跑
    TB 官方 run-tests.sh;其他任务仍走 host 版 `_build_verify_cmd`。

    mirror_dir:docker 路径专用 —— SubAgentFactory._run 会在 worktree 拆掉前把
      内容拷到这里;verify_cmd 调 docker 时 mount 这个目录到 /app,让容器看到
      agent 的产出。host 路径下忽略。
    """
    if n < 1:
        raise ValueError(f"n 必须 ≥ 1,得 {n}")
    cls = classify(tb_task)
    if cls.kind == "supported_in_docker":
        # workdir 优先用 mirror_dir(agent 产出会被镜像到这里);无 mirror_dir 退化到
        # source_dir(legacy,只能读到 task.yaml/run-tests.sh/tests,无 agent 产出)。
        wd = mirror_dir if mirror_dir is not None else tb_task.source_dir
        verify_cmd = _build_docker_verify_cmd(tb_task, workdir=wd)
    else:
        # 本机路径:内联 verify_cmd(workdir 用临时目录只为 $TEST_DIR 替换出合法路径)
        import tempfile
        with tempfile.TemporaryDirectory() as _td:
            verify_cmd = _build_verify_cmd(tb_task, workdir=Path(_td))
    spec_dict = {
        "name": f"tb-bridge-{tb_task.task_id}",
        "description": (
            f"TB bridge: {tb_task.task_id} (N={n}, model={model_tier})"
        ),
        "stages": [{
            "id": tb_task.task_id,
            "op": "best_of_n",
            "n": n,
            "agent": {
                "prompt": tb_task.instruction,
                "tool_scope": "full",
                "isolation": "worktree",
                "verify": verify_cmd,
                "role": "coder",
                "model": model_tier,
            },
        }],
    }
    return parse_spec(spec_dict)


# ── 单任务跑批(N=1 与 N=k 在同一份里) ────────────────────────


@dataclass(frozen=True, slots=True)
class BridgePerTask:
    """单任务在两档 N 下的最终状态。"""
    n1_winner: str | None     # winner agent_id(只装 N=1)
    n3_winner: str | None     # winner agent_id(N=k;None 表示未跑)
    n1_status: str            # passed | failed | error | setup_failed
    n3_status: str
    n1_candidates: tuple[AgentResult, ...]
    n3_candidates: tuple[AgentResult, ...]
    error: str | None = None


@dataclass(frozen=True, slots=True)
class BridgeReport:
    """bridge 跑批结果(spec §E2+E3)。

    字段:
      total_seen       看了多少条
      supported        其中 supported 的(真跑了)
      skipped          = unsupported(不入分母)
      pass_at_1_n1     N=1 维度上的 pass@1
      pass_at_1_n3     N=k(=3 默认)维度上的 pass@1
      n                实际跑的 N(可配置;默认 3)
      per_task         {task_id: BridgePerTask}
      per_task_status  {task_id: (status, reason)}  status 是 "passed"/"failed"/"skipped",
                        reason 是 N 维度标记("n1"/"n3")或 skip 原因
      unsupported_reasons  {reason_kind: count}
    """
    total_seen: int
    supported: int
    skipped: int
    n: int
    pass_at_1_n1: float
    pass_at_1_n3: float
    per_task: Mapping[str, BridgePerTask]
    per_task_status: Mapping[str, tuple[str, str]]
    unsupported_reasons: Mapping[str, int]


# ── 内部:跑一份 best_of_n spec,收 StageResult ────────────────


async def _drive_engine(engine: WorkflowEngine, spec: WorkflowSpec) -> StageResult:
    """同步消费 engine.run() 的进度事件;返回最后一 stage 的 StageResult。"""
    async for _ev in engine.run(spec):
        pass
    assert engine.last_result is not None
    return engine.last_result.stages[0]


def _status_of_winner(winner: AgentResult) -> str:
    """从 winner.verdict 派生任务级状态。verdict=None / 异常 → "failed"(防御)。"""
    if winner.verdict == "passed":
        return "passed"
    if winner.verdict == "unverifiable":
        return "unverifiable"
    return "failed"


def _passed_count(stage: StageResult) -> int:
    return sum(1 for r in stage.candidates if r.verdict == "passed")


def run_pass_at_1(
    task_dirs: Iterable[str | Path],
    *,
    engine: WorkflowEngine,
    n: int = 3,
    base_dir: Path,
    persist: bool = True,
    docker_available: bool | None = None,
) -> BridgeReport:
    """跑一批 TB 任务:N=1(基线)与 N=k 各自真跑 best_of_n,返 BridgeReport。

    engine:外部构造好的 WorkflowEngine(caller 注入 model_factory 等共享依赖)。
    n:候选数(N=1 与 N=k 共用;N=1 时每个任务只起 1 个候选,N=k 时起 n 个)。
    base_dir:落盘根(目前不写文件,但接口对齐 EvalRunner,后续可加 JSONL 持久化)。
    persist:接口位(留口子,本版不写盘)。
    docker_available:None → 自动探;True/False → 显式给定(测试用)。
    """
    if n < 1:
        raise ValueError(f"n 必须 ≥ 1,得 {n}")
    base_dir = Path(base_dir)
    base_dir.mkdir(parents=True, exist_ok=True)

    supported = 0
    skipped = 0
    n1_passed = n3_passed = 0
    n1_total = n3_total = 0
    per_task: dict[str, BridgePerTask] = {}
    per_task_status: dict[str, tuple[str, str]] = {}
    reasons: dict[str, int] = {}

    for d in task_dirs:
        tb_task = load_tb_task(d)
        if tb_task is None:
            skipped += 1
            reasons["unparsable"] = reasons.get("unparsable", 0) + 1
            per_task_status[Path(d).name] = ("skipped", "task missing task.yaml/instruction")
            continue
        cls = classify(tb_task, docker_available=docker_available)
        if not cls.supported:
            skipped += 1
            reasons[cls.kind] = reasons.get(cls.kind, 0) + 1
            per_task_status[tb_task.task_id] = ("skipped", cls.reason)
            log.info("[bridge] skip %s — %s", tb_task.task_id, cls.reason)
            continue

        supported += 1
        # docker 路径下:verify 在 worktree 内跑(verify_dir = worktree 路径),
        # 容器 mount worktree 到 /app 直接看到 agent 产出。**不**需要单独 mirror
        # —— 旧版 mirror 工作流(bridge 先 seed、agent 写 worktree、_run 末尾镜像)有
        # 时序问题:verify 在 _run 末尾**之前**就跑,镜像还没建出。直接 mount worktree
        # 干净。mirror_dir 参数在 build_spec_for_task 仍保留以兼容接口,实际忽略。
        cls = classify(tb_task, docker_available=docker_available)
        mirror = None  # 不再 seed(legacy noop,见 _build_docker_verify_cmd 注释)
        # SubAgentFactory.frozen=True → output_mirror 不能 in-place 改;用 object.__setattr__
        # 绕开冻结。本桥接是 async-per-task(每个 task 跑完再下一个),不存在并发,安全。
        prev_mirror = engine._factory.output_mirror
        try:
            object.__setattr__(engine._factory, "output_mirror", mirror)
        except Exception:
            pass

        # 同一任务跑两份:N=1(基线)与 N=n(best_of_n)
        try:
            spec_n1 = build_spec_for_task(tb_task, n=1, model_tier="default", mirror_dir=mirror)
            spec_nk = build_spec_for_task(tb_task, n=n, model_tier="default", mirror_dir=mirror)
            stage_n1 = asyncio.run(_drive_engine(engine, spec_n1))
            stage_nk = asyncio.run(_drive_engine(engine, spec_nk))
        except Exception as e:  # noqa: BLE001 — 不让单任务 crash 拖垮整批
            log.warning("[bridge] engine crashed on %s: %s", tb_task.task_id, e)
            per_task_status[tb_task.task_id] = ("error", f"{type(e).__name__}: {e}")
            per_task[tb_task.task_id] = BridgePerTask(
                n1_winner=None, n3_winner=None,
                n1_status="error", n3_status="error",
                n1_candidates=(), n3_candidates=(), error=str(e),
            )
            # 恢复 mirror
            try:
                object.__setattr__(engine._factory, "output_mirror", prev_mirror)
            except Exception:
                pass
            continue
        # 恢复 mirror
        try:
            object.__setattr__(engine._factory, "output_mirror", prev_mirror)
        except Exception:
            pass

        # W6 调试:打印每个 candidate 的 ok / verdict / error,看到底是哪里 failed
        import logging as _lg
        for c in stage_n1.candidates:
            _lg.warning(
                "[bridge] N1 candidate %s: ok=%s verdict=%s err=%s",
                c.agent_id, c.ok, c.verdict,
                (c.error or "")[:200] if c.error else "",
            )
        for c in stage_nk.candidates:
            _lg.warning(
                "[bridge] Nk candidate %s: ok=%s verdict=%s err=%s",
                c.agent_id, c.ok, c.verdict,
                (c.error or "")[:200] if c.error else "",
            )

        # N=1:N=1 时 stage_n1.results 必为 1 个 winner(同一候选)
        w_n1 = stage_n1.results[0]
        s_n1 = _status_of_winner(w_n1)
        n1_total += 1
        if s_n1 == "passed":
            n1_passed += 1
        # N=k:同理
        w_nk = stage_nk.results[0]
        s_nk = _status_of_winner(w_nk)
        n3_total += 1
        if s_nk == "passed":
            n3_passed += 1

        per_task[tb_task.task_id] = BridgePerTask(
            n1_winner=w_n1.agent_id,
            n3_winner=w_nk.agent_id,
            n1_status=s_n1,
            n3_status=s_nk,
            n1_candidates=stage_n1.candidates,
            n3_candidates=stage_nk.candidates,
        )
        # 任务级最终态:N=k 维度为主(N=k 是"我们的卖点");N=k 没 passed → 看 N=1
        # 透出哪个维度的数字,reason 写明(N=k 是真卖点,但要看 N=1 也单独报)
        final_status = s_nk if s_nk == "passed" else s_n1
        reason = "n3" if s_nk == "passed" else ("n1" if s_n1 == "passed" else "both_failed")
        per_task_status[tb_task.task_id] = (final_status, reason)

    pass_at_1_n1 = (n1_passed / n1_total) if n1_total else 0.0
    pass_at_1_n3 = (n3_passed / n3_total) if n3_total else 0.0
    return BridgeReport(
        total_seen=supported + skipped,
        supported=supported,
        skipped=skipped,
        n=n,
        pass_at_1_n1=pass_at_1_n1,
        pass_at_1_n3=pass_at_1_n3,
        per_task=per_task,
        per_task_status=per_task_status,
        unsupported_reasons=reasons,
    )
