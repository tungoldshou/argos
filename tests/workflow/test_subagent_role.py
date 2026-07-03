"""Internal documentation."""
from __future__ import annotations

import pytest

from argos.workflow.spec import AgentTask, ROLE_PRESETS
from argos.workflow.subagent import SubAgentFactory


def _spy_agent_loop(monkeypatch, captured: dict):
    """Internal documentation."""
    from argos.workflow import subagent as _sub

    real_AgentLoop = _sub.AgentLoop

    def _spy(*args, **kwargs):
        captured.update(kwargs)
        return real_AgentLoop(*args, **kwargs)

    monkeypatch.setattr(_sub, "AgentLoop", _spy, raising=True)


@pytest.mark.asyncio
async def test_explorer_role_physically_strips_writes(
    tmp_path, scripted_model_factory, monkeypatch, requires_sandbox,
):
    """Internal documentation."""
    captured: dict = {}
    _spy_agent_loop(monkeypatch, captured)

    factory = SubAgentFactory.for_test(
        workspace=tmp_path, model_factory=scripted_model_factory,
    )
    task = AgentTask(prompt="只读侦察 {item}", role="explorer")
    res = await factory.run_task(
        task, item="README", agent_id="s#0", on_phase=lambda *a: None,
    )
    assert res.ok is True
    assert captured.get("read_only") is True, (
        f"explorer role 必须派生 read_only=True,实得 {captured.get('read_only')!r}"
    )


@pytest.mark.asyncio
async def test_planner_role_is_read_only(
    tmp_path, scripted_model_factory, monkeypatch, requires_sandbox,
):
    captured: dict = {}
    _spy_agent_loop(monkeypatch, captured)

    factory = SubAgentFactory.for_test(
        workspace=tmp_path, model_factory=scripted_model_factory,
    )
    task = AgentTask(prompt="出方案", role="planner")
    res = await factory.run_task(
        task, item="x", agent_id="s#0", on_phase=lambda *a: None,
    )
    assert res.ok is True
    assert captured.get("read_only") is True


@pytest.mark.asyncio
async def test_reviewer_role_is_read_only(
    tmp_path, scripted_model_factory, monkeypatch, requires_sandbox,
):
    captured: dict = {}
    _spy_agent_loop(monkeypatch, captured)

    factory = SubAgentFactory.for_test(
        workspace=tmp_path, model_factory=scripted_model_factory,
    )
    task = AgentTask(prompt="审 {item}", role="reviewer", verify="pytest -q")
    res = await factory.run_task(
        task, item="x", agent_id="s#0", on_phase=lambda *a: None,
    )
    assert res.ok is True
    assert captured.get("read_only") is True


@pytest.mark.asyncio
async def test_coder_role_keeps_writes(
    tmp_path, scripted_model_factory, monkeypatch, requires_sandbox,
):
    captured: dict = {}
    _spy_agent_loop(monkeypatch, captured)

    factory = SubAgentFactory.for_test(
        workspace=tmp_path, model_factory=scripted_model_factory,
    )
    task = AgentTask(prompt="写代码", role="coder", verify="pytest -q")
    res = await factory.run_task(
        task, item="x", agent_id="s#0", on_phase=lambda *a: None,
    )
    assert res.ok is True
    assert captured.get("read_only") is False, "coder 必须 read_only=False"


@pytest.mark.asyncio
async def test_coder_without_verify_reports_no_test(
    tmp_path, scripted_model_factory, requires_sandbox,
):
    """Internal documentation."""
    factory = SubAgentFactory.for_test(
        workspace=tmp_path, model_factory=scripted_model_factory,
    )
    task = AgentTask(prompt="写代码", role="coder", verify=None)
    res = await factory.run_task(
        task, item="x", agent_id="s#0", on_phase=lambda *a: None,
    )
    assert res.verdict != "passed", (
        f"coder 缺 verify 绝不当 passed(会谎报),实得 verdict={res.verdict!r}"
    )


@pytest.mark.asyncio
async def test_legacy_no_role_task_unchanged(
    tmp_path, scripted_model_factory, monkeypatch, requires_sandbox,
):
    """Internal documentation."""
    captured: dict = {}
    _spy_agent_loop(monkeypatch, captured)

    factory = SubAgentFactory.for_test(
        workspace=tmp_path, model_factory=scripted_model_factory,
    )
    task = AgentTask(prompt="x", tool_scope="read")
    res = await factory.run_task(
        task, item="x", agent_id="s#0", on_phase=lambda *a: None,
    )
    assert res.ok is True
    assert captured.get("read_only") is True
    assert captured.get("config").max_steps == 20


@pytest.mark.asyncio
async def test_legacy_no_role_full_scope_keeps_writes(
    tmp_path, scripted_model_factory, monkeypatch, requires_sandbox,
):
    """Internal documentation."""
    captured: dict = {}
    _spy_agent_loop(monkeypatch, captured)

    factory = SubAgentFactory.for_test(
        workspace=tmp_path, model_factory=scripted_model_factory,
    )
    task = AgentTask(prompt="x", tool_scope="full", verify="pytest -q")
    res = await factory.run_task(
        task, item="x", agent_id="s#0", on_phase=lambda *a: None,
    )
    assert res.ok is True
    assert captured.get("read_only") is False


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["explorer", "planner", "coder", "reviewer"])
async def test_all_four_roles_run_in_single_model_path(
    tmp_path, scripted_model_factory, role, requires_sandbox,
):
    """Internal documentation."""
    factory = SubAgentFactory.for_test(
        workspace=tmp_path, model_factory=scripted_model_factory,
    )
    verify = "pytest -q" if role in ("coder", "reviewer") else None
    task = AgentTask(prompt="任务 {item}", role=role, verify=verify)
    res = await factory.run_task(
        task, item="x", agent_id=f"s_{role}", on_phase=lambda *a: None,
    )
    assert res.ok is True, f"{role} 跑挂:{res.error}"


@pytest.mark.asyncio
async def test_role_max_steps_applied(
    tmp_path, scripted_model_factory, monkeypatch, requires_sandbox,
):
    """Internal documentation."""
    captured: dict = {}
    _spy_agent_loop(monkeypatch, captured)

    factory = SubAgentFactory.for_test(
        workspace=tmp_path, model_factory=scripted_model_factory,
    )
    expected = ROLE_PRESETS["planner"].max_steps
    task = AgentTask(prompt="x", role="planner")
    await factory.run_task(
        task, item="x", agent_id="s#0", on_phase=lambda *a: None,
    )
    assert captured.get("config").max_steps == expected, (
        f"planner role max_steps 应={expected},实得 {captured.get('config').max_steps!r}"
    )


@pytest.mark.asyncio
async def test_role_system_prompt_injected_into_prompt(
    tmp_path, scripted_model_factory, requires_sandbox,
):
    """Internal documentation."""
    factory = SubAgentFactory.for_test(
        workspace=tmp_path, model_factory=scripted_model_factory,
    )
    task = AgentTask(prompt="我的目标 {item}", role="explorer")
    res = await factory.run_task(
        task, item="x", agent_id="s#0", on_phase=lambda *a: None,
    )
    assert res.ok is True
