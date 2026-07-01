"""TopBar TUI v3 spec §4.1:状态眼 + 徽标诚实性断言。

视觉更新(v3):
- 品牌符 ✳ → 眼系字形(idle=◌, plan=◔, act=◉, verify=❂, report/done=◕)
- 徽标去方括号:[plan mode] → plan, ⏻ YOLO → YOLO
- 徽标新增 LIVE(有 key 时);has_key=False 绝不出现 LIVE(契约6)
- DEFAULT_CSS 底色改 $well

行为契约断言语义不变(只更新视觉字符)。
"""
from __future__ import annotations

import pytest
from textual.app import App, ComposeResult

from argos.tui.widgets.top_bar import TopBar


class _H(App):
    def compose(self) -> ComposeResult:
        yield TopBar(version="1.2.3", model_label="MiniMax-M3", id="tb")


@pytest.mark.asyncio
async def test_topbar_shows_brand_version_model():
    """品牌名、版本、模型均出现在渲染文本中。"""
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        tb = app.query_one("#tb", TopBar)
        t = tb.render_text
        assert "Argos" in t and "1.2.3" in t and "MiniMax-M3" in t


@pytest.mark.asyncio
async def test_topbar_shows_unsandboxed_badge_when_off(monkeypatch):
    """#2 CC对齐:关沙箱(opt-in 默认)→ 顶栏显式标'未沙箱化'(诚实:无内核牢笼,别让用户误以为有)。"""
    monkeypatch.setenv("ARGOS_SANDBOX", "0")
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        tb = app.query_one("#tb", TopBar)
        assert "未沙箱化" in tb.render_text


@pytest.mark.asyncio
async def test_topbar_no_unsandboxed_badge_when_on(monkeypatch):
    """开沙箱(--sandbox / ARGOS_SANDBOX=1)→ 不显'未沙箱化'标。"""
    monkeypatch.setenv("ARGOS_SANDBOX", "1")
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        tb = app.query_one("#tb", TopBar)
        assert "未沙箱化" not in tb.render_text


@pytest.mark.asyncio
async def test_topbar_logo_eye_glyph_not_star():
    """v3:品牌符从 ✳ 改为眼系字形(◌/◉ 等),不再出现 ✳。"""
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        tb = app.query_one("#tb", TopBar)
        t = tb.render_text
        assert "✳" not in t, f"v3 不应出现旧品牌符 ✳,实际: {t!r}"
        # idle 态初始眼形为 ◌(空态)
        assert "◌" in t, f"idle 态应显 ◌ 空态眼,实际: {t!r}"


@pytest.mark.asyncio
async def test_topbar_phase_eye_changes():
    """set_phase 切换眼形:act→◉, verify→❂, report→◕, plan→◔。"""
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        tb = app.query_one("#tb", TopBar)

        tb.set_phase("act")
        assert "◉" in tb.render_text, "act 阶段应显注视眼 ◉"

        tb.set_phase("verify")
        assert "❂" in tb.render_text, "verify 阶段应显聚焦眼 ❂"

        tb.set_phase("report")
        assert "◕" in tb.render_text, "report 阶段应显阅毕眼 ◕"

        tb.set_phase("plan")
        assert "◔" in tb.render_text, "plan 阶段应显扫视眼 ◔"

        tb.set_phase("idle")
        assert "◌" in tb.render_text, "idle 阶段应显空态眼 ◌"


@pytest.mark.asyncio
async def test_topbar_no_key_badge_never_lies_live():
    """has_key=False 时绝不出现 LIVE 字样(契约6)。"""
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        tb = app.query_one("#tb", TopBar)
        tb.set_state(has_key=False)
        # 不能有 LIVE
        assert "LIVE" not in tb.render_text, (
            f"无 key 时 render_text 绝不含 LIVE,实际: {tb.render_text!r}"
        )
        assert any("未配 key" in b for b in tb.badges())


@pytest.mark.asyncio
async def test_topbar_live_badge_present_with_key():
    """has_key=True +  → badges 含 LIVE(v3 新增)。"""
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        tb = app.query_one("#tb", TopBar)
        tb.set_state(has_key=True)
        assert any("LIVE" in b for b in tb.badges()), (
            f"有 key 时 badges 应含 LIVE,实际: {tb.badges()!r}"
        )


@pytest.mark.asyncio
async def test_topbar_plan_and_yolo_badges():
    """plan_mode → 'plan' 徽标(v3 去方括号);yolo → 'YOLO' 徽标。"""
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        tb = app.query_one("#tb", TopBar)
        tb.set_state(plan_mode=True, yolo=True)
        bs = tb.badges()
        # v3 徽标去方括号
        assert any("plan" in b for b in bs), f"plan_mode 应有 plan 徽标,实际: {bs!r}"
        assert any("YOLO" in b for b in bs), f"yolo 应有 YOLO 徽标,实际: {bs!r}"
        # 确认旧格式 [plan mode] 已移除
        assert "[plan mode]" not in bs, "v3 不应再出现 [plan mode] 方括号格式"
        tb.set_state(plan_mode=False, yolo=False)
        bs = tb.badges()
        assert not any("plan" in b and b == "plan" for b in bs)
        assert not any("YOLO" in b for b in bs)


@pytest.mark.asyncio
async def test_topbar_no_bullet_before_live():
    """v3:● LIVE 的 ● 被处决;LIVE 前缀无 ●(EAW=A 被处决字形)。"""
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        tb = app.query_one("#tb", TopBar)
        tb.set_state(has_key=True)
        t = tb.render_text
        # ● 是被处决字形,绝不出现
        assert "●" not in t, f"v3 ● 被处决,不应出现在渲染文本中,实际: {t!r}"
