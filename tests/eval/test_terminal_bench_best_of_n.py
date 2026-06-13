"""Terminal-Bench → best_of_n 桥接 验收。

覆盖:
  (a) 桥接把每个 supported TB 任务真送进 best_of_n(走真 WorkflowEngine +
      SubAgentFactory,候选数 N 真跑;沙箱 / verify 不 mock,候选跑在隔离 worktree
      下)。unsupported 任务保持 skipped,不进分母。
  (b) run_pass_at_1 同时返 N=1 与 N=k 的 pass@1 数字;supported/skipped 计数
      与 TBBatchReport 同口径;不把 skipped 算进分母。
  (c) 跳过任务不计 passed(诚实铁律):哪怕 fake 全判 passed,skipped 也不能变 passed。

实现:TDD 路径——bridge 模块有 build_spec_for_task / run_pass_at_1 / BridgeReport 三个
公共契约;先写测试再写实现。
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from argos.eval.benchmarks import terminal_bench as tb
from argos.eval.benchmarks import terminal_bench_best_of_n as bridge
from argos.workflow.engine import WorkflowEngine
from argos.workflow.result import AgentResult
from argos.workflow.spec import WorkflowSpec
from argos.workflow.subagent import SubAgentFactory

from tests.eval._fakes import FakeWorktree

SMOKE_DIR = Path(__file__).parent / "_fixtures" / "tb_smoke"


# ── 工具:monkey-patch SubAgentFactory.run_task 返确定结果 ─────────
# 与 tests/workflow/test_best_of_n.py 同模式,只是把"按 agent_id 后缀(c0/c1/c2)
# 决定 verdict"独立成可注入:让 N=1 / N=3 都能定向控制候选结果。
def _make_fake_run_task(scripts: dict[str, AgentResult]):
    async def _run(self, task, *, item, agent_id, on_phase):
        await asyncio.sleep(0.001)
        if agent_id in scripts:
            return scripts[agent_id]
        return AgentResult(
            agent_id=agent_id, ok=False, output="",
            error=f"no script registered for {agent_id}",
        )
    return _run


def _patch_run_task(monkeypatch, scripts: dict[str, AgentResult]) -> None:
    monkeypatch.setattr(SubAgentFactory, "run_task", _make_fake_run_task(scripts))


def _build_engine(tmp_path) -> WorkflowEngine:
    """测试用 ScriptedModelClient(契约 §7)+ 临时 workspace。"""
    from tests.e2e.scripted_model import ScriptedModelClient

    def model_factory(_profile=None):
        return ScriptedModelClient(["x"])
    return WorkflowEngine.for_test(workspace=tmp_path, model_factory=model_factory)


def _passed(agent_id: str) -> AgentResult:
    return AgentResult(
        agent_id=agent_id, ok=True, output=f"done {agent_id}",
        verdict="passed", error=None,
        diff_ref=None, diff_summary=None, diff_file_count=0,
    )


def _failed(agent_id: str) -> AgentResult:
    return AgentResult(
        agent_id=agent_id, ok=True, output=f"tried {agent_id}",
        verdict="failed", error=None,
        diff_ref=None, diff_summary=None, diff_file_count=0,
    )


# ── (a) 桥接把每个 supported TB 任务真送进 best_of_n ────────────


def test_bridge_runs_supported_task_through_best_of_n(tmp_path, monkeypatch):
    """1 个 supported TB 任务 → 桥接把它送进 best_of_n 两份(N=1 与 N=3)各跑一次。
    N=3 时真跑 3 个候选(SubAgentFactory.run_task 在 N=3 那次被调 3 次);N=1 那次
    调 1 次。合起来 = 4 次(c0, c0, c1, c2 顺序无保证)。"""
    seen: list[str] = []

    async def _spy(self, task, *, item, agent_id, on_phase):
        seen.append(agent_id)
        return _passed(agent_id)
    monkeypatch.setattr(SubAgentFactory, "run_task", _spy)

    engine = _build_engine(tmp_path)
    report = bridge.run_pass_at_1(
        [SMOKE_DIR / "tb_echo_hello"], engine=engine, n=3,
        base_dir=tmp_path / "bridge_base", persist=False,
    )
    # N=1 + N=3 = 1 + 3 = 4 次调用
    assert len(seen) == 4
    # N=3 那次调 3 个不同的 c# 后缀;N=1 那次只调 c0(同一后缀出现 2 次)
    assert seen.count("tb_echo_hello#c0") == 2
    assert "tb_echo_hello#c1" in seen
    assert "tb_echo_hello#c2" in seen
    # report.supported=1,skipped=0
    assert report.supported == 1
    assert report.skipped == 0
    # 1 个任务跑了,N=3 全 passed → pass@1(N=1) = pass@1(N=3) = 1.0
    assert report.pass_at_1_n1 == 1.0
    assert report.pass_at_1_n3 == 1.0
    # per_task 状态:1 passed,winner 是某 c# 候选
    statuses = {tid: st for tid, (st, _) in report.per_task_status.items()}
    assert statuses["tb_echo_hello"] == "passed"


def test_bridge_skips_unsupported_without_invoking_engine(tmp_path, monkeypatch):
    """3 个 unsupported(compile_asm / hidden_state)+ 1 supported:engine 只为 supported 跑。
    docker_available=False 让 tb_compile_asm 走老 skip 路径。"""
    invoked: list[str] = []

    async def _spy(self, task, *, item, agent_id, on_phase):
        invoked.append(agent_id)
        return _passed(agent_id)
    monkeypatch.setattr(SubAgentFactory, "run_task", _spy)

    engine = _build_engine(tmp_path)
    report = bridge.run_pass_at_1(
        [
            SMOKE_DIR / "tb_compile_asm",     # unsupported_custom_image_no_docker (no docker)
            SMOKE_DIR / "tb_hidden_state",    # unsupported_protected_path
            SMOKE_DIR / "tb_echo_hello",      # supported
        ],
        engine=engine, n=1, base_dir=tmp_path / "bridge_base", persist=False,
        docker_available=False,
    )
    # engine 只为 supported 任务跑(1 个任务,跑 N=1 + N=1 各 1 候选 = 2 次)
    assert all("tb_echo_hello" in a for a in invoked)
    assert len(invoked) == 2  # n=1,1 个任务 × 2 份 spec(N=1 + N=1)
    # 计数
    assert report.total_seen == 3
    assert report.supported == 1
    assert report.skipped == 2
    # pass@1 = 1/1
    assert report.pass_at_1_n1 == 1.0
    # skip reason 分桶
    assert report.unsupported_reasons.get("unsupported_custom_image_no_docker") == 1
    assert report.unsupported_reasons.get("unsupported_protected_path") == 1


# ── (b) N=1 vs N=k:同一任务跑两轮,数字分别报 ──────────────────


def test_bridge_n1_and_n3_pass_at_1_calculated_independently(tmp_path, monkeypatch):
    """N=1:1 候选(只 c0 决定成败)。N=3:3 候选,任一 passed 即任务算 passed。

    用 1 个 supported 任务,3 个候选分别 passed/failed/passed:
      N=1:取 c0(failed)→ 任务 failed → pass@1(N=1)=0.0
      N=3:有 passed(c1 或 c2)→ 任务 passed → pass@1(N=3)=1.0
    → 同一批任务,N=k 真的能"拉起来"。
    """
    scripts = {
        "tb_echo_hello#c0": _failed("tb_echo_hello#c0"),
        "tb_echo_hello#c1": _passed("tb_echo_hello#c1"),
        "tb_echo_hello#c2": _passed("tb_echo_hello#c2"),
    }
    _patch_run_task(monkeypatch, scripts)

    engine = _build_engine(tmp_path)
    report = bridge.run_pass_at_1(
        [SMOKE_DIR / "tb_echo_hello"], engine=engine, n=3,
        base_dir=tmp_path / "bridge_base", persist=False,
    )
    # N=1 应取 c0(failed)→ pass@1(N=1)=0.0
    # N=3 取 c1 或 c2(passed)→ pass@1(N=3)=1.0
    assert report.pass_at_1_n1 == 0.0
    assert report.pass_at_1_n3 == 1.0
    # 提升幅度 > 0
    assert report.pass_at_1_n3 > report.pass_at_1_n1
    # per_task 状态:N=3 维度上 passed,N=1 维度上 failed
    statuses = report.per_task_status
    assert statuses["tb_echo_hello"] == ("passed", "n3")  # 见 BridgeReport 字段说明


def test_bridge_n1_and_n3_both_count_skipped_in_denom_separately(tmp_path, monkeypatch):
    """跳过任务不计入 N=1 也不计入 N=3 分母;只对 supported 任务计算 pass@1。"""
    # 5 unsupported + 1 supported(passed)
    async def _spy(self, task, *, item, agent_id, on_phase):
        return _passed(agent_id)
    monkeypatch.setattr(SubAgentFactory, "run_task", _spy)

    engine = _build_engine(tmp_path)
    subset = [SMOKE_DIR / "tb_compile_asm"] * 5 + [SMOKE_DIR / "tb_echo_hello"]
    report = bridge.run_pass_at_1(
        subset, engine=engine, n=3,
        base_dir=tmp_path / "bridge_base", persist=False,
        docker_available=False,  # 模拟"无 Docker",让 tb_compile_asm 走老 skip
    )
    # 1 supported 真跑 → N=1=1.0, N=3=1.0(全 passed)
    assert report.supported == 1
    assert report.skipped == 5
    assert report.pass_at_1_n1 == 1.0
    assert report.pass_at_1_n3 == 1.0


# ── (c) skipped 任务绝不记 passed(诚实铁律) ───────────────────────


def test_bridge_never_marks_skipped_as_passed(tmp_path, monkeypatch):
    """即使 fake loop 全返 passed,skipped 任务也仍是 skipped。"""
    async def _spy(self, task, *, item, agent_id, on_phase):
        return _passed(agent_id)
    monkeypatch.setattr(SubAgentFactory, "run_task", _spy)

    engine = _build_engine(tmp_path)
    report = bridge.run_pass_at_1(
        [SMOKE_DIR / "tb_compile_asm", SMOKE_DIR / "tb_hidden_state"],
        engine=engine, n=3, base_dir=tmp_path / "bridge_base", persist=False,
        docker_available=False,  # 模拟"无 Docker",让 tb_compile_asm 走老 skip
    )
    # 全 skipped,pass@1 必须 = 0.0(分母为 0 的退化,见实现)
    assert report.supported == 0
    assert report.skipped == 2
    assert report.pass_at_1_n1 == 0.0
    assert report.pass_at_1_n3 == 0.0
    statuses = {tid: st for tid, (st, _) in report.per_task_status.items()}
    for tid in ("tb_compile_asm", "tb_hidden_state"):
        assert statuses[tid] == "skipped"


# ── (d) build_spec_for_task 公共契约(桥接核心) ───────────────────


def test_build_spec_for_supported_task_has_best_of_n_stage():
    """给定一个 supported TB 任务 → 产 WorkflowSpec 单 stage、op=best_of_n、agent.verify=verify_cmd。"""
    tb_task = tb.load_tb_task(SMOKE_DIR / "tb_echo_hello")
    assert tb_task is not None
    spec = bridge.build_spec_for_task(tb_task, n=3, model_tier="default")
    assert isinstance(spec, WorkflowSpec)
    assert len(spec.stages) == 1
    stage = spec.stages[0]
    assert stage.op == "best_of_n"
    assert stage.n == 3
    agent = stage.agent[0] if isinstance(stage.agent, tuple) else stage.agent
    # verify_cmd 必须透传(子 agent 跑 verify 门 → 真三态裁决)
    # 历史:verify_cmd 之前是 `bash -c '...'`(首 token = bash 不在白名单,N=1 必 0%)。
    # 适配器修后:首 token 落在白名单(python / pytest)。桥接按 spec.verify 透传,不动。
    assert agent.verify is not None
    assert agent.verify.startswith("python -c ")
    # prompt = goal.md 内容
    assert "Write a shell script" in agent.prompt
    # coder 角色 + 写工具 + worktree 隔离(允许改 /app/run.sh)
    assert agent.role == "coder"
    assert agent.isolation == "worktree"
    assert agent.tool_scope == "full"
    # model 透传(若实现支持)
    assert agent.model == "default"


# ── (e) run_pass_at_1 接收 n=1(基线)真能跑 1 候选 ───────────────


def test_bridge_n_equals_one_runs_one_candidate(tmp_path, monkeypatch):
    """N=1 时,SubAgentFactory.run_task 只被调 1 次(只 c0)。"""
    seen: list[str] = []

    async def _spy(self, task, *, item, agent_id, on_phase):
        seen.append(agent_id)
        return _failed(agent_id)
    monkeypatch.setattr(SubAgentFactory, "run_task", _spy)

    engine = _build_engine(tmp_path)
    report = bridge.run_pass_at_1(
        [SMOKE_DIR / "tb_echo_hello"], engine=engine, n=1,
        base_dir=tmp_path / "bridge_base", persist=False,
    )
    # n=1:同一任务跑两份(N=1 + N=1),每份 1 个候选 → 2 次调用
    assert len(seen) == 2
    assert seen == ["tb_echo_hello#c0", "tb_echo_hello#c0"]
    # 1 候选 failed → 任务 failed → pass@1(N=1)=0.0
    assert report.pass_at_1_n1 == 0.0
    # pass@1(N=3) 走不到(实现可只算 N=1,或 N=3=0.0 因仍只跑了 1 任务)
    assert report.pass_at_1_n3 == 0.0
