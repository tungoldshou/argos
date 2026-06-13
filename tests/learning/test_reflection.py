"""learning reflection 验收 — 任务:失败路径只产 reflection,绝不升级技能。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from argos.learning import reflection


def _write_run_store(tmp_path: Path, run_id: str, events: list[dict]) -> None:
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    p = runs_dir / f"{run_id}.jsonl"
    with p.open("w", encoding="utf-8") as fh:
        for ev in events:
            fh.write(json.dumps(ev, ensure_ascii=False) + "\n")


def _make_failed_events(reason: str = "tests failed") -> list[dict]:
    return [
        {"kind": "session_start", "goal": "fix foo", "seq": 0},
        {"kind": "code_action", "code": "x = 1", "step": 0, "seq": 1},
        {"kind": "code_result", "stdout": "", "exc": "AssertionError", "ok": False, "step": 0, "seq": 2},
        {"kind": "verify_verdict",
         "verdict": {"status": "failed", "reason": reason, "verify_cmd": "pytest"},
         "seq": 3},
    ]


def _make_unverifiable_events() -> list[dict]:
    return [
        {"kind": "session_start", "goal": "fix foo", "seq": 0},
        {"kind": "code_action", "code": "x = 1", "step": 0, "seq": 1},
        {"kind": "verify_verdict",
         "verdict": {"status": "unverifiable", "reason": "tampered", "tampered": ["tests/test_x.py"]},
         "seq": 2},
    ]


# ── 验收 c: 失败 run 永不产生技能、只产 reflection ──────────
def test_failed_run_writes_reflection_only(tmp_path, monkeypatch):
    """failed verdict → 调 memory capture_event,**不**写任何 skill 文件。"""
    captured: list[dict] = []
    # monkeypatch memory.auto.capture_event 拦截
    from argos.memory import auto as _mem_auto
    monkeypatch.setattr(
        _mem_auto, "capture_event",
        lambda kind, **kw: captured.append({"kind": kind, **kw}),
    )

    from argos.learning.reflection import reflect_failure

    run_id = "r#failed"
    events = _make_failed_events()
    _write_run_store(tmp_path, run_id, events)

    skills_root = tmp_path / "skills"   # 应保持空
    reflect_failure(
        run_id=run_id, store_dir=tmp_path / "runs",
        goal="fix foo", verify_cmd="pytest",
        verdict_status="failed",
        skills_root=skills_root,
    )
    # 写了 reflection
    assert len(captured) == 1
    assert captured[0]["kind"] == "task_reflection"
    assert captured[0].get("verdict") == "failed"
    # 没写 skill
    assert not skills_root.exists() or not any(skills_root.iterdir())


def test_unverifiable_run_writes_reflection_only(tmp_path, monkeypatch):
    """unverifiable verdict → 同样只产 reflection。"""
    captured: list[dict] = []
    from argos.memory import auto as _mem_auto
    monkeypatch.setattr(
        _mem_auto, "capture_event",
        lambda kind, **kw: captured.append({"kind": kind, **kw}),
    )

    from argos.learning.reflection import reflect_failure

    run_id = "r#unv"
    events = _make_unverifiable_events()
    _write_run_store(tmp_path, run_id, events)

    skills_root = tmp_path / "skills"
    reflect_failure(
        run_id=run_id, store_dir=tmp_path / "runs",
        goal="fix foo", verify_cmd="pytest",
        verdict_status="unverifiable",
        skills_root=skills_root,
    )
    assert len(captured) == 1
    assert captured[0]["kind"] == "task_reflection"
    assert captured[0].get("verdict") == "unverifiable"
    assert not skills_root.exists() or not any(skills_root.iterdir())


def test_reflection_swallows_memory_exceptions(tmp_path, monkeypatch):
    """memory 写失败 → reflect_failure 不抛(caller 可以放心 await)。"""
    from argos.memory import auto as _mem_auto
    def _boom(*a, **kw):
        raise RuntimeError("memory write failed")
    monkeypatch.setattr(_mem_auto, "capture_event", _boom)

    from argos.learning.reflection import reflect_failure
    # 不该抛
    reflect_failure(
        run_id="r#nope", store_dir=tmp_path / "runs",
        goal="x", verify_cmd="pytest",
        verdict_status="failed",
        skills_root=tmp_path / "skills",
    )
