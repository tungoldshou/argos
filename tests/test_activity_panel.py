import pytest
from textual.app import App, ComposeResult
from argos_agent.tui.widgets.activity_panel import ActivityPanel
from argos_agent.core.types import ModelTierName  # noqa


class _H(App):
    def compose(self) -> ComposeResult:
        yield ActivityPanel(id="ap", model_label="MiniMax-M3", tier="worker")


@pytest.mark.asyncio
async def test_panel_sections_present_and_honest_empty():
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        ap = app.query_one("#ap", ActivityPanel)
        txt = ap.snapshot_text()
        assert "MiniMax-M3" in txt                              # 模型(真,只显模型名不露档位)
        # Skills 已接进活 loop:诚实显真实可用数(内置 4 个)或"无可用",绝不谎报。
        assert ("可用" in txt or "无可用" in txt)
        # MCP 诚实显配置态:'未配置'(零预配)或 'N 个已配置';绝不谎报连接数。
        assert ("未配置" in txt or "已配置" in txt)
        assert "缓存" in txt                                      # 成本含缓存区


@pytest.mark.asyncio
async def test_phase_timeline_accumulates():
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        ap = app.query_one("#ap", ActivityPanel)
        ap.on_phase("plan", 0)
        ap.on_phase("act", 1)
        await pilot.pause()
        assert "plan" in ap.snapshot_text() and "act" in ap.snapshot_text()


@pytest.mark.asyncio
async def test_receipt_and_cost_update():
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        ap = app.query_one("#ap", ActivityPanel)
        ap.on_receipt("write_file")
        ap.on_cost(tokens_in=12400, tokens_out=3100, cost_usd=0.013, elapsed_s=4.2, cache_read=179)
        await pilot.pause()
        t = ap.snapshot_text()
        assert "write_file" in t           # 工具计数 + 回执
        assert "179" in t                  # 缓存命中


@pytest.mark.asyncio
async def test_model_section_shows_name_not_tier():
    app = _H()  # _H 已在该文件:yield ActivityPanel(id="ap", model_label="MiniMax-M3", tier="worker")
    async with app.run_test() as pilot:
        await pilot.pause()
        ap = app.query_one("#ap", ActivityPanel)
        txt = ap.snapshot_text()
        assert "MiniMax-M3" in txt, "应显示真实模型名"
        assert "档位" not in txt and "worker" not in txt, "不得暴露内部档位/tier 概念"


@pytest.mark.asyncio
async def test_cost_unknown_shows_na_not_zero():
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        ap = app.query_one("#ap", ActivityPanel)
        ap.on_cost(tokens_in=100, tokens_out=50, cost_usd=None, elapsed_s=1.0, cache_read=0)
        await pilot.pause()
        t = ap.snapshot_text()
        assert "N/A" in t, "单价未知应显 $(N/A)"
        assert "$0.000" not in t


@pytest.mark.asyncio
async def test_context_section_shows_usage_bar():
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        ap = app.query_one("#ap", ActivityPanel)
        ap.on_context(used=50000, window=200000)  # 25%
        await pilot.pause()
        t = ap.snapshot_text()
        assert "25%" in t
        assert "上下文" in t


@pytest.mark.asyncio
async def test_panel_is_scrollable():
    """修复:活动栏内容超出可视高度时必须可滚(overflow-y: auto);
    此前继承 Vertical 默认 overflow-y: hidden,区块被裁死、滚轮/拖拽全失效。"""
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        ap = app.query_one("#ap", ActivityPanel)
        assert ap.styles.overflow_y == "auto", \
            f"活动栏应 overflow-y: auto 才能滚动,实际 {ap.styles.overflow_y}"


@pytest.mark.asyncio
async def test_section_title_not_transparent():
    """修复:区块标题此前 border-title-color 落到透明默认(alpha=0)完全看不见;
    须为不透明可读色($foreground)。"""
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        ap = app.query_one("#ap", ActivityPanel)
        c = ap._sections()[0].styles.border_title_color
        assert c is not None and c.a > 0, f"区块标题颜色不得透明(alpha=0),实际 {c!r}"


