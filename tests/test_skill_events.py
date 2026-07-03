from __future__ import annotations

import json

import pytest

from argos.skills_runtime.events import SkillRunStart, SkillRunEnd
from argos.tui.events import (
    Event, EventKind, _KIND_TO_CLASS, deserialize_event, serialize_event,
)


def test_skill_run_start_kind():
    s = SkillRunStart(skill_name="verify", args={"path": "x.py"})
    assert s.kind == "skill_run_start"


def test_skill_run_end_kind_and_verdict_literal():
    s = SkillRunEnd(
        skill_name="verify", verdict="passed", duration_ms=100,
        finding_count=0, error_count=0,
    )
    assert s.kind == "skill_run_end"
    for v in ("passed", "failed", "partial", "n_a", "skipped"):
        SkillRunEnd(skill_name="x", verdict=v, duration_ms=0, finding_count=0, error_count=0)


def test_serialize_deserialize_skill_run_start_round_trip():
    s = SkillRunStart(
        skill_name="verify", args={"path": "src/foo.py", "timeout": 30},
        cwd="/tmp", timestamp_ms=12345,
    )
    blob = serialize_event(s)  # type: ignore[arg-type]
    parsed = json.loads(blob)
    assert parsed["kind"] == "skill_run_start"
    restored = deserialize_event(blob)
    assert isinstance(restored, SkillRunStart)
    assert restored.skill_name == s.skill_name
    assert restored.args == s.args
    assert restored.cwd == s.cwd
    assert restored.timestamp_ms == s.timestamp_ms


def test_serialize_deserialize_skill_run_end_round_trip():
    for v in ("passed", "failed", "partial", "n_a", "skipped"):
        s = SkillRunEnd(
            skill_name="security-review", verdict=v,  # type: ignore[arg-type]
            duration_ms=500, finding_count=3, error_count=0, cwd="/tmp/ws", timestamp_ms=99999,
        )
        blob = serialize_event(s)  # type: ignore[arg-type]
        restored = deserialize_event(blob)
        assert isinstance(restored, SkillRunEnd)
        assert restored.verdict == v
        assert restored.finding_count == 3


def test_event_kind_union_includes_skill_events():
    assert "skill_run_start" in EventKind.__args__  # type: ignore[attr-defined]
    assert "skill_run_end" in EventKind.__args__  # type: ignore[attr-defined]
    assert _KIND_TO_CLASS["skill_run_start"] is SkillRunStart
    assert _KIND_TO_CLASS["skill_run_end"] is SkillRunEnd


def test_event_union_includes_skill_events():
    s: Event = SkillRunStart(skill_name="x", args={})  # type: ignore[assignment]
    e: Event = SkillRunEnd(skill_name="x", verdict="passed", duration_ms=0, finding_count=0, error_count=0)  # type: ignore[assignment]
    assert s.kind == "skill_run_start"
    assert e.kind == "skill_run_end"


def test_deserialize_unknown_kind_raises():
    with pytest.raises(ValueError, match="unknown event kind"):
        deserialize_event(json.dumps({"kind": "bogus", "data": {}}))
