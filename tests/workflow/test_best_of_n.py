"""Internal documentation."""
from __future__ import annotations

import asyncio
import os
import time
import uuid
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

import pytest

from argos.workflow.engine import WorkflowEngine
from argos.workflow.result import AgentResult
from argos.workflow.spec import parse_spec
from argos.workflow.subagent import SubAgentFactory




def _make_fake_run_task(scripts: dict[str, AgentResult]):
    """Internal documentation."""
    async def _run(self, task, *, item, agent_id, on_phase):
        await asyncio.sleep(0.001)
        if agent_id in scripts:
            return scripts[agent_id]
        return AgentResult(
            agent_id=agent_id, ok=False, output="",
            error="no script registered for this candidate",
        )
    return _run


def _patch_run_task(monkeypatch, scripts: dict[str, AgentResult]) -> None:
    monkeypatch.setattr(SubAgentFactory, "run_task", _make_fake_run_task(scripts))


def _build_engine(tmp_path, *, model_factory=None) -> WorkflowEngine:
    if model_factory is None:
        from tests.e2e.scripted_model import ScriptedModelClient
        def model_factory(_profile=None):
            return ScriptedModelClient(["x"])
    return WorkflowEngine.for_test(workspace=tmp_path, model_factory=model_factory)


def _drive(engine: WorkflowEngine, spec_dict: dict) -> AgentResult:
    """Internal documentation."""
    spec = parse_spec(spec_dict)
    async def _go():
        async for _ev in engine.run(spec):
            pass
    asyncio.run(_go())
    assert engine.last_result is not None
    return engine.last_result.stages[0]


def _passed_result(agent_id: str, *, files: int = 0) -> AgentResult:
    return AgentResult(
        agent_id=agent_id, ok=True, output=f"done {agent_id}",
        verdict="passed", error=None,
        diff_ref=f"/tmp/{agent_id}.diff",
        diff_summary=f"{files} files changed, +0/-0 lines",
        diff_file_count=files,
    )


def _failed_result(agent_id: str, *, files: int = 0) -> AgentResult:
    return AgentResult(
        agent_id=agent_id, ok=True, output=f"tried {agent_id}",
        verdict="failed", error=None,
        diff_ref=None, diff_summary=None, diff_file_count=files,
    )


def _unverifiable_result(agent_id: str) -> AgentResult:
    return AgentResult(
        agent_id=agent_id, ok=True, output=f"tried {agent_id}",
        verdict="unverifiable", error=None,
        diff_ref=None, diff_summary=None, diff_file_count=0,
    )


def _error_result(agent_id: str) -> AgentResult:
    return AgentResult(agent_id=agent_id, ok=False, output="", verdict=None,
                       error="simulated agent crash")




def test_best_of_n_runs_n_candidates_in_parallel(tmp_path, monkeypatch):
    """Internal documentation."""
    seen: list[str] = []
    scripts: dict[str, AgentResult] = {}

    async def _spy(self, task, *, item, agent_id, on_phase):
        seen.append(agent_id)
        await asyncio.sleep(0.01)
        r = _passed_result(agent_id)
        scripts[agent_id] = r
        return r

    monkeypatch.setattr(SubAgentFactory, "run_task", _spy)
    eng = _build_engine(tmp_path)
    sr = _drive(eng, {
        "name": "t", "description": "",
        "stages": [{
            "id": "s", "op": "best_of_n", "n": 3,
            "agent": {"prompt": "fix", "tool_scope": "full",
                      "isolation": "worktree", "verify": "pytest -q"},
        }],
    })
    assert len(seen) == 3
    assert sorted(seen) == ["s#c0", "s#c1", "s#c2"]
    assert len(sr.candidates) == 3
    assert {c.agent_id for c in sr.candidates} == {"s#c0", "s#c1", "s#c2"}
    assert len(sr.results) == 1
    assert sr.results[0].verdict == "passed"
    assert sr.results[0].ok is True
    assert sr.results[0].agent_id == "s#c0"


def test_best_of_n_default_n_is_three(tmp_path, monkeypatch):
    """Internal documentation."""
    seen: list[str] = []

    async def _spy(self, task, *, item, agent_id, on_phase):
        seen.append(agent_id)
        return _passed_result(agent_id)

    monkeypatch.setattr(SubAgentFactory, "run_task", _spy)
    eng = _build_engine(tmp_path)
    sr = _drive(eng, {
        "name": "t", "description": "",
        "stages": [{
            "id": "s", "op": "best_of_n",
            "agent": {"prompt": "x", "tool_scope": "full", "verify": "pytest -q"},
        }],
    })
    assert len(seen) == 3


def test_best_of_n_n_is_configurable(tmp_path, monkeypatch):
    """Internal documentation."""
    seen: list[str] = []

    async def _spy(self, task, *, item, agent_id, on_phase):
        seen.append(agent_id)
        return _passed_result(agent_id)

    monkeypatch.setattr(SubAgentFactory, "run_task", _spy)
    eng = _build_engine(tmp_path)
    sr = _drive(eng, {
        "name": "t", "description": "",
        "stages": [{
            "id": "s", "op": "best_of_n", "n": 5,
            "agent": {"prompt": "x", "tool_scope": "full", "verify": "pytest -q"},
        }],
    })
    assert len(seen) == 5
    assert sorted(seen) == ["s#c0", "s#c1", "s#c2", "s#c3", "s#c4"]




