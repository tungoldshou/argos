"""RunRegistry 单元测试(#5b T1)。"""
from __future__ import annotations

import asyncio

import pytest

from argos_agent.daemon.registry import RunEntry, RunRegistry
from argos_agent.daemon.state_machine import TERMINAL_STATES


# ── register ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_register_creates_entry():
    reg = RunRegistry()
    entry = await reg.register(
        run_id="abc123def456", goal="refactor auth", workspace="/tmp",
    )
    assert entry.run_id == "abc123def456"
    assert entry.state == "pending"
    assert entry.goal == "refactor auth"
    assert entry.workspace == "/tmp"
    assert entry.worktree_path is None
    assert entry.tokens_in == 0
    assert entry.tokens_out == 0
    assert entry.cost_usd is None
    assert entry.created_at > 0


@pytest.mark.asyncio
async def test_register_persists_worktree_path():
    reg = RunRegistry()
    entry = await reg.register(
        run_id="abc123def456", goal="x", workspace="/tmp",
        worktree_path="/Users/zc/.argos/worktrees/abc123def456",
    )
    assert entry.worktree_path == "/Users/zc/.argos/worktrees/abc123def456"


@pytest.mark.asyncio
async def test_get_returns_none_for_unknown():
    reg = RunRegistry()
    assert reg.get("000000000000") is None


@pytest.mark.asyncio
async def test_register_increments_active_count():
    reg = RunRegistry(max_concurrent=3)
    await reg.register(run_id="a" * 12, goal="x", workspace="")
    await reg.register(run_id="b" * 12, goal="y", workspace="")
    assert reg.active_count == 2
    assert reg.max_concurrent == 3


# ── list / mark ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_filters_by_state():
    reg = RunRegistry()
    await reg.register(run_id="a" * 12, goal="x", workspace="")
    await reg.register(run_id="b" * 12, goal="y", workspace="")
    reg.mark(run_id="a" * 12, state="running")
    reg.mark(run_id="b" * 12, state="completed")
    running = reg.list(state="running")
    assert len(running) == 1
    assert running[0].run_id == "a" * 12
    completed = reg.list(state="completed")
    assert len(completed) == 1


@pytest.mark.asyncio
async def test_mark_updates_state_and_updated_at():
    reg = RunRegistry()
    entry = await reg.register(run_id="a" * 12, goal="x", workspace="")
    old_updated = entry.updated_at
    await asyncio.sleep(0.01)
    reg.mark(run_id="a" * 12, state="running")
    assert entry.state == "running"
    assert entry.updated_at > old_updated


# ── add_cost ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_add_cost_accumulates_tokens():
    reg = RunRegistry()
    await reg.register(run_id="a" * 12, goal="x", workspace="")
    reg.add_cost(run_id="a" * 12, tokens_in_delta=100, tokens_out_delta=50, cost_usd_delta=0.01)
    reg.add_cost(run_id="a" * 12, tokens_in_delta=200, tokens_out_delta=100, cost_usd_delta=0.02)
    entry = reg.get("a" * 12)
    assert entry.tokens_in == 300
    assert entry.tokens_out == 150
    assert abs(entry.cost_usd - 0.03) < 1e-9


@pytest.mark.asyncio
async def test_add_cost_with_none_keeps_none():
    """cost_usd_delta=None → 不累加(API 返 None 诚实保 None)。"""
    reg = RunRegistry()
    await reg.register(run_id="a" * 12, goal="x", workspace="")
    reg.add_cost(run_id="a" * 12, tokens_in_delta=100, tokens_out_delta=50, cost_usd_delta=None)
    entry = reg.get("a" * 12)
    assert entry.cost_usd is None
    assert entry.tokens_in == 100


# ── set_focus ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_set_focus_roundtrip():
    reg = RunRegistry()
    await reg.register(run_id="a" * 12, goal="x", workspace="")
    reg.set_focus(run_id="a" * 12, session_id="sess-abc")
    entry = reg.get("a" * 12)
    assert entry.focus_session_id == "sess-abc"
    reg.set_focus(run_id="a" * 12, session_id=None)
    assert entry.focus_session_id is None