@pytest.mark.asyncio
async def test_in_progress_phase_shows_ellipsis_not_zero():
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        ap = app.query_one("#ap", ActivityPanel)
        ap.on_phase("plan", 0)  # 刚进 plan,进行中
        await pilot.pause()
        # Textual 8.2.7 的 Static 用 .content 暴露正文(无 .renderable)
        sec = str(ap._sections()[1].content)  # 任务进度区
        assert "0.0s" not in sec, "进行中阶段不应显 0.0s"
        assert "…" in sec, "进行中阶段应显占位 …"


# ── Hooks(spec §2.4):ActivityPanel 'Hook' 区段 + 3 态渲染 + deque 50 ───────────
@pytest.mark.asyncio
async def test_activity_panel_has_hook_section():
    """ActivityPanel.compose 含 'Hook' 区段(标题)。"""
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        ap = app.query_one("#ap", ActivityPanel)
        titles = [getattr(s, "border_title", "") for s in ap._sections()]
        assert "Hook" in titles


@pytest.mark.asyncio
async def test_activity_panel_on_hook_fired_ok():
    """on_hook_fired(success=True) → 区段体含 'ok' / 命令名。"""
    from argos_agent.hooks.events import HookFired
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        ap = app.query_one("#ap", ActivityPanel)
        ev = HookFired(event_name="PreToolUse", command="echo ok",
                       success=True, returncode=0, elapsed_ms=130)
        ap.on_hook_fired(ev)
        snap = ap.snapshot_text()
        assert "PreToolUse" in snap
        assert "echo" in snap
        assert "ok" in snap


@pytest.mark.asyncio
async def test_activity_panel_on_hook_fired_fail_red():
    """on_hook_fired(success=False, returncode=2) → 显 fail 红色标记(行内含 'fail' 或 'exit 2')。"""
    from argos_agent.hooks.events import HookFired
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        ap = app.query_one("#ap", ActivityPanel)
        ev = HookFired(event_name="PostToolUse", command="false",
                       success=False, returncode=2, elapsed_ms=80)
        ap.on_hook_fired(ev)
        snap = ap.snapshot_text()
        assert "exit 2" in snap or "fail" in snap.lower()


@pytest.mark.asyncio
async def test_activity_panel_on_hook_fired_timeout():
    """on_hook_fired(timed_out=True) → 显 timeout 标记。"""
    from argos_agent.hooks.events import HookFired
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        ap = app.query_one("#ap", ActivityPanel)
        ev = HookFired(event_name="PreToolUse", command="sleep 5",
                       success=False, returncode=None, elapsed_ms=200, timed_out=True)
        ap.on_hook_fired(ev)
        snap = ap.snapshot_text()
        assert "timeout" in snap.lower()


@pytest.mark.asyncio
async def test_activity_panel_hook_deque_caps_at_50():
    """on_hook_fired 触发 60 次 → deque 最多 50 条(最近 50)。"""
    from argos_agent.hooks.events import HookFired
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        ap = app.query_one("#ap", ActivityPanel)
        for i in range(60):
            ev = HookFired(
                event_name="PostToolUse", command=f"cmd{i}",
                success=True, returncode=0, elapsed_ms=10,
            )
            ap.on_hook_fired(ev)
        # 内部 _hook_log 是 deque(maxlen=50)
        assert len(ap._hook_log) == 50


@pytest.mark.asyncio
async def test_activity_panel_reset_run_clears_hook_log():
    """reset_run 清空 hook log(每轮独立)。"""
    from argos_agent.hooks.events import HookFired
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        ap = app.query_one("#ap", ActivityPanel)
        ev = HookFired(event_name="PreToolUse", command="x",
                       success=True, returncode=0, elapsed_ms=10)
        ap.on_hook_fired(ev)
        assert len(ap._hook_log) == 1
        ap.reset_run()
        assert len(ap._hook_log) == 0


# ── LSP(spec 2026-06-06 §2.7)────────────────────────────────────────
@pytest.mark.asyncio
async def test_activity_panel_has_lsp_section():
    """ActivityPanel.compose 含 'LSP' 区段(标题)。"""
    from argos_agent.lsp.events import LspServerEvent
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        ap = app.query_one("#ap", ActivityPanel)
        titles = [s.border_title for s in ap._sections()]
        assert "LSP" in titles


