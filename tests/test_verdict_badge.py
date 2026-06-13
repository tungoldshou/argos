"""VerdictBadge 四态测试(TUI v3 · 黑曜石之眼 spec §4.6,契约7/10)。

断言点(spec §4.6(d)):
1. 四态前缀眼字符:passed=◉ / failed=◉ / unverifiable=◔ / self-verified=◍
2. self-verified 挂 verdict-self 类 + render_text 含"较弱"与"未晋级"(契约10)
3. passed render_text 含 verify_cmd 与"N 次尝试"
4. failed render_text 含 detail 与"重试"
5. unverifiable render_text 含"无法验证"(三重冗余文字证据)
6. CSS 三类名不变:verdict-passed/verdict-failed/verdict-unverifiable(契约7)
7. verdict-self 新增,不冒充 verdict-passed
"""
import pytest
from textual.app import App, ComposeResult

from argos.core.verify_gate import Verdict
from argos.tui.theme import ARGOS_NIGHT
from argos.tui.widgets.verdict_badge import VerdictBadge


class _H(App):
    """最小测试宿主：注入 argos-night token 以便 DEFAULT_CSS 中 $token 在 CSS 解析阶段可用。

    get_theme_variable_defaults() 在 DEFAULT_CSS 首次解析前运行,
    是让自定义 $token($pass/$fail/$unverif/$pass-weak)在测试环境中可用的唯一手段。
    """

    def get_theme_variable_defaults(self) -> dict[str, str]:
        """把 ARGOS_NIGHT.variables 作为 CSS token 兜底注入。"""
        defaults = super().get_theme_variable_defaults()
        if ARGOS_NIGHT.variables:
            defaults.update(ARGOS_NIGHT.variables)
        return defaults

    def compose(self) -> ComposeResult:
        yield VerdictBadge(id="vb")


# ── 契约7:三个 CSS 类名必须存在且不变 ─────────────────────────────


def test_css_class_names_unchanged():
    """契约7:verdict-passed/verdict-failed/verdict-unverifiable 三名不变。"""
    css = VerdictBadge.DEFAULT_CSS
    assert "verdict-passed" in css
    assert "verdict-failed" in css
    assert "verdict-unverifiable" in css
    assert "verdict-self" in css  # v3 新增


# ── 行为契约:三态互斥 CSS 类(语义不变)────────────────────────────


@pytest.mark.asyncio
async def test_three_states_get_distinct_classes():
    """三态各自独占一个 CSS 类,切换时不残留旧类(行为契约,语义不变)。"""
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        vb = app.query_one("#vb", VerdictBadge)
        vb.show(Verdict.passed(detail="ok", verify_cmd="echo", attempts=1))
        await pilot.pause()
        assert vb.has_class("verdict-passed")
        vb.show(Verdict.failed(detail="bad", verify_cmd="echo", attempts=1))
        await pilot.pause()
        assert vb.has_class("verdict-failed") and not vb.has_class("verdict-passed")
        vb.show(Verdict.unverifiable(detail="??", tampered=[], attempts=1))
        await pilot.pause()
        assert vb.has_class("verdict-unverifiable") and not vb.has_class("verdict-failed")


# ── 前缀眼字符(v3 视觉快照)─────────────────────────────────────


@pytest.mark.asyncio
async def test_passed_prefix_eye():
    """passed 态前缀眼 = ◉(注视实瞳)。"""
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        vb = app.query_one("#vb", VerdictBadge)
        vb.show(Verdict.passed(detail="42 passed", verify_cmd="pytest -x", attempts=1))
        await pilot.pause()
        assert "◉" in vb.render_text


@pytest.mark.asyncio
async def test_failed_prefix_eye():
    """failed 态前缀眼 = ◉(注视实瞳,同 passed 但色为红)。"""
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        vb = app.query_one("#vb", VerdictBadge)
        vb.show(Verdict.failed(detail="3 failed", verify_cmd="pytest -x", attempts=2))
        await pilot.pause()
        assert "◉" in vb.render_text


@pytest.mark.asyncio
async def test_unverifiable_prefix_eye():
    """unverifiable 态前缀眼 = ◔(扫视半瞳,三重冗余之一)。"""
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        vb = app.query_one("#vb", VerdictBadge)
        vb.show(Verdict.unverifiable(detail="trivial command rejected", tampered=[], attempts=1))
        await pilot.pause()
        assert "◔" in vb.render_text


@pytest.mark.asyncio
async def test_self_verified_prefix_eye():
    """self-verified 态前缀眼 = ◍(格纹瞳,区分于实瞳 ◉)。"""
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        vb = app.query_one("#vb", VerdictBadge)
        vb.show(Verdict.passed_self(detail="3 checks ok", verify_cmd=None, attempts=1))
        await pilot.pause()
        assert "◍" in vb.render_text


