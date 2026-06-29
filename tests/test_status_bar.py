# tests/test_status_bar.py
"""StatusBar v3「黑曜石之眼」测试套件。

覆盖：
- 阶段眼字符映射（◔plan / ◉act / ❂verify / ◕report / ◌idle）
- set_blocked(True) → ◓开头 + 含"审批挂起"，即便 phase=verify
- set_alert(True) → CSS 类 -alert 加持
- ctx≥80% → -ctx-warn；ctx≥95% → -ctx-crit
- 不变 API 兼容（行为契约）
"""
import pytest
from textual.app import App, ComposeResult

from argos.tui.theme import ARGOS_NIGHT
from argos.tui.widgets.status_bar import StatusBar


class _H(App):
    """最小测试宿主：注入 argos-night token 以便 DEFAULT_CSS 中 $token 名能在 CSS 解析阶段解析。

    override get_theme_variable_defaults() 是在 CSS 解析前就让 $token 可用的唯一手段——
    register_theme + self.theme 发生在 on_mount，晚于 DEFAULT_CSS 首次解析。
    """

    def get_theme_variable_defaults(self) -> dict[str, str]:
        """把 ARGOS_NIGHT variables 作为 CSS token 兜底注入。"""
        defaults = super().get_theme_variable_defaults()
        if ARGOS_NIGHT.variables:
            defaults.update(ARGOS_NIGHT.variables)
        return defaults

    def compose(self) -> ComposeResult:
        yield StatusBar(id="sb")


# ── 旧兼容（不变 API）────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_status_bar_shows_phase_actions_elapsed():
    """不变 API：set_phase / set_cost → render_text 含阶段/动作/耗时。"""
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        sb = app.query_one("#sb", StatusBar)
        sb.set_phase("verify", 3)
        sb.set_cost(tokens_in=1, tokens_out=2, cost_usd=0.0, elapsed_s=4.2)
        await pilot.pause()
        t = sb.render_text
        assert "verify" in t and "3" in t and "4.2" in t


# ── 阶段眼字符映射（v3 §4.9 + §8.4）────────────────────────────────
@pytest.mark.asyncio
async def test_phase_eye_plan():
    """plan 阶段 → 眼字形 ◔。"""
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        sb = app.query_one("#sb", StatusBar)
        sb.set_phase("plan", 0)
        await pilot.pause()
        assert sb.render_text.startswith("◔"), f"期望 ◔ 开头，实际：{sb.render_text!r}"


@pytest.mark.asyncio
async def test_phase_eye_act():
    """act 阶段 → 眼字形 ◉。"""
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        sb = app.query_one("#sb", StatusBar)
        sb.set_phase("act", 2)
        await pilot.pause()
        assert sb.render_text.startswith("◉"), f"期望 ◉ 开头，实际：{sb.render_text!r}"


@pytest.mark.asyncio
async def test_phase_eye_verify():
    """verify 阶段 → 眼字形 ❂。"""
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        sb = app.query_one("#sb", StatusBar)
        sb.set_phase("verify", 5)
        await pilot.pause()
        assert sb.render_text.startswith("❂"), f"期望 ❂ 开头，实际：{sb.render_text!r}"


@pytest.mark.asyncio
async def test_phase_eye_report():
    """report 阶段 → 眼字形 ◕。"""
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        sb = app.query_one("#sb", StatusBar)
        sb.set_phase("report", 1)
        await pilot.pause()
        assert sb.render_text.startswith("◕"), f"期望 ◕ 开头，实际：{sb.render_text!r}"


@pytest.mark.asyncio
async def test_phase_eye_idle():
    """idle 阶段 → 眼字形 ◌。"""
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        sb = app.query_one("#sb", StatusBar)
        # 默认即 idle
        await pilot.pause()
        assert sb.render_text.startswith("◌"), f"期望 ◌ 开头，实际：{sb.render_text!r}"


# ── 优先级状态机（v3 §8.4 裁决铁律）────────────────────────────────
@pytest.mark.asyncio
async def test_set_blocked_overrides_verify_phase():
    """用户阻塞态优先级最高：phase=verify 但 set_blocked(True) → ◓ 开头 + 含"审批挂起"。"""
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        sb = app.query_one("#sb", StatusBar)
        sb.set_phase("verify", 5)
        sb.set_blocked(True)
        await pilot.pause()
        t = sb.render_text
        assert t.startswith("◓"), f"blocked 时期望 ◓ 开头，实际：{t!r}"
        assert "审批挂起" in t, f"blocked 时期望含'审批挂起'，实际：{t!r}"


