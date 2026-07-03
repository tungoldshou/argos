"""Internal documentation."""
from __future__ import annotations

from argos.tui.events import PlanUpdate, deserialize_event, serialize_event


def test_plan_update_event_roundtrip():
    ev = PlanUpdate(todos=[{"content": "读文件", "status": "completed", "activeForm": "读文件中"},
                           {"content": "修 bug", "status": "in_progress", "activeForm": "修 bug 中"}])
    d = serialize_event(ev)
    back = deserialize_event(d)
    assert isinstance(back, PlanUpdate)
    assert back.todos[1]["status"] == "in_progress"