# ── passed 态:verify_cmd 与 N 次尝试 ─────────────────────────────


@pytest.mark.asyncio
async def test_passed_shows_verify_cmd_and_attempts():
    """passed render_text 含 verify_cmd 与 '次尝试'(spec §4.6 机会点③)。"""
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        vb = app.query_one("#vb", VerdictBadge)
        vb.show(Verdict.passed(detail="12 passed", verify_cmd="pytest -x", attempts=1))
        await pilot.pause()
        assert "pytest -x" in vb.render_text
        assert "次尝试" in vb.render_text or "1 次" in vb.render_text


# ── failed 态:detail 与重试 ──────────────────────────────────────


@pytest.mark.asyncio
async def test_failed_shows_detail_and_retry():
    """failed render_text 含 detail 与'重试'。"""
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        vb = app.query_one("#vb", VerdictBadge)
        vb.show(Verdict.failed(detail="assert mismatch", verify_cmd="pytest -x", attempts=3))
        await pilot.pause()
        assert "assert mismatch" in vb.render_text
        assert "重试" in vb.render_text


# ── unverifiable 态:三重冗余文字证据 ─────────────────────────────


@pytest.mark.asyncio
async def test_unverifiable_text_contains_wufa():
    """unverifiable render_text 含'无法验证'(三重冗余文字证据)。"""
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        vb = app.query_one("#vb", VerdictBadge)
        vb.show(Verdict.unverifiable(detail="trivial command rejected", tampered=[], attempts=1))
        await pilot.pause()
        assert "无法验证" in vb.render_text


@pytest.mark.asyncio
async def test_tampered_归入_unverifiable():
    """tampered 文件被改 → 归入 unverifiable 态,◔ 橙,含'无法验证'。"""
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        vb = app.query_one("#vb", VerdictBadge)
        vb.show(Verdict.unverifiable(detail="tamper detected", tampered=["auth.py"], attempts=1))
        await pilot.pause()
        assert vb.has_class("verdict-unverifiable")
        assert "无法验证" in vb.render_text
        assert "◔" in vb.render_text


# ── 契约10:self-verified 四重区分 ──────────────────────────────────


@pytest.mark.asyncio
async def test_self_verified_css_class_not_passed():
    """契约10:self_verified=True → verdict-self 类,绝不挂 verdict-passed。"""
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        vb = app.query_one("#vb", VerdictBadge)
        vb.show(Verdict.passed_self(detail="3 checks ok", verify_cmd=None, attempts=1))
        await pilot.pause()
        assert vb.has_class("verdict-self")
        assert not vb.has_class("verdict-passed")


@pytest.mark.asyncio
async def test_self_verified_render_text_contains_weaker_and_not_promoted():
    """契约10:self-verified render_text 含'较弱'与'未晋级'。"""
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        vb = app.query_one("#vb", VerdictBadge)
        vb.show(Verdict.passed_self(detail="3 checks ok", verify_cmd=None, attempts=1))
        await pilot.pause()
        assert "较弱" in vb.render_text
        assert "未晋级" in vb.render_text


@pytest.mark.asyncio
async def test_self_verified_second_line_annotation():
    """契约10:self-verified 强制第二行 ⤷ 注解。"""
    app = _H()
    async with app.run_test() as pilot:
        await pilot.pause()
        vb = app.query_one("#vb", VerdictBadge)
        vb.show(Verdict.passed_self(detail="3 checks ok", verify_cmd=None, attempts=1))
        await pilot.pause()
        # 第二行注解以 ⤷ 引出
        assert "⤷" in vb.render_text


# ── CSS 着色 token(v3 新规) ───────────────────────────────────────


def test_css_passed_uses_pass_token():
    """v3: verdict-passed 着色 $pass(满绿)。"""
    css = VerdictBadge.DEFAULT_CSS
    # 找 verdict-passed 块内含 $pass
    assert "$pass" in css


def test_css_failed_uses_fail_token():
    """v3: verdict-failed 着色 $fail(红)。"""
    css = VerdictBadge.DEFAULT_CSS
    assert "$fail" in css


def test_css_unverifiable_uses_unverif_token():
    """v3: verdict-unverifiable 着色 $unverif(橙)。"""
    css = VerdictBadge.DEFAULT_CSS
    assert "$unverif" in css


def test_css_self_uses_pass_weak_token():
    """v3: verdict-self 着色 $pass-weak(去饱和绿,区别于 $pass 满绿)。"""
    css = VerdictBadge.DEFAULT_CSS
    assert "$pass-weak" in css
