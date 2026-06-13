"""#10 防 O(n²):update_plan / propose_workflow 的括号配平扫描钳 64KB 窗口。

bug:对每个 `update_plan(` / `propose_workflow(` 匹配,内层 while 从实参起点扫到文末做括号
配平;若模型输出大量未配平的调用,每个都扫到文末 → O(N × len) 二次方,阻塞事件循环
(实测 4000 次 ~16s)。修法:单次配平扫描钳 64KB 窗口,超窗口视为未配平跳过(正常 todos /
workflow spec 远小于 64KB,不受影响)。
"""
from __future__ import annotations

from argos.core.loop import extract_plan_todos, extract_workflow_spec


def test_extract_plan_todos_normal_still_parses():
    text = "update_plan([{'content': 'a', 'status': 'pending', 'activeForm': 'a'}])"
    out = extract_plan_todos(text)
    assert out is not None and out[0]["content"] == "a"


def test_extract_plan_todos_caps_scan_window():
    # 配平的 ) 落在 64KB 窗口外 → 钳制视为未配平,返回 None(防二次方扫描卡事件循环)。
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
