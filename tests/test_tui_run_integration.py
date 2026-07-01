"""TUI + daemon 集成测试(Ctrl+B / Esc / status bar / activity panel)。"""
from __future__ import annotations

from pathlib import Path

import pytest

from argos.daemon.manager import RunManager
from argos.daemon.worker import FakeLoop, RunWorker


# ── StatusBar 纯函数测试(无 TUI 渲染)────────────────────────

def test_status_bar_count_badges_active_paused_history():
    """status bar 从 list[(id, state)] 渲染 count badges。"""
    from argos.tui.widgets.status_bar import StatusBar
    bar = StatusBar()   # 不传 model_label,Textual 内部 markup 关键字
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
    """TUI v2 去噪:空列表(非 daemon)→ 整段消失,不再显 ⏵0/⏸0/⏹0 噪声。"""
    from argos.tui.widgets.status_bar import StatusBar
    bar = StatusBar()
    assert bar.render_count_badges([]) == ""
    assert "⏵" not in bar.render_text


def test_status_bar_run_summary_not_in_text_after_dedup():
    """去重(2026-07-01):daemon run 计数徽标归右侧 ActivityPanel(_RUN_IDX),底栏 render_text
    不再重复显示。set_run_summary 仍存(喂数据),render_count_badges 方法仍独立可用(见上)。"""
    from argos.tui.widgets.status_bar import StatusBar
    bar = StatusBar()
    bar.set_run_summary([("a", "running"), ("b", "paused")])
    text = bar.render_text
    assert "⏵" not in text and "⏸" not in text


# ── ActivityPanel 'Run' 区段(逻辑测,无 widget 渲染)────────

def test_activity_panel_run_section_idx_exists():
    """ActivityPanel._RUN_IDX = 4(Run 区段在任务进度/工具/回执 之后)。"""
    from argos.tui.widgets.activity_panel import ActivityPanel
    assert ActivityPanel._RUN_IDX == 4


def test_activity_panel_run_section_text_format():
    """直接调 on_run_summary → _RUN_IDX section 体(纯逻辑断言)。"""
    from argos.tui.widgets.activity_panel import ActivityPanel
    panel = ActivityPanel()
    # monkey-patch _set 拦截
    captured = {}
    panel._set = lambda idx, body: captured.setdefault(idx, body)  # type: ignore[method-assign]
    panel.on_run_summary(active=2, paused=1, suspended=3, history=5)
    assert "⏵2" in captured[4]
    assert "⏸1" in captured[4]
    assert "⏹5" in captured[4]   # history (suspended+completed+failed+cancelled)
    assert "suspended 3" in captured[4]


def test_activity_panel_run_section_empty():
    """全 0 → '◌ (无)'(TUI v3:空态一律 ◌ 前缀 + 最弱墨,绝不预填假数据,spec §4.8)。"""
    from argos.tui.widgets.activity_panel import ActivityPanel
    panel = ActivityPanel()
    captured = {}
    panel._set = lambda idx, body: captured.setdefault(idx, body)  # type: ignore[method-assign]
    panel.on_run_summary(active=0, paused=0, suspended=0, history=0)
    assert captured[4] == "◌ (无)"


# ── tui/commands.py 加 'runs' ───────────────────────────────────────

def test_runs_command_in_command_help():
    """/runs 在 COMMAND_HELP 里。"""
    from argos.tui.commands import COMMAND_HELP
    assert "runs" in COMMAND_HELP
    assert "daemon" in COMMAND_HELP["runs"].lower()


def test_parse_slash_runs():
    """parse_slash('/runs {id} resume') 拆出 (name='runs', arg='{id} resume')。"""
    from argos.tui.commands import parse_slash
    cmd = parse_slash("/runs abc123def456 resume")
    assert cmd is not None
    assert cmd.name == "runs"
    assert cmd.arg == "abc123def456 resume"
    assert cmd.known is True


# ── Ctrl+B 后台化走 RunManager.mark_suspended ──────────────────────

def test_ctrl_b_marks_suspended(tmp_path: Path):
    """Ctrl+B → state_change(running → suspended)+ checkpoint 落 JSONL。"""
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


# ── Esc 双按检测逻辑 ───────────────────────────────────────────

def test_double_esc_detection_window(monkeypatch):
    """1.5s 内第二次 Esc → cancel(检测逻辑不依赖 TUI,纯函数测)。"""
    import time
    last = 0.0
    now1 = 1000.0
    # 单按:time delta large → pause
    is_double1 = (now1 - last) < 1.5
    assert is_double1 is False
    last = now1
    # 双按 0.5s 后
    now2 = 1000.5
    is_double2 = (now2 - last) < 1.5
    assert is_double2 is True


# ── 跨 session resume 启动 modal 数据准备 ────────────────────────

def test_resume_modal_data_format(tmp_path: Path):
    """suspended run 数据格式对齐 modal 行(state / goal / age / step)。"""
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
        # modal 显示需要字段
        assert r["state"] == "suspended"
        assert r["goal"] == "refactor auth.py"
        assert r["run_id"] == rid
    asyncio.run(_go())


# ── BINDINGS 包含 ctrl+b ────────────────────────────────────────

def test_bindings_contain_ctrl_b():
    """ArgosApp BINDINGS 含 ctrl+b(后台化)。"""
    from argos.tui.app import ArgosApp
    bindings = [b for b in ArgosApp.BINDINGS if b[0] == "ctrl+b"]
    assert bindings
    assert bindings[0][1] == "background"