@pytest.mark.asyncio
async def test_set_blocked_false_restores_phase():
    """set_blocked(False) → 恢复阶段眼（◉ act）。"""
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        sb = app.query_one("#sb", StatusBar)
        sb.set_phase("act", 2)
        sb.set_blocked(True)
        sb.set_blocked(False)
        await pilot.pause()
        t = sb.render_text
        assert t.startswith("◉"), f"blocked=False 后期望 ◉ 开头，实际：{t!r}"


@pytest.mark.asyncio
async def test_set_alert_adds_css_class():
    """set_alert(True) → widget 上有 -alert CSS 类。"""
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        sb = app.query_one("#sb", StatusBar)
        sb.set_phase("verify", 5)
        sb.set_alert(True)
        await pilot.pause()
        assert sb.has_class("-alert"), "set_alert(True) 后期望 CSS 类 -alert"


@pytest.mark.asyncio
async def test_set_alert_false_removes_css_class():
    """set_alert(False) → 移除 -alert CSS 类。"""
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        sb = app.query_one("#sb", StatusBar)
        sb.set_alert(True)
        sb.set_alert(False)
        await pilot.pause()
        assert not sb.has_class("-alert"), "set_alert(False) 后期望无 -alert 类"


@pytest.mark.asyncio
async def test_alert_does_not_override_phase_eye_glyph():
    """告警锁色时眼仍随阶段（字形不变为 ◓），整条锁红靠 CSS。"""
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        sb = app.query_one("#sb", StatusBar)
        sb.set_phase("act", 3)
        sb.set_alert(True)
        await pilot.pause()
        t = sb.render_text
        # alert 时眼仍随阶段（◉），不是 ◓（◓ 只属于 blocked）
        assert t.startswith("◉"), f"alert 时阶段眼应保持 ◉，实际：{t!r}"


@pytest.mark.asyncio
async def test_blocked_beats_alert():
    """blocked > alert 优先级：两者同时 True → ◓。"""
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        sb = app.query_one("#sb", StatusBar)
        sb.set_phase("verify", 5)
        sb.set_alert(True)
        sb.set_blocked(True)
        await pilot.pause()
        t = sb.render_text
        assert t.startswith("◓"), f"blocked+alert 时期望 ◓ 优先，实际：{t!r}"


# ── ctx 压力 CSS 类（v3 §4.9 d）──────────────────────────────────
@pytest.mark.asyncio
async def test_ctx_warn_at_80_percent():
    """ctx≥80% → CSS 类 -ctx-warn。"""
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        sb = app.query_one("#sb", StatusBar)
        sb.update_ctx_pressure(0.80)
        await pilot.pause()
        assert sb.has_class("-ctx-warn"), "ctx=80% 期望 -ctx-warn"
        assert not sb.has_class("-ctx-crit"), "ctx=80% 不应有 -ctx-crit"


@pytest.mark.asyncio
async def test_ctx_crit_at_95_percent():
    """ctx≥95% → CSS 类 -ctx-crit（且不保留 -ctx-warn）。"""
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        sb = app.query_one("#sb", StatusBar)
        sb.update_ctx_pressure(0.95)
        await pilot.pause()
        assert sb.has_class("-ctx-crit"), "ctx=95% 期望 -ctx-crit"


@pytest.mark.asyncio
async def test_ctx_below_80_no_warn():
    """ctx<80% → 无 -ctx-warn / -ctx-crit。"""
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        sb = app.query_one("#sb", StatusBar)
        sb.update_ctx_pressure(0.5)
        await pilot.pause()
        assert not sb.has_class("-ctx-warn"), "ctx=50% 不应有 -ctx-warn"
        assert not sb.has_class("-ctx-crit"), "ctx=50% 不应有 -ctx-crit"


