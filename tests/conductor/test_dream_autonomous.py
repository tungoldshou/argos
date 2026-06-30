"""5a.3 Dream 自主启动验收测试。

契约：
  - 材料门放行 + dream_starter 注入 → tick 直接调 dream_starter，不进 pending，不广播 suggestion。
  - 材料门拦截（空料） → 不启动，不进 pending，不崩溃。
  - dream_starter 注入但守卫失败（busy / no key，返 False） → 不进 pending，不崩溃。
  - dream_starter 注入但抛异常 → 静默吞掉，不挂 tick loop。
  - 未注入 dream_starter（None）→ 退回旧路：进 pending + 广播（向后兼容）。
  - action="run" 的 suggestion 永远走旧路（进 pending），不受自主逻辑影响。
"""
from __future__ import annotations

import asyncio
import time
import uuid
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from argos.conductor.orders import OrderStore
from argos.conductor.proposals import ProactiveSuggestion
from argos.daemon.conductor_supervisor import ConductorSupervisor


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_supervisor(
    tmp_path: Path,
    *,
    dream_starter=None,
) -> tuple[ConductorSupervisor, list[dict]]:
    """构造带事件捕获的 ConductorSupervisor。"""
    events: list[dict] = []

    async def _bcast(ev: dict) -> None:
        events.append(ev)

    sup = ConductorSupervisor(
        orders_dir=tmp_path / "conductor",
        tick_interval=999.0,
        broadcast_fn=_bcast,
        dream_starter=dream_starter,
    )
    sup._broadcast_events = events
    return sup, events


def _dream_suggestion(order_id: str = "builtin-dream-nightly") -> ProactiveSuggestion:
    return ProactiveSuggestion(
        id=uuid.uuid4().hex,
        order_id=order_id,
        goal="__dream__",
        reason_human="定时触发（03:00）：夜间整合",
        suggested_at=time.time(),
        requires_confirmation=True,
        action="dream",
    )


def _run_suggestion(order_id: str = "ord-run") -> ProactiveSuggestion:
    return ProactiveSuggestion(
        id=uuid.uuid4().hex,
        order_id=order_id,
        goal="检查日志 {date}",
        reason_human="定时触发（09:00）",
        suggested_at=time.time(),
        requires_confirmation=True,
        action="run",
    )


# ── 核心：guards 全过 → dream_starter 被调，不进 pending ─────────────────────

@pytest.mark.asyncio
async def test_dream_starter_called_directly_when_guards_pass(tmp_path: Path, monkeypatch):
    """材料门放行 + dream_starter 注入 → 直接调 dream_starter，suggestion 不进 pending。"""
    from argos.learning import candidates as cand_mod

    cand_root = tmp_path / "candidates"
    monkeypatch.setattr(cand_mod, "DEFAULT_ROOT", cand_root)

    # 放一个候选让材料门放行
    from argos.learning.distiller import SkillCandidate
    cand = SkillCandidate(
        name="auto_learned",
        body_markdown="# x\n\n```python\nprint('ok')\n```",
        verify_cmd="true",
        skill_md_path=Path("unused"),
    )
    cand_mod.save_candidate(
        cand, root=cand_root, source_run="run0001aabb22",
        workspace=str(tmp_path), goal="fix bug",
    )

    starter_calls: list[ProactiveSuggestion] = []

    async def _starter(s: ProactiveSuggestion) -> bool:
        starter_calls.append(s)
        return True  # 成功启动

    sup, events = _make_supervisor(tmp_path, dream_starter=_starter)

    s = _dream_suggestion()
    # 手动触发自主路径（绕过 engine.tick，直接测 _run_loop 的 per-suggestion 逻辑）
    if sup._should_emit_dream(s):
        if s.action == "dream" and sup._dream_starter is not None:
            await sup._start_dream_autonomous(s)
        else:
            sup._pending[s.id] = s
            await sup._emit_suggestion(s)

    # dream_starter 被调用一次
    assert len(starter_calls) == 1, "dream_starter 应被调用一次"
    assert starter_calls[0].action == "dream"

    # suggestion 没进 pending（自主模式不等确认）
    assert s.id not in sup.pending_suggestions, "自主模式: suggestion 不应进 pending"

    # 没有广播 proactive_suggestion 事件（自主启动，不需要用户看到建议）
    assert not any(e.get("kind") == "proactive_suggestion" for e in events), \
        "自主模式: 不应广播 proactive_suggestion 事件"


# ── 空料：材料门拦截 → dream_starter 不被调 ─────────────────────────────────

@pytest.mark.asyncio
async def test_no_material_dream_starter_not_called(tmp_path: Path, monkeypatch):
    """材料门拦截（空料）→ dream_starter 不被调，不进 pending，不崩溃。"""
    from argos.learning import candidates as cand_mod

    cand_root = tmp_path / "empty_candidates"
    monkeypatch.setattr(cand_mod, "DEFAULT_ROOT", cand_root)
    # 候选区不放任何候选 → has_material = False

    starter_calls: list = []

    async def _starter(s: ProactiveSuggestion) -> bool:
        starter_calls.append(s)
        return True

    sup, events = _make_supervisor(tmp_path, dream_starter=_starter)

    s = _dream_suggestion()
    # 材料门应拦截
    assert sup._should_emit_dream(s) is False, "空料应被材料门拦截"

    # 由于材料门拦截，_run_loop 里的逻辑直接 continue；验证 starter 未被调
    assert len(starter_calls) == 0
    assert s.id not in sup.pending_suggestions


