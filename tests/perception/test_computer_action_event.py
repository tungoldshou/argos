from __future__ import annotations

import json

import pytest

import argos.protocol.events as PE



def _round(ev):
    blob = PE.serialize_event(ev)
    back = PE.deserialize_event(blob)
    assert type(back) is type(ev), f"类型不匹配:{type(back)} vs {type(ev)}"
    return back


def _make_event(**kwargs) -> PE.ComputerActionEvent:
    defaults = dict(
        kind_action="screenshot",
        x=None,
        y=None,
        text_preview="",
        ok=True,
        detail="截图已保存至 /tmp/argos_screen_test.png",
        artifact_path="/tmp/argos_screen_test.png",
    )
    defaults.update(kwargs)
    return PE.ComputerActionEvent(**defaults)



def test_computer_action_event_golden_screenshot():
    ev = _make_event()
    obj = json.loads(PE.serialize_event(ev))
    assert obj["kind"] == "computer_action"
    data = obj["data"]
    assert data["kind_action"] == "screenshot"
    assert data["x"] is None
    assert data["y"] is None
    assert data["text_preview"] == ""
    assert data["ok"] is True
    assert "截图" in data["detail"]
    assert data["artifact_path"] == "/tmp/argos_screen_test.png"


def test_computer_action_event_golden_click():
    ev = _make_event(
        kind_action="click",
        x=100,
        y=200,
        text_preview="",
        ok=True,
        detail="点击 (100, 200) 成功",
        artifact_path=None,
    )
    obj = json.loads(PE.serialize_event(ev))
    data = obj["data"]
    assert data["kind_action"] == "click"
    assert data["x"] == 100
    assert data["y"] == 200
    assert data["ok"] is True


def test_computer_action_event_golden_failure():
    ev = _make_event(
        kind_action="type_text",
        x=None,
        y=None,
        text_preview="hello wor…",
        ok=False,
        detail="系统拒绝了辅助功能访问请求。请前往系统设置授权。",
        artifact_path=None,
    )
    obj = json.loads(PE.serialize_event(ev))
    data = obj["data"]
    assert data["ok"] is False
    assert data["text_preview"] == "hello wor…"
    assert "辅助功能" in data["detail"]


# ── Round-trip ────────────────────────────────────────────────────────────────

def test_computer_action_event_roundtrip_screenshot():
    ev = _make_event()
    back = _round(ev)
    assert back.kind_action == "screenshot"
    assert back.ok is True
    assert back.artifact_path == "/tmp/argos_screen_test.png"
    assert back.x is None and back.y is None


def test_computer_action_event_roundtrip_click():
    ev = _make_event(
        kind_action="click", x=50, y=75,
        text_preview="", ok=True,
        detail="点击成功", artifact_path=None,
    )
    back = _round(ev)
    assert back.x == 50 and back.y == 75
    assert back.kind_action == "click"


def test_computer_action_event_roundtrip_failure():
    ev = _make_event(
        kind_action="type_text", x=None, y=None,
        text_preview="hi…", ok=False,
        detail="权限拒绝", artifact_path=None,
    )
    back = _round(ev)
    assert back.ok is False
    assert back.text_preview == "hi…"
    assert back.detail == "权限拒绝"


def test_computer_action_event_roundtrip_all_kinds():
    for kind_action in ("screenshot", "click", "double_click",
                         "type_text", "key", "scroll", "open_app"):
        ev = _make_event(kind_action=kind_action)
        back = _round(ev)
        assert back.kind_action == kind_action



def test_computer_action_in_kind_to_class():
    assert "computer_action" in PE._KIND_TO_CLASS
    assert PE._KIND_TO_CLASS["computer_action"] is PE.ComputerActionEvent


def test_computer_action_in_event_kind_literal():
    assert "computer_action" in PE.EventKind.__args__


def test_computer_action_event_is_frozen():
    ev = _make_event()
    with pytest.raises((AttributeError, TypeError)):
        ev.ok = False  # type: ignore[misc]


def test_computer_action_event_kind_constant():
    assert PE.ComputerActionEvent.kind == "computer_action"



def test_text_preview_truncation_convention():
    long_text = "a" * 100
    preview = long_text[:80]
    ev = _make_event(
        kind_action="type_text",
        text_preview=preview,
        ok=True,
        detail="键入成功",
        artifact_path=None,
    )
    obj = json.loads(PE.serialize_event(ev))
    assert obj["data"]["text_preview"] == preview
    assert len(obj["data"]["text_preview"]) == 80



def test_tui_events_shim_exports_computer_action_event():
    from argos.tui import events as E  # noqa: PLC0415
    assert hasattr(E, "ComputerActionEvent"), (
        "tui/events.py shim 未导出 ComputerActionEvent —— 需要在 shim 中加入 re-export"
    )
    assert E.ComputerActionEvent is PE.ComputerActionEvent
