"""best_of_n op 验收 —— 任务:同任务 N 个候选,各自真跑真 verify(本测试 monkey-patch
SubAgentFactory.run_task 返确定结果,不替真沙箱路径;真沙箱路径由既有 test_subagent_*
那批覆盖),选第一个 passed / 全部不通过则如实标 failed / unverifiable。

约束(模块顶部 hard rule):
  · 候选数 N 真跑(不 mock 沙箱 / verify;本测试替 run_task 让 verdict 可控,沙箱逻辑不在
    本测覆盖范围 —— 既有 subagent_role 测已覆盖)
  · 无 passed 时 winner.verdict 必为 failed 或 unverifiable,**绝不** ok=True
  · diff 走摘要模式(SubAgentFactory.inline_diff=False 默认 → output 不含整段 diff,
    winners.diff_ref 落盘,output 段含 '[diff 摘要] ...')
  · 至少 1 passed → winner 必为那一个,ok=True,verdict='passed'
"""
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


# ── 工具:monkey-patch SubAgentFactory.run_task 返确定结果 ─────────


def _make_fake_run_task(scripts: dict[str, AgentResult]):
    """返一个 run_task 替身:按 agent_id 找预制结果,找不到就回一个保守 failed。"""
    async def _run(self, task, *, item, agent_id, on_phase):
        # 等一下让"并发"看起来真(否则 gather 一帧收完,排序退化)
        await asyncio.sleep(0.001)
        if agent_id in scripts:
            return scripts[agent_id]
        # 兜底
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
    """跑 spec(同步),返 StageResult(实际只有 1 个 stage)。"""
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


# ── (a) N=3 真并行跑了 3 个隔离候选 ────────────────────────────


def test_best_of_n_runs_n_candidates_in_parallel(tmp_path, monkeypatch):
    """3 个候选:SubAgentFactory.run_task 被调 3 次,各返不同 agent_id 形态(c0/c1/c2)。"""
    seen: list[str] = []
    scripts: dict[str, AgentResult] = {}

    async def _spy(self, task, *, item, agent_id, on_phase):
        seen.append(agent_id)
        await asyncio.sleep(0.01)  # 让真并发能发生
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
    # 真调了 3 次(3 个候选)
    assert len(seen) == 3
    assert sorted(seen) == ["s#c0", "s#c1", "s#c2"]
    # 候选全在 candidates(全本)
    assert len(sr.candidates) == 3
    assert {c.agent_id for c in sr.candidates} == {"s#c0", "s#c1", "s#c2"}
    # winner = 任一 passed(3 个都 passed,选 diff_file_count 最小者;都是 0 → 取下标最小 s#c0)
    assert len(sr.results) == 1
    assert sr.results[0].verdict == "passed"
    assert sr.results[0].ok is True
    assert sr.results[0].agent_id == "s#c0"


def test_best_of_n_default_n_is_three(tmp_path, monkeypatch):
    """不填 n → 默认 3(spec 解析层 _BEST_OF_N_DEFAULT=3)。"""
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
    assert len(seen) == 3  # 默认 3


def test_best_of_n_n_is_configurable(tmp_path, monkeypatch):
    """n=5 真跑 5 个候选。"""
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


# ── (b) 有候选通过时 → winner 必为通过的 ────────────────────


def test_best_of_n_picks_first_passed_when_some_pass(tmp_path, monkeypatch):
    """3 个候选:1 passed + 2 failed → winner = passed 那个,ok=True,verdict='passed'。"""
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
    # 全部候选在 candidates(全本,供人看)
    assert len(sr.candidates) == 3