# ── dream_starter 返 False（busy）→ 不进 pending，不崩溃 ──────────────────────

@pytest.mark.asyncio
async def test_dream_starter_returns_false_not_in_pending(tmp_path: Path, monkeypatch):
    """dream_starter 返 False（守卫失败）→ 不进 pending，不崩溃。"""
    from argos.learning import candidates as cand_mod

    cand_root = tmp_path / "candidates"
    monkeypatch.setattr(cand_mod, "DEFAULT_ROOT", cand_root)

    from argos.learning.distiller import SkillCandidate
    cand = SkillCandidate(
        name="busy_test",
        body_markdown="# x\n\n```python\nprint('ok')\n```",
        verify_cmd="true",
        skill_md_path=Path("unused"),
    )
    cand_mod.save_candidate(
        cand, root=cand_root, source_run="run0001ccdd33",
        workspace=str(tmp_path), goal="test",
    )

    async def _busy_starter(s: ProactiveSuggestion) -> bool:
        return False  # 守卫失败（busy）

    sup, events = _make_supervisor(tmp_path, dream_starter=_busy_starter)

    s = _dream_suggestion()
    # 材料门放行，然后 dream_starter 返 False
    assert sup._should_emit_dream(s) is True
    await sup._start_dream_autonomous(s)

    assert s.id not in sup.pending_suggestions, "守卫失败时 suggestion 不应进 pending"
    assert not any(e.get("kind") == "proactive_suggestion" for e in events)


# ── dream_starter 抛异常 → 静默，不挂 tick loop ──────────────────────────────

@pytest.mark.asyncio
async def test_dream_starter_exception_silent(tmp_path: Path, monkeypatch):
    """dream_starter 抛异常 → log.warning + 不抛，不进 pending。"""
    from argos.learning import candidates as cand_mod

    cand_root = tmp_path / "candidates"
    monkeypatch.setattr(cand_mod, "DEFAULT_ROOT", cand_root)

    from argos.learning.distiller import SkillCandidate
    cand = SkillCandidate(
        name="exc_test",
        body_markdown="# x\n\n```python\nprint('ok')\n```",
        verify_cmd="true",
        skill_md_path=Path("unused"),
    )
    cand_mod.save_candidate(
        cand, root=cand_root, source_run="run0001eeff44",
        workspace=str(tmp_path), goal="test",
    )

    async def _boom_starter(s: ProactiveSuggestion) -> bool:
        raise RuntimeError("simulated pipeline init failure")

    sup, events = _make_supervisor(tmp_path, dream_starter=_boom_starter)

    s = _dream_suggestion()
    # 不应抛
    await sup._start_dream_autonomous(s)

    assert s.id not in sup.pending_suggestions
    assert not any(e.get("kind") == "proactive_suggestion" for e in events)


# ── 未注入 dream_starter → 退回旧路：进 pending + 广播 ──────────────────────

@pytest.mark.asyncio
async def test_no_dream_starter_falls_back_to_pending(tmp_path: Path, monkeypatch):
    """dream_starter=None → 旧路：dream suggestion 进 pending + 广播事件（向后兼容）。"""
    from argos.learning import candidates as cand_mod

    cand_root = tmp_path / "candidates"
    monkeypatch.setattr(cand_mod, "DEFAULT_ROOT", cand_root)

    from argos.learning.distiller import SkillCandidate
    cand = SkillCandidate(
        name="fallback_test",
        body_markdown="# x\n\n```python\nprint('ok')\n```",
        verify_cmd="true",
        skill_md_path=Path("unused"),
    )
    cand_mod.save_candidate(
        cand, root=cand_root, source_run="run0001aabb55",
        workspace=str(tmp_path), goal="test",
    )

    # dream_starter=None → 旧路
    sup, events = _make_supervisor(tmp_path, dream_starter=None)

    s = _dream_suggestion()
    assert sup._should_emit_dream(s) is True

    # 手动模拟 _run_loop 的分支逻辑（dream_starter is None → 旧路）
    if s.action == "dream" and sup._dream_starter is not None:
        await sup._start_dream_autonomous(s)
    else:
        sup._pending[s.id] = s
        await sup._emit_suggestion(s)

    # 旧路：suggestion 进 pending
    assert s.id in sup.pending_suggestions, "旧路: suggestion 应进 pending"
    # 旧路：广播 proactive_suggestion 事件
    assert any(e.get("kind") == "proactive_suggestion" for e in events), \
        "旧路: 应广播 proactive_suggestion 事件"


# ── action="run" 的 suggestion 永远走旧路 ────────────────────────────────────

@pytest.mark.asyncio
async def test_run_suggestion_always_goes_to_pending(tmp_path: Path):
    """action=run 的 suggestion 无论如何都进 pending（自主逻辑只针对 dream）。"""
    starter_calls: list = []

    async def _starter(s: ProactiveSuggestion) -> bool:
        starter_calls.append(s)
        return True

    sup, events = _make_supervisor(tmp_path, dream_starter=_starter)

    s = _run_suggestion()

    # _should_emit_dream 对 action=run 永远放行
    assert sup._should_emit_dream(s) is True

    # 模拟 _run_loop 分支：action != "dream" → 旧路
    if s.action == "dream" and sup._dream_starter is not None:
        await sup._start_dream_autonomous(s)
    else:
        sup._pending[s.id] = s
        await sup._emit_suggestion(s)

    assert s.id in sup.pending_suggestions, "run suggestion 应进 pending"
    assert len(starter_calls) == 0, "dream_starter 不应被 run suggestion 触发"
