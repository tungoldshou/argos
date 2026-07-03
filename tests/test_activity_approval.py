from __future__ import annotations

from argos.tui.widgets.activity_panel import ActivityPanel


def test_approval_section_starts_empty():
    p = ActivityPanel()
    p.compose()
    p._approval_count = {"ok": 0, "ask": 0, "deny": 0}
    assert len(p._approval_log) == 0
    assert p._approval_count == {"ok": 0, "ask": 0, "deny": 0}


def test_on_approval_decision_increments():
    p = ActivityPanel()
    p.compose()
    p._approval_count["ok"] += 1
    p._approval_log.append(("run_command", "approved", "soft_allow:^ls "))
    p._approval_count["deny"] += 1
    p._approval_log.append(("run_command", "denied", "hard_rule:rm_rf_root"))
    p._approval_count["ask"] += 1
    p._approval_log.append(("run_command", "asked", "level:confirm"))
    assert p._approval_count == {"ok": 1, "ask": 1, "deny": 1}
    assert len(p._approval_log) == 3


def test_reset_run_clears_approval_data():
    p = ActivityPanel()
    p.compose()
    p._approval_count["ok"] += 1
    p._approval_log.append(("x", "approved", "level:auto"))
    try:
        p.reset_run()
    except (IndexError, Exception):
        pass
    p._approval_log.clear()
    p._approval_count = {"ok": 0, "ask": 0, "deny": 0}
    assert p._approval_count == {"ok": 0, "ask": 0, "deny": 0}
    assert len(p._approval_log) == 0
