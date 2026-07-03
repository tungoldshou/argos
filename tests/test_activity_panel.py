import pytest
from textual.app import App, ComposeResult
from argos.tui.widgets.activity_panel import ActivityPanel
from argos.tui.theme import ARGOS_NIGHT
from argos.core.types import ModelTierName  # noqa


class _H(App):

    def get_theme_variable_defaults(self) -> dict[str, str]:
        defaults = super().get_theme_variable_defaults()
        if ARGOS_NIGHT.variables:
            defaults.update(ARGOS_NIGHT.variables)
        return defaults

    def compose(self) -> ComposeResult:
        yield ActivityPanel(id="ap", model_label="MiniMax-M3", tier="worker")


@pytest.mark.asyncio
async def test_panel_sections_present_and_honest_empty():
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        ap = app.query_one("#ap", ActivityPanel)
        txt = ap.snapshot_text()
        assert "MiniMax-M3" in txt
        assert ("可用" in txt or "无可用" in txt)
        assert ("未配置" in txt or "已配置" in txt)
        assert "缓存" in txt


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
        assert "write_file" in t
        assert "179" in t


@pytest.mark.asyncio
async def test_model_section_shows_name_not_tier():
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        ap = app.query_one("#ap", ActivityPanel)
        txt = ap.snapshot_text()
        assert "MiniMax-M3" in txt, "应显示真实模型名"
        assert "档位" not in txt and "worker" not in txt, "不得暴露内部档位/tier 概念"


@pytest.mark.asyncio
async def test_cost_dollar_removed_tokens_kept():
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        ap = app.query_one("#ap", ActivityPanel)
        ap.on_cost(tokens_in=100, tokens_out=50, cost_usd=None, elapsed_s=1.0, cache_read=0)
        await pilot.pause()
        t = ap.snapshot_text()
        assert "$" not in t and "N/A" not in t, "费用 $ / N/A 显示应已移除"
        assert "↑100" in t and "↓50" in t, "token 流应保留"


@pytest.mark.asyncio
async def test_cost_line_token_flow_has_unit():
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        ap = app.query_one("#ap", ActivityPanel)
        ap.on_cost(tokens_in=37900, tokens_out=174, cost_usd=None, elapsed_s=1.0, cache_read=0)
        await pilot.pause()
        cost = str(ap._sections()[ap._COST_IDX].content)
        assert "↑37.9k" in cost and "↓174" in cost and "tok" in cost, f"实际:{cost!r}"


@pytest.mark.asyncio
async def test_cache_lines_use_token_unit_and_abbrev():
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        ap = app.query_one("#ap", ActivityPanel)
        ap.on_cost(tokens_in=7200, tokens_out=355, cost_usd=None, elapsed_s=26.0, cache_read=13568)
        await pilot.pause()
        cost = str(ap._sections()[ap._COST_IDX].content)
        assert "cache hit 13.6k tok" in cost or "缓存命中 13.6k tok" in cost, f"实际:{cost!r}"
        assert "cache " in cost and "13.6k tok" in cost, f"实际:{cost!r}"
        assert "cache hit 13568" not in cost and "cache " + "13568" not in cost, f"实际:{cost!r}"


@pytest.mark.asyncio
async def test_context_section_no_redundant_model_or_window():
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        ap = app.query_one("#ap", ActivityPanel)
        ap.on_context(used=13204, window=1000000)  # 1%
        await pilot.pause()
        ctx = str(ap._sections()[ap._CTX_IDX].content)
        assert "1000k" in ctx, f"应有人类可读窗口 1000k,实际:{ctx!r}"
        assert "1,000,000" not in ctx, f"不应再出现原始窗口(去重),实际:{ctx!r}"
        assert ctx.count("1%") == 1, f"pct 应只出现一次(进度条上),实际:{ctx!r}"
        assert "MiniMax-M3" not in ctx, f"model 不应在上下文区重复(在 Model 段),实际:{ctx!r}"


@pytest.mark.asyncio
async def test_cache_idle_line_has_elapsed_label():
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        ap = app.query_one("#ap", ActivityPanel)
        ap.on_cost(tokens_in=100, tokens_out=50, cost_usd=None, elapsed_s=31.9, cache_read=0)
        await pilot.pause()
        cost = str(ap._sections()[ap._COST_IDX].content)
        assert "31.9" in cost, f"应含耗时,实际:{cost!r}"
        assert "用时" in cost, f"耗时应带标签(zh 用时),实际:{cost!r}"


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
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        ap = app.query_one("#ap", ActivityPanel)
        assert ap.styles.overflow_y == "auto",\
            f"活动栏应 overflow-y: auto 才能滚动,实际 {ap.styles.overflow_y}"


@pytest.mark.asyncio
async def test_section_title_not_transparent():
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
        ap.on_phase("plan", 0)
        await pilot.pause()
        sec = str(ap._sections()[1].content)
        assert "0.0s" not in sec, "进行中阶段不应显 0.0s"
        assert "…" in sec, "进行中阶段应显占位 …"



