"""Internal documentation."""
from __future__ import annotations

from pathlib import Path

import pytest

from argos.daemon.manager import RunManager
from argos.daemon.worker import FakeLoop, RunWorker



def test_status_bar_count_badges_active_paused_history():
    """Internal documentation."""
    from argos.tui.widgets.status_bar import StatusBar
    bar = StatusBar()
    runs = [
        ("a", "running"),
        ("b", "paused"),
        ("c", "paused"),
        ("d", "suspended"),
        ("e", "completed"),
    ]
    text = bar.render_count_badges(runs)
    assert "⏵1" in text   # 1 active
    assert "⏸2" in text   # 2 paused
    assert "⏹2" in text   # suspended + completed = 2 history


def test_status_bar_count_badges_empty():
    """Internal documentation."""
    from argos.tui.widgets.status_bar import StatusBar
    bar = StatusBar()
    assert bar.render_count_badges([]) == ""
    assert "⏵" not in bar.render_text


def test_status_bar_run_summary_not_in_text_after_dedup():
    """Internal documentation."""
    from argos.tui.widgets.status_bar import StatusBar
    bar = StatusBar()
    bar.set_run_summary([("a", "running"), ("b", "paused")])
    text = bar.render_text
    assert "⏵" not in text and "⏸" not in text



def test_activity_panel_run_section_idx_exists():
    """Internal documentation."""
    from argos.tui.widgets.activity_panel import ActivityPanel
    assert ActivityPanel._RUN_IDX == 4


def test_activity_panel_run_section_text_format():
    """Internal documentation."""
    from argos.tui.widgets.activity_panel import ActivityPanel
    panel = ActivityPanel()
    captured = {}
    panel._set = lambda idx, body: captured.setdefault(idx, body)  # type: ignore[method-assign]
    panel.on_run_summary(active=2, paused=1, suspended=3, history=5)
    assert "⏵2" in captured[4]
    assert "⏸1" in captured[4]
    assert "⏹5" in captured[4]   # history (suspended+completed+failed+cancelled)
    assert "suspended 3" in captured[4]


def test_activity_panel_run_section_empty():
    """Internal documentation."""
    from argos.tui.widgets.activity_panel import ActivityPanel
    panel = ActivityPanel()
    captured = {}
    panel._set = lambda idx, body: captured.setdefault(idx, body)  # type: ignore[method-assign]
    panel.on_run_summary(active=0, paused=0, suspended=0, history=0)
    assert captured[4] == "◌ (无)"



def test_runs_command_in_command_help():
    """Internal documentation."""
    from argos.tui.commands import COMMAND_HELP
    assert "runs" in COMMAND_HELP
    assert "daemon" in COMMAND_HELP["runs"].lower()


def test_parse_slash_runs():
    """Internal documentation."""
    from argos.tui.commands import parse_slash
    cmd = parse_slash("/runs abc123def456 resume")
    assert cmd is not None
    assert cmd.name == "runs"
    assert cmd.arg == "abc123def456 resume"
    assert cmd.known is True



def test_ctrl_b_marks_suspended(tmp_path: Path):
    """Internal documentation."""
    import asyncio
    async def _go():
        mgr = RunManager(runs_dir=tmp_path / "runs", index_path=tmp_path / "index.json")
        rid = await mgr.create_run(goal="x", workspace="/tmp")
        mgr.mark_running(rid)
        mgr.mark_suspended(rid, last_step=0, msg_count=0, last_event_seq=0)
        assert mgr.get_run(rid).state == "suspended"
        events = list(mgr.store.replay(rid))
        assert any(e.get("kind") == "run_checkpoint" for e in events)
        assert any(e.get("kind") == "state_change" and e.get("to") == "suspended"
                   for e in events)
    asyncio.run(_go())



def test_double_esc_detection_window(monkeypatch):
    """Internal documentation."""
    import time
    last = 0.0
    now1 = 1000.0
    is_double1 = (now1 - last) < 1.5
    assert is_double1 is False
    last = now1
    now2 = 1000.5
    is_double2 = (now2 - last) < 1.5
    assert is_double2 is True



def test_resume_modal_data_format(tmp_path: Path):
    """Internal documentation."""
    import asyncio
    import time as _t

    async def _go():
        mgr = RunManager(runs_dir=tmp_path / "runs", index_path=tmp_path / "index.json")
        rid = await mgr.create_run(goal="refactor auth.py", workspace="/tmp")
        mgr.mark_running(rid)
        mgr.mark_suspended(rid, last_step=5, msg_count=10, last_event_seq=15)
        runs = mgr.list_runs(state="suspended")
        assert len(runs) == 1
        r = runs[0]
        assert r["state"] == "suspended"
        assert r["goal"] == "refactor auth.py"
        assert r["run_id"] == rid
    asyncio.run(_go())



def test_bindings_contain_ctrl_b():
    """Internal documentation."""
    from argos.tui.app import ArgosApp

    def _key(binding):
        return binding.key if hasattr(binding, "key") else binding[0]

    def _action(binding):
        return binding.action if hasattr(binding, "action") else binding[1]

    bindings = [b for b in ArgosApp.BINDINGS if _key(b) == "ctrl+b"]
    assert bindings
    assert _action(bindings[0]) == "background"
