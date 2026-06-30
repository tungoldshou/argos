"""ActivityPanel 智能切(TUI v2 spec §5):4 视图按阶段自动切换 + Ctrl+O 手动 pin +
footer(成本/上下文)常驻 + snapshot_text 聚合全部数据(不受视图切换影响)。"""
from __future__ import annotations

import pytest
from textual.app import App, ComposeResult

from argos.tui.widgets.activity_panel import ActivityPanel
from argos.tui.theme import ARGOS_NIGHT


class _H(App):
    """最小测试宿主:注入 ARGOS_NIGHT tokens 以便 DEFAULT_CSS 中 $token 可解析。"""

    def get_theme_variable_defaults(self) -> dict[str, str]:
        """把 ARGOS_NIGHT.variables 作为 CSS token 兜底注入。"""
        defaults = super().get_theme_variable_defaults()
        if ARGOS_NIGHT.variables:
            defaults.update(ARGOS_NIGHT.variables)
        return defaults

    def compose(self) -> ComposeResult:
        yield ActivityPanel(id="ap", model_label="M3", tier="t")


def _visible_titles(ap: ActivityPanel) -> set[str]:
    return {str(s.border_title) for s in ap._sections() if s.display}


@pytest.mark.asyncio
async def test_idle_view_default_and_footer_always_on():
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        ap = app.query_one("#ap", ActivityPanel)
        vis = _visible_titles(ap)
        assert "模型" in vis and "MCP" in vis
        assert "工具" not in vis                       # act 专属,idle 隐藏
        assert "用量 + 缓存" in vis and "上下文" in vis  # footer 常驻


@pytest.mark.asyncio
async def test_phase_drives_view_auto_switch():
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        ap = app.query_one("#ap", ActivityPanel)
        ap.on_phase("plan", 0)
        assert ap._view == "plan"
        assert "任务进度" in _visible_titles(ap)
        ap.on_phase("act", 1)
        assert ap._view == "act"
        vis = _visible_titles(ap)
        assert "工具" in vis and "Approval" in vis
        assert "模型" not in vis
        ap.on_phase("verify", 1)
        assert ap._view == "verify"
        assert "Verdict" in _visible_titles(ap)
        ap.on_run_end()
        assert ap._view == "idle"
        # footer 在每个视图都常驻
        assert "用量 + 缓存" in _visible_titles(ap)


@pytest.mark.asyncio
async def test_pinned_view_ignores_phase():
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        ap = app.query_one("#ap", ActivityPanel)
        ap.set_view("act", pinned=True)
        ap.on_phase("plan", 0)        # pinned:阶段不再自动切
        assert ap._view == "act"
        ap.on_run_end()
        assert ap._view == "act"


@pytest.mark.asyncio
async def test_cycle_view_walks_and_returns_to_auto():
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        ap = app.query_one("#ap", ActivityPanel)
        seen = [ap.cycle_view() for _ in range(5)]
        assert seen == ["idle", "plan", "act", "verify", "auto"]
        assert ap._pinned is False    # 走完一圈回 auto
        ap.on_phase("act", 1)         # auto 恢复:阶段又能驱动了
        assert ap._view == "act"


@pytest.mark.asyncio
async def test_snapshot_text_aggregates_hidden_sections():
    """诚实:数据都在 —— 视图只动可见性,snapshot_text(/cost 回显)聚合全部区段。"""
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        ap = app.query_one("#ap", ActivityPanel)
        ap.on_receipt("write_file")               # 工具区数据(idle 视图下隐藏)
        ap.set_view("idle", pinned=True)
        assert "write_file" in ap.snapshot_text()


@pytest.mark.asyncio
async def test_verdict_section_shows_three_state_honestly():
    from argos.core.verify_gate import Verdict
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        ap = app.query_one("#ap", ActivityPanel)
        ap.on_verdict(Verdict.unverifiable(detail="no cmd", tampered=[], attempts=1))
        assert "unverifiable" in ap.snapshot_text()
        # E4 防火墙:self-verified 的 passed 必须显式标注,不冒充用户级 verify
        ap.on_verdict(Verdict.passed_self(detail="ok", verify_cmd="pytest", attempts=1))
        t = ap.snapshot_text()
        assert "passed" in t and "pytest" in t and "self-verified" in t