def test_best_of_n_picks_first_passed_when_some_pass(tmp_path, monkeypatch):
    """Internal documentation."""
    scripts = {
        "s#c0": _failed_result("s#c0"),
        "s#c1": _passed_result("s#c1", files=2),
        "s#c2": _failed_result("s#c2"),
    }
    _patch_run_task(monkeypatch, scripts)
    eng = _build_engine(tmp_path)
    sr = _drive(eng, {
        "name": "t", "description": "",
        "stages": [{
            "id": "s", "op": "best_of_n", "n": 3,
            "agent": {"prompt": "x", "tool_scope": "full", "verify": "pytest -q"},
        }],
    })
    assert len(sr.results) == 1
    w = sr.results[0]
    assert w.ok is True
    assert w.verdict == "passed"
    assert w.agent_id == "s#c1"
    assert len(sr.candidates) == 3


def test_best_of_n_tie_breaks_by_smallest_diff(tmp_path, monkeypatch):
    """Internal documentation."""
    scripts = {
        "s#c0": _passed_result("s#c0", files=5),
        "s#c1": _passed_result("s#c1", files=1),
        "s#c2": _passed_result("s#c2", files=10),
    }
    _patch_run_task(monkeypatch, scripts)
    eng = _build_engine(tmp_path)
    sr = _drive(eng, {
        "name": "t", "description": "",
        "stages": [{
            "id": "s", "op": "best_of_n", "n": 3,
            "agent": {"prompt": "x", "tool_scope": "full", "verify": "pytest -q"},
        }],
    })
    assert sr.results[0].agent_id == "s#c1"
    assert sr.results[0].verdict == "passed"


def test_best_of_n_tie_breaks_by_index_when_diff_equal(tmp_path, monkeypatch):
    """Internal documentation."""
    scripts = {
        "s#c0": _passed_result("s#c0", files=3),
        "s#c1": _passed_result("s#c1", files=3),
    }
    _patch_run_task(monkeypatch, scripts)
    eng = _build_engine(tmp_path)
    sr = _drive(eng, {
        "name": "t", "description": "",
        "stages": [{
            "id": "s", "op": "best_of_n", "n": 2,
            "agent": {"prompt": "x", "tool_scope": "full", "verify": "pytest -q"},
        }],
    })
    assert sr.results[0].agent_id == "s#c0"




def test_best_of_n_all_failed_returns_failed_not_passed(tmp_path, monkeypatch):
    """Internal documentation."""
    scripts = {
        "s#c0": _failed_result("s#c0", files=2),
        "s#c1": _failed_result("s#c1", files=1),
        "s#c2": _failed_result("s#c2", files=0),
    }
    _patch_run_task(monkeypatch, scripts)
    eng = _build_engine(tmp_path)
    sr = _drive(eng, {
        "name": "t", "description": "",
        "stages": [{
            "id": "s", "op": "best_of_n", "n": 3,
            "agent": {"prompt": "x", "tool_scope": "full", "verify": "pytest -q"},
        }],
    })
    w = sr.results[0]
    assert w.ok is False, f"无 passed 时 winner 不应 ok=True(实得 {w})"
    assert w.verdict == "failed"
    assert w.agent_id == "s#c2"
    assert len(sr.candidates) == 3


def test_best_of_n_all_unverifiable_returns_unverifiable(tmp_path, monkeypatch):
    """Internal documentation."""
    scripts = {
        "s#c0": _unverifiable_result("s#c0"),
        "s#c1": _unverifiable_result("s#c1"),
        "s#c2": _unverifiable_result("s#c2"),
    }
    _patch_run_task(monkeypatch, scripts)
    eng = _build_engine(tmp_path)
    sr = _drive(eng, {
        "name": "t", "description": "",
        "stages": [{
            "id": "s", "op": "best_of_n", "n": 3,
            "agent": {"prompt": "x", "tool_scope": "full", "verify": "pytest -q"},
        }],
    })
    w = sr.results[0]
    assert w.ok is False
    assert w.verdict == "unverifiable", f"全 unverifiable 应如实标,实得 {w.verdict!r}"
    assert w.agent_id == "s#c0"


def test_best_of_n_mixed_unverifiable_failed_returns_unverifiable(tmp_path, monkeypatch):
    """Internal documentation."""
    scripts = {
        "s#c0": _failed_result("s#c0"),
        "s#c1": _unverifiable_result("s#c1"),
        "s#c2": _failed_result("s#c2"),
    }
    _patch_run_task(monkeypatch, scripts)
    eng = _build_engine(tmp_path)
    sr = _drive(eng, {
        "name": "t", "description": "",
        "stages": [{
            "id": "s", "op": "best_of_n", "n": 3,
            "agent": {"prompt": "x", "tool_scope": "full", "verify": "pytest -q"},
        }],
    })
    w = sr.results[0]
    assert w.ok is False
    assert w.verdict == "unverifiable", (
        f"mixed unverifiable+failed 应标 unverifiable 实得 {w.verdict!r}"
    )
    assert w.agent_id == "s#c1"