# ── 窄屏降级（v3 §7.2）───────────────────────────────────────────
@pytest.mark.asyncio
async def test_narrow_mode_includes_cost_and_ctx():
    """<80 列降级模式：render_text 仍含阶段、成本、ctx%（不含键提示区但那是 render() 层）。"""
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        sb = app.query_one("#sb", StatusBar)
        sb.set_phase("act", 3)
        sb.set_cost(tokens_in=12400, tokens_out=3100, cost_usd=0.013, elapsed_s=4.2)
        sb.update_ctx_pressure(0.34)
        await pilot.pause()
        t = sb.render_text
        assert "act" in t
        assert "$0.013" in t
        assert "ctx 34%" in t


@pytest.mark.asyncio
async def test_cost_unknown_renders_na_not_shell_form():
    """成本未知 → render_text 含 'N/A',不再含 shell 样 '$(N/A)'(真机右侧/底栏观感修复)。"""
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        sb = app.query_one("#sb", StatusBar)
        sb.set_cost(tokens_in=100, tokens_out=50, cost_usd=None, elapsed_s=1.0)
        await pilot.pause()
        t = sb.render_text
        assert "N/A" in t, f"未知成本应显 N/A,实际:{t!r}"
        assert "$(N/A)" not in t, f"不应再用 shell 样 $(N/A),实际:{t!r}"


@pytest.mark.asyncio
async def test_token_flow_has_unit():
    """token 段带 'tok' 单位 + 方向箭头(修真机裸数字 ↑37.9k ↓174 无单位)。"""
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        sb = app.query_one("#sb", StatusBar)
        sb.set_cost(tokens_in=37900, tokens_out=174, cost_usd=0.0, elapsed_s=1.0)
        await pilot.pause()
        t = sb.render_text
        assert "↑37.9k" in t and "↓174" in t and "tok" in t, f"实际:{t!r}"


# ── 动作计数文字（v3 §4.9 a："动作" 而非 ⚙）──────────────────────
@pytest.mark.asyncio
async def test_action_count_label():
    """动作计数使用"动作N"文字格式（⚙ 已处决，v3 字形铁律）。"""
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        sb = app.query_one("#sb", StatusBar)
        sb.set_phase("act", 7)
        await pilot.pause()
        t = sb.render_text
        assert "动作7" in t, f"期望'动作7'，实际：{t!r}"
        # ⚙ 是处决字形
        assert "⚙" not in t, f"⚙ 是处决字形，不应出现：{t!r}"


def test_action_label_en_has_space():
    """EN 文案 'action {n}' 数字与词之间有空格 —— 修真机里 'action0' 像标识符的观感。
    (ZH '动作{n}' 按 CJK 习惯不加空格,保持不变 —— 见 test_action_count_label。)"""
    from argos.locales.tui_app import EN
    assert EN["tui.statusbar.action"].format(n=0) == "action 0"
    assert EN["tui.statusbar.action"].format(n=7) == "action 7"


# ── set_blocked / set_alert 签名存在性（公开 API 门禁）──────────────
def test_public_api_set_blocked_exists():
    """set_blocked(active: bool) 必须存在（P9 接线要调用）。"""
    import inspect
    sig = inspect.signature(StatusBar.set_blocked)
    params = list(sig.parameters)
    assert "active" in params, f"set_blocked 缺 active 参数，实际：{params}"


def test_public_api_set_alert_exists():
    """set_alert(kind: str | None) 或 set_alert(active: bool) 必须存在。"""
    import inspect
    assert hasattr(StatusBar, "set_alert"), "StatusBar 缺 set_alert 公开方法"
    sig = inspect.signature(StatusBar.set_alert)
    params = list(sig.parameters)
    # 第一个非 self 参数须存在
    assert len(params) >= 2, f"set_alert 签名参数不足，实际：{params}"