@pytest.mark.asyncio
async def test_activity_panel_on_lsp_server_event_ready():
    """status='ready' + elapsed_ms=820 → 区段体显 'python' + 'ready' + 耗时。"""
    from argos_agent.lsp.events import LspServerEvent
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        ap = app.query_one("#ap", ActivityPanel)
        ap.on_lsp_server_event(LspServerEvent(
            server_name="python", status="ready", command="pyright",
            elapsed_ms=820, cwd="",
        ))
        snap = ap.snapshot_text()
        assert "python" in snap
        assert "ready" in snap.lower()
        assert "820" in snap


@pytest.mark.asyncio
async def test_activity_panel_on_lsp_server_event_disabled():
    """status='disabled' → 区段体显 'disabled'。"""
    from argos_agent.lsp.events import LspServerEvent
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        ap = app.query_one("#ap", ActivityPanel)
        ap.on_lsp_server_event(LspServerEvent(
            server_name="python", status="disabled", command="x",
            error="not found", cwd="",
        ))
        snap = ap.snapshot_text()
        assert "disabled" in snap.lower()


@pytest.mark.asyncio
async def test_activity_panel_on_lsp_server_event_crash():
    """status='crash' + error → 区段体显 'crash' + 错误。"""
    from argos_agent.lsp.events import LspServerEvent
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        ap = app.query_one("#ap", ActivityPanel)
        ap.on_lsp_server_event(LspServerEvent(
            server_name="python", status="crash", command="x",
            error="sigsegv", elapsed_ms=100, cwd="",
        ))
        snap = ap.snapshot_text()
        assert "crash" in snap.lower()
        assert "sigsegv" in snap


@pytest.mark.asyncio
async def test_activity_panel_lsp_diag_change_detection():
    """lsp_diagnostic_event 同 uri 同 count → 不重渲;新 count → 渲。"""
    from argos_agent.lsp.events import LspDiagnosticEvent
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        ap = app.query_one("#ap", ActivityPanel)
        ev_a = LspDiagnosticEvent(
            server_name="python", uri="file:///a.py", count=3,
            severity_counts={"error": 3}, cached=False, cwd="",
        )
        ap.on_lsp_diagnostic_event(ev_a)
        # 第二次同 uri 同 count → 内部 cache 不变
        ap.on_lsp_diagnostic_event(ev_a)
        assert ap._lsp_diag_cache.get("file:///a.py") == 3
        # 第三次同 uri 新 count=5 → cache 更新
        ap.on_lsp_diagnostic_event(LspDiagnosticEvent(
            server_name="python", uri="file:///a.py", count=5,
            severity_counts={"error": 5}, cached=False, cwd="",
        ))
        assert ap._lsp_diag_cache.get("file:///a.py") == 5


@pytest.mark.asyncio
async def test_activity_panel_lsp_diag_dedup_no_cache_growth():
    """同 uri 同 count 重复推 → _lsp_diag_cache 不增(5 次推 → 1 个 entry)。"""
    from argos_agent.lsp.events import LspDiagnosticEvent
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        ap = app.query_one("#ap", ActivityPanel)
        for _ in range(5):
            ap.on_lsp_diagnostic_event(LspDiagnosticEvent(
                server_name="python", uri="file:///a.py", count=2,
                severity_counts={"error": 2}, cached=False, cwd="",
            ))
        assert ap._lsp_diag_cache.get("file:///a.py") == 2
        assert len(ap._lsp_diag_cache) == 1


@pytest.mark.asyncio
async def test_activity_panel_reset_run_clears_lsp_log():
    """reset_run 清空 LSP cache(每轮独立)。"""
    from argos_agent.lsp.events import LspDiagnosticEvent
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        ap = app.query_one("#ap", ActivityPanel)
        ap.on_lsp_diagnostic_event(LspDiagnosticEvent(
            server_name="python", uri="file:///a.py", count=2,
            severity_counts={"error": 2}, cached=False, cwd="",
        ))
        assert ap._lsp_diag_cache
        ap.reset_run()
        assert ap._lsp_diag_cache == {}