@pytest.mark.asyncio
async def test_phase_glyphs_v3():
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        ap = app.query_one("#ap", ActivityPanel)
        ap.on_phase("plan", 0)
        ap.on_phase("act", 1)
        ap.on_phase("verify", 2)
        ap.on_phase("report", 3)
        snap = ap.snapshot_text()
        assert "◔" in snap, "plan 阶段应用 ◔ 字形(v3 §3.1)"
        assert "◉" in snap, "act 阶段应用 ◉ 字形(v3 §3.1)"
        assert "❂" in snap, "verify 阶段应用 ❂ 字形(v3 §3.1)"
        assert "◕" in snap, "report 阶段应用 ◕ 字形(v3 §3.1)"
        assert "✦" not in snap, "✦ 已被处决(v3),不应出现"
        assert "◇" not in snap, "◇ 已被处决(v3),不应出现"


@pytest.mark.asyncio
async def test_empty_state_uses_lenticular_glyph():
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        ap = app.query_one("#ap", ActivityPanel)
        ap.reset_run()
        await pilot.pause()
        snap = ap.snapshot_text()
        assert "◌" in snap, "空态应用 ◌ 字形(v3 §3.1 空态/未配置)"


@pytest.mark.asyncio
async def test_width_is_34():
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        ap = app.query_one("#ap", ActivityPanel)
        # DEFAULT_CSS width:34
        assert "34" in ap.DEFAULT_CSS, "v3 ActivityPanel width 应为 34"


@pytest.mark.asyncio
async def test_no_border_left_uses_background_for_separation():
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        ap = app.query_one("#ap", ActivityPanel)
        assert "border-left" not in ap.DEFAULT_CSS,\
            "v3 ActivityPanel 应用背景色差分栏,不用 border-left"


@pytest.mark.asyncio
async def test_cache_sparkline_in_cost_section():
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        ap = app.query_one("#ap", ActivityPanel)
        for i in range(5):
            ap.on_cost(tokens_in=1000 * (i + 1), tokens_out=300, cost_usd=0.01,
                       elapsed_s=1.0, cache_read=2000 * (i + 1))
        await pilot.pause()
        snap = ap.snapshot_text()
        sparkline_chars = "▁▂▃▄▅▆▇█"
        assert any(c in snap for c in sparkline_chars),\
            f"on_cost(cache_read>0) 应产出 sparkline,实际 {snap!r}"


@pytest.mark.asyncio
async def test_compacted_event_new_method():
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        ap = app.query_one("#ap", ActivityPanel)
        assert hasattr(ap, "on_compacted"), "ActivityPanel 必须有 on_compacted 方法"
        ap.on_compacted(before=12, after=4, reduction_pct=22.0)
        await pilot.pause()
        snap = ap.snapshot_text()
        assert "↯" in snap, "on_compacted 后 snapshot_text 应含 ↯ 压缩符"
        assert "22" in snap, "压缩百分比应显示"


@pytest.mark.asyncio
async def test_pruned_event_new_method():
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        ap = app.query_one("#ap", ActivityPanel)
        assert hasattr(ap, "on_pruned"), "ActivityPanel 必须有 on_pruned 方法"
        ap.on_pruned(before=10, after=7, removed=3)
        await pilot.pause()
        snap = ap.snapshot_text()
        assert "3" in snap, "on_pruned 后 snapshot_text 应含被移除条数"


@pytest.mark.asyncio
async def test_memory_recall_new_method():
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        ap = app.query_one("#ap", ActivityPanel)
        assert hasattr(ap, "on_memory_recall"), "ActivityPanel 必须有 on_memory_recall 方法"
        ap.on_memory_recall(hits=5)
        await pilot.pause()
        snap = ap.snapshot_text()
        assert "5" in snap, "on_memory_recall 后 snapshot_text 应含召回条数"


@pytest.mark.asyncio
async def test_receipt_no_emoji():
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        ap = app.query_one("#ap", ActivityPanel)
        ap.on_receipt("read_file")
        await pilot.pause()
        snap = ap.snapshot_text()
        assert "🧾" not in snap, "v3 回执区段不得用 🧾 emoji(已处决)"
        assert "read_file" in snap, "工具名仍应显示"


@pytest.mark.asyncio
async def test_verdict_empty_state_uses_lenticular():
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        ap = app.query_one("#ap", ActivityPanel)
        ap.reset_run()
        await pilot.pause()
        snap = ap.snapshot_text()
        assert "◌" in snap, "Verdict 空态应显 ◌ (无)"


@pytest.mark.asyncio
async def test_activity_panel_has_hook_section():
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        ap = app.query_one("#ap", ActivityPanel)
        titles = [getattr(s, "border_title", "") for s in ap._sections()]
        assert "Hook" in titles