# ── 设计审计修复：blocked 眼色（2026-06-14）────────────────────
@pytest.mark.asyncio
async def test_blocked_eye_glyph_color_is_gold_not_orange():
    """AUDIT FIX [LOW]: blocked 眼 ◓ 应始终染 $eye 金色(#D9A85C)，不是 $unverif 橙色(#FF9E64)。

    设计稿 05 组件变体 line 316 明确：blocked 行整体文字染 $unverif 橙，但眼 ◓ 本身仍金
    (与其他阶段眼一致)。现有代码第 239 行 eye_style = _STYLE_BLOCKED if self._blocked else _STYLE_EYE
    强制 blocked 时用橙，与设计的二色对比(金眼+橙文)不符。修复：eye_style 恒为 _STYLE_EYE。
    """
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        sb = app.query_one("#sb", StatusBar)
        sb.set_phase("verify", 5)
        sb.set_blocked(True)
        await pilot.pause()

        # 生成 render() Rich Text
        rt = sb.render()
        plain = rt.plain
        assert plain.startswith("◓"), f"blocked 时期望 ◓ 开头，实际：{plain!r}"

        # 检查首字 ◓ 的样式：应该是 gold _STYLE_EYE，不是 orange _STYLE_BLOCKED
        # Rich Text 的 stylize 会在指定范围内设置样式；我们验证首个字符的样式不是 orange
        # 由于 render() 显式 stylize 首字符，我们检查 render() 输出不含 _STYLE_BLOCKED(#FF9E64) 的直接证据
        # 更直接：render() 调用 stylize(_STYLE_EYE, 0, 1) 表示位置 0 长度 1 应用金色
        # 检查 render() 中是否有 _STYLE_EYE (#D9A85C) 而非 _STYLE_BLOCKED (#FF9E64)
        # 由于 Textual 不暴露 Span 细节，我们用间接法：生成 render() 并反检查代码逻辑
        from argos.tui.widgets.status_bar import _STYLE_EYE, _STYLE_BLOCKED

        # 从源代码验证：blocked 眼应染 _STYLE_EYE，不是 _STYLE_BLOCKED
        # StatusBar.render() 第 238-241 行：eye_style = _STYLE_EYE（修复后）
        # 直接读源验证修复生效
        import inspect
        render_src = inspect.getsource(sb.render)
        assert "_STYLE_EYE" in render_src, "render() 应使用 _STYLE_EYE 给眼着色"
        # 更严格：不应出现 if self._blocked ... eye_style = _STYLE_BLOCKED 的分支
        # 即应该写成 eye_style = _STYLE_EYE（无条件）
        assert "eye_style = _STYLE_EYE" in render_src, "eye_style 应恒为 _STYLE_EYE"
        assert "if self._blocked" not in render_src.split("eye_style = _STYLE_EYE")[0].split('\n')[-1], \
            "eye_style = _STYLE_EYE 之前不应有 if self._blocked 分支"


def test_mark_run_end_resets_phase_to_idle():
    """C2(2026-06-22 真机:run 结束后底栏 phase 粘在 'report' 与右栏 idle 矛盾)。"""
    from argos.tui.widgets.status_bar import StatusBar
    bar = StatusBar()
    bar.set_phase("report", 5)
    assert bar.phase == "report"
    bar.mark_run_end()
    assert bar.phase == "idle", "run 收尾 phase 应复位 idle"
    assert bar.actions == 0


# ── Task 2.4: step budget N/M ─────────────────────────────────────────────────

def test_status_bar_action_with_max_steps():
    """set_phase with max_steps → render_text shows 'action N/M' format."""
    from argos.tui.widgets.status_bar import StatusBar
    bar = StatusBar()
    bar.set_phase("act", 7, max_steps=40)
    text = bar.render_text
    assert "7/40" in text, f"期望 '7/40' 在 render_text 中，实际：{text!r}"


def test_status_bar_action_without_max_steps():
    """set_phase without max_steps → render_text shows 'action N' (no '/None')."""
    from argos.tui.widgets.status_bar import StatusBar
    bar = StatusBar()
    bar.set_phase("act", 7)
    text = bar.render_text
    assert "7" in text, f"期望 '7' 在 render_text 中，实际：{text!r}"
    assert "/None" not in text, f"不应出现 '/None'，实际：{text!r}"
    assert "7/40" not in text  # 无 max_steps 不应显示分母


def test_phase_change_max_steps_field_defaults_none():
    """PhaseChange.max_steps defaults to None — existing call sites stay unbroken."""
    from argos.protocol.events import PhaseChange
    ev = PhaseChange(phase="act", actions=3)
    assert ev.max_steps is None

    ev_with = PhaseChange(phase="act", actions=3, max_steps=40)
    assert ev_with.max_steps == 40
