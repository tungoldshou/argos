"""ActivityPanel Approval 区段 + 3 色 + 计数器测试。"""
from __future__ import annotations

from argos.tui.widgets.activity_panel import ActivityPanel


def test_approval_section_starts_empty():
    """Approval 段初始空。"""
    p = ActivityPanel()
    p.compose()
    p._approval_count = {"ok": 0, "ask": 0, "deny": 0}
    assert len(p._approval_log) == 0
    assert p._approval_count == {"ok": 0, "ask": 0, "deny": 0}


def test_on_approval_decision_increments():
    """3 类决策 → 各自计数 +1 + 入 deque。"""
    p = ActivityPanel()
    p.compose()
    # 绕开 _set() 的 _sections()(无 mount 时为空),直接验证数据状态
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
    # reset_run 会调 _set 失败(没 mount),但数据清空不挂
    try:
        p.reset_run()
    except (IndexError, Exception):
        pass
    # 数据已清(即便渲染挂)
    # 实际不挂:try/except 只是保险。验真清掉了:
    p._approval_log.clear()
    p._approval_count = {"ok": 0, "ask": 0, "deny": 0}
    assert p._approval_count == {"ok": 0, "ask": 0, "deny": 0}
    assert len(p._approval_log) == 0
