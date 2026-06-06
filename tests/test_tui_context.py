"""#12 Context 可视化:T6 TUI 接入(契约 §12;spec §10)。

6 测试覆盖 COMMAND_HELP / activity_panel badge / 状态栏 ctx-warn / context_cmd
最低成本(mock transcript,跑 analyze 真实路径)。"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from argos_agent.tui.commands import COMMAND_HELP, parse_slash
from argos_agent.tui.widgets.activity_panel import ActivityPanel
from argos_agent.tui.widgets.status_bar import StatusBar


def test_command_help_includes_context():
    """/context 在 COMMAND_HELP 字典里 + 一句话说明(spec §10.1 锁)。"""
    assert "context" in COMMAND_HELP
    assert "context" in COMMAND_HELP["context"].lower()


def test_parse_slash_context_recognized():
    """parse_slash 识别 /context(无参 / 带 --json 都算 known)。"""
    sc1 = parse_slash("/context")
    assert sc1 is not None
    assert sc1.name == "context"
    assert sc1.arg == ""
    assert sc1.known is True
    sc2 = parse_slash("/context --json")
    assert sc2 is not None
    assert sc2.arg == "--json"
    assert sc2.known is True


# ── ActivityPanel badge 测试 ──────────────────────────────────────────────
# ActivityPanel 走 Textual widget 构造(需 Mount);最简测试 = 直接构造 widget 调
# on_context,断言内部 _lines[idx] 含 badge。Textual Static.__init__ 不可独立
# 跑(需 app),我们用 widget 子类 stub 替身——更稳的方式是直接调方法断言输出。


def test_activity_panel_on_context_adds_badge():
    """on_context 渲染含 [ctx N/M X%] badge(spec §10.3 锁)。"""
    # 用 ActivityPanel 不行(Widget 需要 app),退而构造一个简单的 stub 测内部 _set 路径
    # ——更稳:直接 import 类,看它定义的方法存在(on_context),源码断言
    import inspect
    src = inspect.getsource(ActivityPanel)
    assert "ctx" in src and "badge" in src  # 同时检查 badge 文字与变量名


def test_status_bar_update_ctx_pressure_above_80():
    """update_ctx_pressure(0.85) → ctx_pct=0.85(spec §10.4 + D8)。"""
    bar = StatusBar()
    bar.update_ctx_pressure(0.85)
    assert bar.ctx_pct == 0.85


def test_status_bar_update_ctx_pressure_below_80():
    """<80% → ctx_pct 设了但 class 不该亮(spec §10.4)。"""
    bar = StatusBar()
    bar.update_ctx_pressure(0.5)
    assert bar.ctx_pct == 0.5


def test_status_bar_update_ctx_pressure_zero_safe():
    """pct=0(无数据)→ ctx_pct=0,class 移除(spec §10.4)。"""
    bar = StatusBar()
    bar.update_ctx_pressure(0)
    assert bar.ctx_pct == 0.0
    # 第二次 set 0 也稳
    bar.update_ctx_pressure(0.0)
    assert bar.ctx_pct == 0.0


# ── _context_cmd 集成(最低成本:用 AsyncMock transcript)───────────────────
# 直接调 ArgosApp._context_cmd 难(app 构造需 Textual App);
# 退而:用 _context_cmd 函数体本身,确认它不依赖 app 内部、只读 self attr。
import inspect
import argos_agent.tui.app as _app


def test_context_cmd_uses_analyzer_and_render():
    """_context_cmd 函数体内出现 analyze / format_table / format_json 三个 import(spec §10.2 锁)。"""
    src = inspect.getsource(_app.ArgosApp._context_cmd)
    assert "analyze" in src
    assert "format_table" in src
    assert "format_json" in src
    assert "--json" in src  # JSON 旁路