def test_best_of_n_with_some_crashed_still_picks_passed(tmp_path, monkeypatch):
    """Internal documentation."""
    scripts = {
        "s#c0": _error_result("s#c0"),
        "s#c1": _passed_result("s#c1"),
        "s#c2": _passed_result("s#c2", files=2),
    }
    _patch_run_task(monkeypatch, scripts)
    eng = _build_engine(tmp_path)
    sr = _drive(eng, {
        "name": "t", "description": "",
        "stages": [{
            "id": "s", "op": "best_of_n", "n": 3,
            "agent": {"prompt": "x", "tool_scope": "full", "verify": "pytest -q"},
        }],
    })
    w = sr.results[0]
    assert w.ok is True
    assert w.verdict == "passed"
    assert w.agent_id == "s#c1"




def test_best_of_n_emits_progress_per_candidate(tmp_path, monkeypatch):
    """Internal documentation."""
    progress_events: list[tuple[str, str, str]] = []

    async def _spy(self, task, *, item, agent_id, on_phase):
        await asyncio.sleep(0.001)
        return _passed_result(agent_id)

    monkeypatch.setattr(SubAgentFactory, "run_task", _spy)
    eng = _build_engine(tmp_path)
    spec = parse_spec({
        "name": "t", "description": "",
        "stages": [{
            "id": "s", "op": "best_of_n", "n": 3,
            "agent": {"prompt": "x", "tool_scope": "full", "verify": "pytest -q"},
        }],
    })
    async def _go():
        async for ev in eng.run(spec):
            progress_events.append((ev.stage_id, ev.agent_id, ev.phase))
    asyncio.run(_go())
    acts = [e for e in progress_events if e[2] == "act"]
    dones = [e for e in progress_events if e[2] == "done"]
    assert len(acts) == 3
    assert len(dones) == 3
    assert {e[0] for e in progress_events} == {"s"}
    assert {e[1] for e in acts} == {"s#c0", "s#c1", "s#c2"}




def test_best_of_n_uses_diff_summary_mode_by_default(tmp_path, monkeypatch):
    """Internal documentation."""
    async def _spy(self, task, *, item, agent_id, on_phase):
        await asyncio.sleep(0.001)
        return AgentResult(
            agent_id=agent_id, ok=True, output="完成。", verdict="passed",
            diff_ref=f"/tmp/{agent_id}.diff",
            diff_summary="2 files changed, +5/-2 lines",
            diff_file_count=2,
        )
    monkeypatch.setattr(SubAgentFactory, "run_task", _spy)
    eng = _build_engine(tmp_path)
    sr = _drive(eng, {
        "name": "t", "description": "",
        "stages": [{
            "id": "s", "op": "best_of_n", "n": 2,
            "agent": {"prompt": "x", "tool_scope": "full", "verify": "pytest -q",
                      "isolation": "worktree"},
        }],
    })
    w = sr.results[0]
    assert "diff --git" not in str(w.output)
    assert w.diff_ref is not None
    assert w.diff_summary is not None
    assert w.diff_file_count == 2




def test_best_of_n_spec_parses_n_defaults_to_three():
    """Internal documentation."""
    spec = parse_spec({
        "name": "t", "description": "",
        "stages": [{
            "id": "s", "op": "best_of_n",
            "agent": {"prompt": "x", "tool_scope": "full", "verify": "pytest -q"},
        }],
    })
    assert spec.stages[0].n == 3


def test_best_of_n_spec_clamps_n_to_at_least_one():
    """Internal documentation."""
    spec = parse_spec({
        "name": "t", "description": "",
        "stages": [{
            "id": "s", "op": "best_of_n", "n": 0,
            "agent": {"prompt": "x", "tool_scope": "full", "verify": "pytest -q"},
        }],
    })
    assert spec.stages[0].n == 1


def test_best_of_n_spec_clamps_n_to_max_cap():
    """Internal documentation."""
    spec = parse_spec({
        "name": "t", "description": "",
        "stages": [{
            "id": "s", "op": "best_of_n", "n": 999,
            "agent": {"prompt": "x", "tool_scope": "full", "verify": "pytest -q"},
        }],
    })
    assert spec.stages[0].n == 16


def test_best_of_n_spec_rejects_non_int_n():
    """Internal documentation."""
    from argos.workflow.spec import WorkflowSpecError
    with pytest.raises(WorkflowSpecError, match="n 非法"):
        parse_spec({
            "name": "t", "description": "",
            "stages": [{
                "id": "s", "op": "best_of_n", "n": "abc",
                "agent": {"prompt": "x", "tool_scope": "full", "verify": "pytest -q"},
            }],
        })
