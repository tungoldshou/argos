from __future__ import annotations

from argos.core.loop import extract_plan_todos, extract_workflow_spec


def test_extract_plan_todos_normal_still_parses():
    text = "update_plan([{'content': 'a', 'status': 'pending', 'activeForm': 'a'}])"
    out = extract_plan_todos(text)
    assert out is not None and out[0]["content"] == "a"


def test_extract_plan_todos_caps_scan_window():
    pad = "'" + "a" * 70000 + "'"
    text = "update_plan([{'content': " + pad + ", 'status': 'p', 'activeForm': 'x'}])"
    assert extract_plan_todos(text) is None


def test_extract_workflow_spec_normal_still_parses():
    text = "propose_workflow({'name': 'w', 'stages': []})"
    out = extract_workflow_spec(text)
    assert out is not None and out["name"] == "w"


def test_extract_workflow_spec_caps_scan_window():
    pad = "'" + "a" * 70000 + "'"
    text = "propose_workflow({'name': " + pad + "})"
    assert extract_workflow_spec(text) is None
