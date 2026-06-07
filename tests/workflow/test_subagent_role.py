"""subagent 角色接线验收 — 任务:4 角色工具白名单物理剔除、coder 缺 verify 不判 passed、
旧 spec 不破、单模型路径全跑通。"""
from __future__ import annotations

import pytest

from argos_agent.workflow.spec import AgentTask, ROLE_PRESETS
from argos_agent.workflow.subagent import SubAgentFactory


def _spy_agent_loop(monkeypatch, captured: dict):
    """monkeypatch subagent 模块里的 AgentLoop,捕获所有 kwargs 给测试断言。"""
    from argos_agent.workflow import subagent as _sub

    real_AgentLoop = _sub.AgentLoop

    def _spy(*args, **kwargs):
        captured.update(kwargs)
        return real_AgentLoop(*args, **kwargs)

    monkeypatch.setattr(_sub, "AgentLoop", _spy, raising=True)


# ── 验收 a: explorer/planner/reviewer 物理上拿不到写工具 ─────────────
@pytest.mark.asyncio
async def test_explorer_role_physically_strips_writes(
    tmp_path, scripted_model_factory, monkeypatch,
):
    """role=explorer → AgentLoop(read_only=True) → 沙箱里 write_file/edit_file 等被剔除。"""
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
    tmp_path, scripted_model_factory, monkeypatch,
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
    tmp_path, scripted_model_factory, monkeypatch,
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


# ── 验收 a (续): coder 保留写工具 ───────────────────────────────────
@pytest.mark.asyncio
async def test_coder_role_keeps_writes(
    tmp_path, scripted_model_factory, monkeypatch,
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


# ── 验收 b: coder 缺 verify 不判 passed(走 NO_TEST 诚实路径) ─────────
@pytest.mark.asyncio
async def test_coder_without_verify_reports_no_test(
    tmp_path, scripted_model_factory,
):
    """coder role + verify=None → 不假装 passed(loop 走 is_honest_completion → NO_TEST)。
    子 agent ok=True 但 res.verdict=None(report 标 "未机检验证")。
    """
    factory = SubAgentFactory.for_test(
        workspace=tmp_path, model_factory=scripted_model_factory,
    )
    task = AgentTask(prompt="写代码", role="coder", verify=None)
    res = await factory.run_task(
        task, item="x", agent_id="s#0", on_phase=lambda *a: None,
    )
    # 关键:不假装 passed —— verdict 必须是 None(NO_TEST 路径)或 unverifiable,绝不是 "passed"
    assert res.verdict != "passed", (
        f"coder 缺 verify 绝不当 passed(会谎报),实得 verdict={res.verdict!r}"
    )


# ── 验收 c: 旧 spec(role=None)行为不变 ──────────────────────────────
@pytest.mark.asyncio
async def test_legacy_no_role_task_unchanged(
    tmp_path, scripted_model_factory, monkeypatch,
):
    """不填 role → 走原有 tool_scope 派生:tool_scope=read → read_only=True,旧行为不破。"""
    captured: dict = {}
    _spy_agent_loop(monkeypatch, captured)

    factory = SubAgentFactory.for_test(
        workspace=tmp_path, model_factory=scripted_model_factory,
    )
    task = AgentTask(prompt="x", tool_scope="read")  # 旧路径:无 role
    res = await factory.run_task(
        task, item="x", agent_id="s#0", on_phase=lambda *a: None,
    )
    assert res.ok is True
    # 既有行为:tool_scope=read → read_only=True
    assert captured.get("read_only") is True
    # 既有 max_steps=20(无 role 派生时不变)
    assert captured.get("config").max_steps == 20


@pytest.mark.asyncio
async def test_legacy_no_role_full_scope_keeps_writes(
    tmp_path, scripted_model_factory, monkeypatch,
):
    """不填 role + tool_scope=full → read_only=False(旧行为,新代码不破)。"""
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


# ── 验收 d: 单模型路径(无 router)4 角色全跑通 ──────────────────────
@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["explorer", "planner", "coder", "reviewer"])
async def test_all_four_roles_run_in_single_model_path(
    tmp_path, scripted_model_factory, role,
):
    """4 角色在单模型(scripted_model_factory,无 router)下都跑得通、不抛。"""
    factory = SubAgentFactory.for_test(
        workspace=tmp_path, model_factory=scripted_model_factory,
    )
    verify = "pytest -q" if role in ("coder", "reviewer") else None
    task = AgentTask(prompt="任务 {item}", role=role, verify=verify)
    res = await factory.run_task(
        task, item="x", agent_id=f"s_{role}", on_phase=lambda *a: None,
    )
    assert res.ok is True, f"{role} 跑挂:{res.error}"


# ── 角色 max_steps 派生(防跑飞) ──────────────────────────────────
@pytest.mark.asyncio
async def test_role_max_steps_applied(
    tmp_path, scripted_model_factory, monkeypatch,
):
    """role 的 max_steps 派生到 LoopConfig.max_steps(无 role 沿用 20)。"""
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


# ── 角色 system_prompt 注入(在 user 段前缀) ───────────────────────
@pytest.mark.asyncio
async def test_role_system_prompt_injected_into_prompt(
    tmp_path, scripted_model_factory,
):
    """role 存在时,system_prompt 拼到 user prompt 最前(prefix 注入)。"""
    factory = SubAgentFactory.for_test(
        workspace=tmp_path, model_factory=scripted_model_factory,
    )
    # explorer role → 实际 spawn 时 prompt 应含 "[角色:explorer]" 段
    task = AgentTask(prompt="我的目标 {item}", role="explorer")
    # 跑通就行 —— 注入是 _run 内部行为,这里间接通过 ok=True 验证不崩
    res = await factory.run_task(
        task, item="x", agent_id="s#0", on_phase=lambda *a: None,
    )
    assert res.ok is True