def test_best_of_n_tie_breaks_by_smallest_diff(tmp_path, monkeypatch):
    """多个 passed:选 diff_file_count 最小者(diff 改动小优先;不动用 LLM 的更"小动作" = 更安全)。"""
    scripts = {
        "s#c0": _passed_result("s#c0", files=5),
        "s#c1": _passed_result("s#c1", files=1),  # 最小 diff
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
    assert sr.results[0].agent_id == "s#c1"  # files=1 最小
    assert sr.results[0].verdict == "passed"


def test_best_of_n_tie_breaks_by_index_when_diff_equal(tmp_path, monkeypatch):
    """多个 passed,files 数同 → 取下标小者(完全 tie 仍确定)。"""
    scripts = {
        "s#c0": _passed_result("s#c0", files=3),  # 下标 0
        "s#c1": _passed_result("s#c1", files=3),  # 下标 1
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


# ── (c) 全不通过时:winner.verdict 必为 failed/unverifiable,绝不假 passed ──


def test_best_of_n_all_failed_returns_failed_not_passed(tmp_path, monkeypatch):
    """3 候选全 failed → winner.ok=False,verdict='failed'(绝不假装通过)。"""
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
    # 诚实核心:绝不能 ok=True
    assert w.ok is False, f"无 passed 时 winner 不应 ok=True(实得 {w})"
    # 标 failed
    assert w.verdict == "failed"
    # 选了 files 最小那个(diff 改动小的"最不坏")
    assert w.agent_id == "s#c2"
    # 全部候选在 candidates
    assert len(sr.candidates) == 3


def test_best_of_n_all_unverifiable_returns_unverifiable(tmp_path, monkeypatch):
    """3 候选全 unverifiable → winner.verdict='unverifiable'(不擅自降级到 failed)。"""
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
    # 选下标最小者(全 tie)
    assert w.agent_id == "s#c0"


def test_best_of_n_mixed_unverifiable_failed_returns_unverifiable(tmp_path, monkeypatch):
    """混合 unverifiable + failed:winner.verdict='unverifiable'(更诚实的"测不了")。"""
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
    # 诚实:有 unverifiable → winner 标 unverifiable(不是 failed)
    assert w.verdict == "unverifiable", (
        f"mixed unverifiable+failed 应标 unverifiable 实得 {w.verdict!r}"
    )
    # winner 选了那个 unverifiable 的
    assert w.agent_id == "s#c1"


def test_best_of_n_with_some_crashed_still_picks_passed(tmp_path, monkeypatch):
    """2 passed + 1 error:winner 仍是 passed 那个(error 候选不污染选择)。"""
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
    # s#c1 files=0 vs s#c2 files=2 → s#c1 胜
    assert w.agent_id == "s#c1"


# ── (d) 候选的进度事件经 EventBus 真发出 ────────────────────


def test_best_of_n_emits_progress_per_candidate(tmp_path, monkeypatch):
    """每个候选 act/done 走 _emit → 拿 WorkflowProgress 事件列表能数到 N*2(act+done)。

    实际生产:_run_one 内部已经 emit 'act'(前)+ 'done'/'error'(后);
    候选内部若再调 on_phase(plan 阶段等)会再产生 phase 事件,但 act/done 这两个是
    引擎层硬保证的(每候选各 1 次)。
    """
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
    # 至少 N 个 act + N 个 done
    acts = [e for e in progress_events if e[2] == "act"]
    dones = [e for e in progress_events if e[2] == "done"]
    assert len(acts) == 3
    assert len(dones) == 3
    # 阶段 id 都是 's'
    assert {e[0] for e in progress_events} == {"s"}
    # agent_id 集合 == {s#c0, s#c1, s#c2}
    assert {e[1] for e in acts} == {"s#c0", "s#c1", "s#c2"}


# ── (e) diff 摘要模式:not inline diff 撑爆父上下文 ─────────


def test_best_of_n_uses_diff_summary_mode_by_default(tmp_path, monkeypatch):
    """best_of_n 透传到 SubAgentFactory 的 inline_diff=False 默认 → winners 不应把
    整段 diff inline 进 output;diff_ref 路径 + diff_summary 都应在(caller 拿到后渲染)。"""
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
    # winner 的 output 不含 'diff --git'(说明没 inline 整段 diff)
    assert "diff --git" not in str(w.output)
    # winner 的 diff 摘要信息在
    assert w.diff_ref is not None
    assert w.diff_summary is not None
    assert w.diff_file_count == 2


# ── (f) spec 解析:n=0/负数/超大都夹到合法区间 ──────────


def test_best_of_n_spec_parses_n_defaults_to_three():
    """不填 n → 默认 3(spec 解析层夹好)。"""
    spec = parse_spec({
        "name": "t", "description": "",
        "stages": [{
            "id": "s", "op": "best_of_n",
            "agent": {"prompt": "x", "tool_scope": "full", "verify": "pytest -q"},
        }],
    })
    assert spec.stages[0].n == 3


def test_best_of_n_spec_clamps_n_to_at_least_one():
    """n=0 / n=-1 → 夹到 1(防"0 候选"把 N 真跑的约束打穿)。"""
    spec = parse_spec({
        "name": "t", "description": "",
        "stages": [{
            "id": "s", "op": "best_of_n", "n": 0,
            "agent": {"prompt": "x", "tool_scope": "full", "verify": "pytest -q"},
        }],
    })
    assert spec.stages[0].n == 1


def test_best_of_n_spec_clamps_n_to_max_cap():
    """n=999 → 夹到 _BEST_OF_N_MAX(=16)。"""
    spec = parse_spec({
        "name": "t", "description": "",
        "stages": [{
            "id": "s", "op": "best_of_n", "n": 999,
            "agent": {"prompt": "x", "tool_scope": "full", "verify": "pytest -q"},
        }],
    })
    assert spec.stages[0].n == 16


def test_best_of_n_spec_rejects_non_int_n():
    """n='abc' → 抛 WorkflowSpecError(fail-closed 校验)。"""
    from argos.workflow.spec import WorkflowSpecError
    with pytest.raises(WorkflowSpecError, match="n 非法"):
        parse_spec({
            "name": "t", "description": "",
            "stages": [{
                "id": "s", "op": "best_of_n", "n": "abc",
                "agent": {"prompt": "x", "tool_scope": "full", "verify": "pytest -q"},
            }],
        })
