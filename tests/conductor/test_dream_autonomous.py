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



@pytest.mark.asyncio
async def test_dream_starter_called_directly_when_guards_pass(tmp_path: Path, monkeypatch):
    from argos.learning import candidates as cand_mod

    cand_root = tmp_path / "candidates"
    monkeypatch.setattr(cand_mod, "DEFAULT_ROOT", cand_root)

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
        return True

    sup, events = _make_supervisor(tmp_path, dream_starter=_starter)

    s = _dream_suggestion()
    if sup._should_emit_dream(s):
        if s.action == "dream" and sup._dream_starter is not None:
            await sup._start_dream_autonomous(s)
        else:
            sup._pending[s.id] = s
            await sup._emit_suggestion(s)

    assert len(starter_calls) == 1, "dream_starter 应被调用一次"
    assert starter_calls[0].action == "dream"

    assert s.id not in sup.pending_suggestions, "自主模式: suggestion 不应进 pending"

    assert not any(e.get("kind") == "proactive_suggestion" for e in events),\
        "自主模式: 不应广播 proactive_suggestion 事件"



@pytest.mark.asyncio
async def test_no_material_dream_starter_not_called(tmp_path: Path, monkeypatch):
    from argos.learning import candidates as cand_mod

    cand_root = tmp_path / "empty_candidates"
    monkeypatch.setattr(cand_mod, "DEFAULT_ROOT", cand_root)

    starter_calls: list = []

    async def _starter(s: ProactiveSuggestion) -> bool:
        starter_calls.append(s)
        return True

    sup, events = _make_supervisor(tmp_path, dream_starter=_starter)

    s = _dream_suggestion()
    assert sup._should_emit_dream(s) is False, "空料应被材料门拦截"

    assert len(starter_calls) == 0
    assert s.id not in sup.pending_suggestions



@pytest.mark.asyncio
async def test_dream_starter_returns_false_not_in_pending(tmp_path: Path, monkeypatch):
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
        return False

    sup, events = _make_supervisor(tmp_path, dream_starter=_busy_starter)

    s = _dream_suggestion()
    assert sup._should_emit_dream(s) is True
    await sup._start_dream_autonomous(s)

    assert s.id not in sup.pending_suggestions, "守卫失败时 suggestion 不应进 pending"
    assert not any(e.get("kind") == "proactive_suggestion" for e in events)



@pytest.mark.asyncio
async def test_dream_starter_exception_silent(tmp_path: Path, monkeypatch):
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
    await sup._start_dream_autonomous(s)

    assert s.id not in sup.pending_suggestions
    assert not any(e.get("kind") == "proactive_suggestion" for e in events)



@pytest.mark.asyncio
async def test_no_dream_starter_falls_back_to_pending(tmp_path: Path, monkeypatch):
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

    sup, events = _make_supervisor(tmp_path, dream_starter=None)

    s = _dream_suggestion()
    assert sup._should_emit_dream(s) is True

    if s.action == "dream" and sup._dream_starter is not None:
        await sup._start_dream_autonomous(s)
    else:
        sup._pending[s.id] = s
        await sup._emit_suggestion(s)

    assert s.id in sup.pending_suggestions, "旧路: suggestion 应进 pending"
    assert any(e.get("kind") == "proactive_suggestion" for e in events),\
        "旧路: 应广播 proactive_suggestion 事件"



@pytest.mark.asyncio
async def test_run_suggestion_always_goes_to_pending(tmp_path: Path):
    starter_calls: list = []

    async def _starter(s: ProactiveSuggestion) -> bool:
        starter_calls.append(s)
        return True

    sup, events = _make_supervisor(tmp_path, dream_starter=_starter)

    s = _run_suggestion()

    assert sup._should_emit_dream(s) is True

    if s.action == "dream" and sup._dream_starter is not None:
        await sup._start_dream_autonomous(s)
    else:
        sup._pending[s.id] = s
        await sup._emit_suggestion(s)

    assert s.id in sup.pending_suggestions, "run suggestion 应进 pending"
    assert len(starter_calls) == 0, "dream_starter 不应被 run suggestion 触发"
