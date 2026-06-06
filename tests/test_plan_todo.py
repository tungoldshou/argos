"""Task 12:`update_plan` 工具 + `PlanUpdate` 事件 + ActivityPanel todo 渲染。

PlanUpdate 走"一份事件三用":序列化/反序列化 round-trip(持久化 + replay)必须完好。
"""
from __future__ import annotations

from argos_agent.tui.events import PlanUpdate, deserialize_event, serialize_event


def test_plan_update_event_roundtrip():
    ev = PlanUpdate(todos=[{"content": "读文件", "status": "completed", "activeForm": "读文件中"},
                           {"content": "修 bug", "status": "in_progress", "activeForm": "修 bug 中"}])
    d = serialize_event(ev)
    back = deserialize_event(d)
    assert isinstance(back, PlanUpdate)
    assert back.todos[1]["status"] == "in_progress"