# ── semaphore ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_acquire_and_release_increments_active_count():
    reg = RunRegistry(max_concurrent=2)
    await reg.acquire_slot()
    await reg.acquire_slot()
    # 第 3 次 acquire 阻塞(timeout 验证)
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(reg.acquire_slot(), timeout=0.05)
    reg.release_slot()
    # 释放后第 3 次成功
    await asyncio.wait_for(reg.acquire_slot(), timeout=0.1)
    assert reg.active_count == 0   # 还没 register,只是 semaphore


@pytest.mark.asyncio
async def test_acquire_slot_allows_max_concurrent_then_blocks():
    reg = RunRegistry(max_concurrent=3)
    await reg.acquire_slot()
    await reg.acquire_slot()
    await reg.acquire_slot()
    # 第 4 个必阻塞
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(reg.acquire_slot(), timeout=0.05)


# ── cleanup / max_history ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cleanup_marks_terminal_and_releases_slot():
    reg = RunRegistry(max_concurrent=1)
    await reg.acquire_slot()
    await reg.register(run_id="a" * 12, goal="x", workspace="")
    reg.mark(run_id="a" * 12, state="running")
    # cleanup
    await reg.cleanup(run_id="a" * 12, terminal_state="completed")
    entry = reg.get("a" * 12)
    assert entry.state == "completed"
    # 槽位已释放:能再 acquire
    await asyncio.wait_for(reg.acquire_slot(), timeout=0.1)


@pytest.mark.asyncio
async def test_max_history_trims_oldest_terminal_runs():
    """终态 + 注册数 > max_history → 删最旧终态。"""
    reg = RunRegistry(max_concurrent=200, max_history=3)
    # 注册 5 个并标终态
    for i in range(5):
        rid = f"{i:012x}"
        await reg.register(run_id=rid, goal=f"g{i}", workspace="")
        reg.mark(run_id=rid, state="completed")
    await reg.cleanup(run_id="000000000004", terminal_state="completed")  # 触发 trim
    # 列表应只剩最新 3
    remaining = reg.list()
    assert len(remaining) == 3
    rids = {e.run_id for e in remaining}
    assert rids == {"000000000002", "000000000003", "000000000004"}


@pytest.mark.asyncio
async def test_cleanup_unknown_run_is_noop():
    reg = RunRegistry()
    await reg.cleanup(run_id="a" * 12, terminal_state="completed")  # 不应抛


@pytest.mark.asyncio
async def test_release_slot_does_not_error_when_not_held():
    """release_slot 多调一次不抛(防御性,bug-friendly)。"""
    reg = RunRegistry(max_concurrent=2)
    reg.release_slot()  # 啥也没持,不应抛
    await reg.acquire_slot()
    reg.release_slot()
    reg.release_slot()  # 多 release 一次


# ── integration: register → mark → cleanup 全流程 ──────────────────


@pytest.mark.asyncio
async def test_full_lifecycle_includes_cost_focus_worktree():
    reg = RunRegistry(max_concurrent=1)
    await reg.acquire_slot()
    entry = await reg.register(
        run_id="a" * 12, goal="refactor",
        workspace="/tmp", worktree_path="/tmp/wt",
    )
    assert entry.worktree_path == "/tmp/wt"
    reg.mark(run_id="a" * 12, state="running")
    reg.set_focus(run_id="a" * 12, session_id="sess")
    reg.add_cost(run_id="a" * 12, tokens_in_delta=1000, tokens_out_delta=200, cost_usd_delta=0.05)
    entry = reg.get("a" * 12)
    assert entry.state == "running"
    assert entry.focus_session_id == "sess"
    assert entry.tokens_in == 1000
    assert entry.cost_usd == 0.05
    # 收尾
    await reg.cleanup(run_id="a" * 12, terminal_state="completed")
    assert entry.state == "completed"
