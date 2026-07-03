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




def test_bridge_runs_supported_task_through_best_of_n(tmp_path, monkeypatch):
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
    assert len(seen) == 4
    assert seen.count("tb_echo_hello#c0") == 2
    assert "tb_echo_hello#c1" in seen
    assert "tb_echo_hello#c2" in seen
    # report.supported=1,skipped=0
    assert report.supported == 1
    assert report.skipped == 0
    assert report.pass_at_1_n1 == 1.0
    assert report.pass_at_1_n3 == 1.0
    statuses = {tid: st for tid, (st, _) in report.per_task_status.items()}
    assert statuses["tb_echo_hello"] == "passed"


def test_bridge_skips_unsupported_without_invoking_engine(tmp_path, monkeypatch):
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
    assert all("tb_echo_hello" in a for a in invoked)
    assert len(invoked) == 2
    assert report.total_seen == 3
    assert report.supported == 1
    assert report.skipped == 2
    # pass@1 = 1/1
    assert report.pass_at_1_n1 == 1.0
    assert report.unsupported_reasons.get("unsupported_custom_image_no_docker") == 1
    assert report.unsupported_reasons.get("unsupported_protected_path") == 1




def test_bridge_n1_and_n3_pass_at_1_calculated_independently(tmp_path, monkeypatch):
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
    assert report.pass_at_1_n1 == 0.0
    assert report.pass_at_1_n3 == 1.0
    assert report.pass_at_1_n3 > report.pass_at_1_n1
    statuses = report.per_task_status
    assert statuses["tb_echo_hello"] == ("passed", "n3")


def test_bridge_n1_and_n3_both_count_skipped_in_denom_separately(tmp_path, monkeypatch):
    # 5 unsupported + 1 supported(passed)
    async def _spy(self, task, *, item, agent_id, on_phase):
        return _passed(agent_id)
    monkeypatch.setattr(SubAgentFactory, "run_task", _spy)

    engine = _build_engine(tmp_path)
    subset = [SMOKE_DIR / "tb_compile_asm"] * 5 + [SMOKE_DIR / "tb_echo_hello"]
    report = bridge.run_pass_at_1(
        subset, engine=engine, n=3,
        base_dir=tmp_path / "bridge_base", persist=False,
        docker_available=False,
    )
    assert report.supported == 1
    assert report.skipped == 5
    assert report.pass_at_1_n1 == 1.0
    assert report.pass_at_1_n3 == 1.0




def test_bridge_never_marks_skipped_as_passed(tmp_path, monkeypatch):
    async def _spy(self, task, *, item, agent_id, on_phase):
        return _passed(agent_id)
    monkeypatch.setattr(SubAgentFactory, "run_task", _spy)

    engine = _build_engine(tmp_path)
    report = bridge.run_pass_at_1(
        [SMOKE_DIR / "tb_compile_asm", SMOKE_DIR / "tb_hidden_state"],
        engine=engine, n=3, base_dir=tmp_path / "bridge_base", persist=False,
        docker_available=False,
    )
    assert report.supported == 0
    assert report.skipped == 2
    assert report.pass_at_1_n1 == 0.0
    assert report.pass_at_1_n3 == 0.0
    statuses = {tid: st for tid, (st, _) in report.per_task_status.items()}
    for tid in ("tb_compile_asm", "tb_hidden_state"):
        assert statuses[tid] == "skipped"




def test_build_spec_for_supported_task_has_best_of_n_stage():
    tb_task = tb.load_tb_task(SMOKE_DIR / "tb_echo_hello")
    assert tb_task is not None
    spec = bridge.build_spec_for_task(tb_task, n=3, model_tier="default")
    assert isinstance(spec, WorkflowSpec)
    assert len(spec.stages) == 1
    stage = spec.stages[0]
    assert stage.op == "best_of_n"
    assert stage.n == 3
    agent = stage.agent[0] if isinstance(stage.agent, tuple) else stage.agent
    assert agent.verify is not None
    assert agent.verify.startswith("python -c ")
    assert "Write a shell script" in agent.prompt
    assert agent.role == "coder"
    assert agent.isolation == "worktree"
    assert agent.tool_scope == "full"
    assert agent.model == "default"




def test_bridge_n_equals_one_runs_one_candidate(tmp_path, monkeypatch):
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
    assert len(seen) == 2
    assert seen == ["tb_echo_hello#c0", "tb_echo_hello#c0"]
    assert report.pass_at_1_n1 == 0.0
    assert report.pass_at_1_n3 == 0.0