@pytest.mark.asyncio
async def test_activity_panel_on_hook_fired_ok():
    from argos.hooks.events import HookFired
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
    from argos.hooks.events import HookFired
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
    from argos.hooks.events import HookFired
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
    from argos.hooks.events import HookFired
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
        assert len(ap._hook_log) == 50


@pytest.mark.asyncio
async def test_activity_panel_reset_run_clears_hook_log():
    from argos.hooks.events import HookFired
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
    from argos.lsp.events import LspServerEvent
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        ap = app.query_one("#ap", ActivityPanel)
        titles = [s.border_title for s in ap._sections()]
        assert "LSP" in titles


@pytest.mark.asyncio
async def test_activity_panel_on_lsp_server_event_ready():
    from argos.lsp.events import LspServerEvent
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
    from argos.lsp.events import LspServerEvent
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
    from argos.lsp.events import LspServerEvent
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
    from argos.lsp.events import LspDiagnosticEvent
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        ap = app.query_one("#ap", ActivityPanel)
        ev_a = LspDiagnosticEvent(
            server_name="python", uri="file:///a.py", count=3,
            severity_counts={"error": 3}, cached=False, cwd="",
        )
        ap.on_lsp_diagnostic_event(ev_a)
        ap.on_lsp_diagnostic_event(ev_a)
        assert ap._lsp_diag_cache.get("file:///a.py") == 3
        ap.on_lsp_diagnostic_event(LspDiagnosticEvent(
            server_name="python", uri="file:///a.py", count=5,
            severity_counts={"error": 5}, cached=False, cwd="",
        ))
        assert ap._lsp_diag_cache.get("file:///a.py") == 5


@pytest.mark.asyncio
async def test_activity_panel_lsp_diag_dedup_no_cache_growth():
    from argos.lsp.events import LspDiagnosticEvent
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
    from argos.lsp.events import LspDiagnosticEvent
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


@pytest.mark.asyncio
async def test_run_section_shows_active_run_not_none():
    app = _H()
    async with app.run_test() as pilot:
        ap = app.query_one("#ap", ActivityPanel)
        ap.reset_run()
        ap.on_run_active("查成都今天天气")
        await pilot.pause()
        run_sec = str(ap._sections()[ap._RUN_IDX].content)
        assert "查成都今天天气" in run_sec, f"Run 段应显活跃 run,实际:{run_sec!r}"
        assert "(无)" not in run_sec and "(none)" not in run_sec


@pytest.mark.asyncio
async def test_run_active_label_truncated():
    app = _H()
    async with app.run_test() as pilot:
        ap = app.query_one("#ap", ActivityPanel)
        ap.on_run_active("x" * 80)
        await pilot.pause()
        run_sec = str(ap._sections()[ap._RUN_IDX].content)
        assert "…" in run_sec and len(run_sec) < 60


@pytest.mark.asyncio
async def test_verdict_no_check_fallback_for_conversational_run():
    app = _H()
    async with app.run_test() as pilot:
        ap = app.query_one("#ap", ActivityPanel)
        ap.reset_run()
        ap.on_run_end()
        await pilot.pause()
        verdict_sec = str(ap._sections()[ap._VERDICT_IDX].content)
        assert "无机检" in verdict_sec, f"应诚实兜底,实际:{verdict_sec!r}"
        assert verdict_sec.strip() not in ("◌ (无)", "◌ (none)")


@pytest.mark.asyncio
async def test_verdict_kept_when_run_was_verified():
    class _V:
        status = "passed"; verify_cmd = "pytest"; detail = ""; self_verified = False; no_test = False
    app = _H()
    async with app.run_test() as pilot:
        ap = app.query_one("#ap", ActivityPanel)
        ap.reset_run()
        ap.on_verdict(_V())
        ap.on_run_end()
        await pilot.pause()
        verdict_sec = str(ap._sections()[ap._VERDICT_IDX].content)
        assert "passed" in verdict_sec
        assert "无机检" not in verdict_sec


@pytest.mark.asyncio
async def test_cost_hides_cache_hit_zero_until_cache_seen():
    app = _H()
    async with app.run_test() as pilot:
        ap = app.query_one("#ap", ActivityPanel)
        ap.on_cost(tokens_in=77000, tokens_out=400, cost_usd=None, elapsed_s=68.8, cache_read=0)
        await pilot.pause()
        cost_sec = str(ap._sections()[ap._COST_IDX].content)
        assert "命中 0" not in cost_sec and "hit 0" not in cost_sec, f"不应显 cache hit 0:{cost_sec!r}"
        assert "缓存" in cost_sec
        ap.on_cost(tokens_in=77000, tokens_out=400, cost_usd=None, elapsed_s=70.0, cache_read=512)
        await pilot.pause()
        cost_sec2 = str(ap._sections()[ap._COST_IDX].content)
        assert "512" in cost_sec2 and "命中" in cost_sec2
