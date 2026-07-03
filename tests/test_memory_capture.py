"""Internal documentation."""
from __future__ import annotations

import time

import pytest

from argos.memory import auto as mem_auto


@pytest.fixture
def mem_root(monkeypatch, tmp_path):
    root = tmp_path / "memory"
    monkeypatch.setenv("ARGOS_MEMORY_DIR", str(root))
    yield root


def test_capture_escalation_decision_writes_to_project(mem_root, tmp_path):
    pid = mem_auto.project_id_for(tmp_path)
    e = mem_auto.capture_event("escalation_decision", project_id=pid,
                               reason="用户选了 retry",
                               user_reply="retry")
    assert e is not None
    assert e.scope == "project"
    assert e.type == "decision"
    assert e.confidence == 0.9
    assert "用户选了 retry" in e.value


def test_capture_verify_fail_includes_cmd(mem_root, tmp_path):
    pid = mem_auto.project_id_for(tmp_path)
    e = mem_auto.capture_event("verify_fail", project_id=pid,
                               cmd="pytest -q",
                               stderr_hash="abc123",
                               stderr_snippet="FAILED tests/test_x.py::test_y")
    assert e is not None
    assert e.type == "failure"
    assert e.scope == "project"
    assert "pytest -q" in e.value


def test_capture_tool_repeat_fail_requires_3(mem_root, tmp_path):
    """Internal documentation."""
    pid = mem_auto.project_id_for(tmp_path)
    # 1st fail
    e1 = mem_auto.capture_event("tool_repeat_fail", project_id=pid,
                                tool="run_shell", error="err1")
    assert e1 is None
    # 2nd fail
    e2 = mem_auto.capture_event("tool_repeat_fail", project_id=pid,
                                tool="run_shell", error="err2")
    assert e2 is None
    # 3rd fail
    e3 = mem_auto.capture_event("tool_repeat_fail", project_id=pid,
                                tool="run_shell", error="err3")
    assert e3 is not None
    assert e3.type == "failure"


def test_capture_run_success_writes_only_over_5_steps(mem_root, tmp_path):
    pid = mem_auto.project_id_for(tmp_path)
    e_short = mem_auto.capture_event("run_success", project_id=pid,
                                    goal="修 bug", steps=4,
                                    key_cmd="pytest -q")
    assert e_short is None
    e_ok = mem_auto.capture_event("run_success", project_id=pid,
                                  goal="修 bug", steps=6,
                                  key_cmd="pytest -q")
    assert e_ok is not None
    assert e_ok.type == "fact"
    assert "修 bug" in e_ok.value


def test_capture_undo(mem_root, tmp_path):
    pid = mem_auto.project_id_for(tmp_path)
    e = mem_auto.capture_event("undo", project_id=pid, reason="改坏了")
    assert e is not None
    assert e.type == "convention"
    assert e.scope == "project"


def test_capture_redacts_secrets_before_write(mem_root, tmp_path):
    pid = mem_auto.project_id_for(tmp_path)
    e = mem_auto.capture_event("verify_fail", project_id=pid,
                               cmd="curl -H 'Authorization: Bearer ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmn'",
                               stderr_hash="h", stderr_snippet="")
    assert e is not None
    assert "ABCDEFGHIJKLMNOP" not in e.value
    assert "<redacted" in e.value or "***" in e.value


def test_capture_dedups_24h_same_key_value(mem_root, tmp_path):
    pid = mem_auto.project_id_for(tmp_path)
    e1 = mem_auto.capture_event("undo", project_id=pid, reason="改坏了")
    e2 = mem_auto.capture_event("undo", project_id=pid, reason="改坏了")
    assert e1 is not None
    assert e2 is None


def test_capture_updates_value_when_changed(mem_root, tmp_path):
    pid = mem_auto.project_id_for(tmp_path)
    e1 = mem_auto.capture_event("undo", project_id=pid, reason="原因 A")
    e2 = mem_auto.capture_event("undo", project_id=pid, reason="原因 B")
    assert e1 is not None
    assert e2 is not None


def test_capture_returns_none_when_unknown_kind(mem_root, tmp_path):
    pid = mem_auto.project_id_for(tmp_path)
    e = mem_auto.capture_event("totally_made_up_event", project_id=pid)
    assert e is None


# ── task_reflection ──────────────────────────────────────────────────────────
def test_capture_task_reflection_persists(tmp_path, monkeypatch):
    """Internal documentation."""
    monkeypatch.setenv("ARGOS_MEMORY_DIR", str(tmp_path))
    from argos.memory import auto
    entry = auto.capture_event(
        "task_reflection",
        project_id="proj1",
        run_id="run123",
        goal="fix the login bug",
        verify_cmd="pytest -q",
        verdict="failed",
        self_verified=False,
        last_exc_snippet="AssertionError: boom",
    )
    assert entry is not None
    assert entry.type == "failure"
    assert entry.scope == "project"
    assert entry.key == "reflection.run123"
    assert "fix the login bug" in entry.value
    assert "failed" in entry.value
    assert "AssertionError: boom" in entry.value


def test_capture_task_reflection_self_verified_tagged(tmp_path, monkeypatch):
    """Internal documentation."""
    monkeypatch.setenv("ARGOS_MEMORY_DIR", str(tmp_path))
    from argos.memory import auto
    entry = auto.capture_event(
        "task_reflection", project_id="proj1", run_id="run456", goal="g",
        verdict="passed", self_verified=True,
    )
    assert entry is not None
    assert "[self_verified]" in entry.value


def test_capture_tool_repeat_fail_isolates_by_tool(mem_root, tmp_path):
    """Internal documentation."""
    pid = mem_auto.project_id_for(tmp_path)
    for i in range(2):
        mem_auto.capture_event("tool_repeat_fail", project_id=pid,
                               tool="run_shell", error=f"e{i}")
    for i in range(2):
        mem_auto.capture_event("tool_repeat_fail", project_id=pid,
                               tool="read_file", error=f"e{i}")
    e = mem_auto.capture_event("tool_repeat_fail", project_id=pid,
                               tool="run_shell", error="e3")
    assert e is not None
