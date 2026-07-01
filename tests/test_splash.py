"""StartupSplash TUI v3 spec §4.2:睁眼仪式 + 诚实徽标断言。

视觉更新(v3):
- ASCII box-drawing 大字 logo 替换为 ▄▀█ 像素风块字
- 禁止 ASCII 巨眼(裁决判死):不含旧 █████╗ 式眼形框
- 状态眼单行:◉/◌/◓ 随启动自检推进
- 徽标文案:✳ LIVE → LIVE, ⚠ DEMO 演示 → DEMO 脚本演示, ⚠ 未配 key → 未配 key · /setup
- has_key=False 绝不出现 LIVE(契约6)
- ARGOS 字面品牌行保留(可访问性文本)

行为契约断言语义不变。
"""
from __future__ import annotations

import pytest
from argos.tui.app import ArgosApp
from argos.tui.fakeloop import FakeLoop
from argos.tui.widgets.splash import StartupSplash


@pytest.mark.asyncio
async def test_splash_shown_on_mount_with_mode_badge():
    """挂载后显示 splash,含 ARGOS 品牌字;DEMO 徽标已移除(2026-07-01)。"""
    app = ArgosApp(loop_factory=lambda **kw: FakeLoop())
    async with app.run_test() as pilot:
        await pilot.pause()
        sp = list(app.query(StartupSplash))
        assert len(sp) == 1
        assert "ARGOS" in sp[0].renderable_text
        assert "DEMO" not in sp[0].renderable_text       # demo 徽标已移除


@pytest.mark.asyncio
async def test_splash_cleared_on_first_run():
    """起一轮后 splash 被清除。"""
    app = ArgosApp(loop_factory=lambda **kw: FakeLoop())
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.start_run("演示任务")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert len(list(app.query(StartupSplash))) == 0, "起一轮后 splash 应被清除"


def test_splash_no_ascii_giant_eye():
    """v3:禁止 ASCII 巨眼(裁决判死)。不应含旧 box-drawing 大字眼形。"""
    sp = StartupSplash(model_label="M3", tier="sonnet", live=True, has_key=True)
    text = sp.renderable_text
    # 旧 ASCII box logo 含 ██████╗ 式结构,v3 改为 ▄▀█ 块字
    assert "╔" not in text and "╗" not in text and "╚" not in text and "╝" not in text, (
        f"v3 禁止旧 box-drawing 大字 logo 字符,实际 text={text!r}"
    )


def test_splash_has_key_live_shows_live_badge():
    """有 key + live=True → 末态眼 ◉ + LIVE 徽标。"""
    sp = StartupSplash(model_label="M3", tier="sonnet", live=True, has_key=True)
    text = sp.renderable_text
    assert "LIVE" in text, f"有 key + live=True 应含 LIVE,实际: {text!r}"
    assert "未配 key" not in text


def test_splash_has_key_false_no_live():
    """has_key=False → 绝不出现 LIVE(契约6)。"""
    sp = StartupSplash(model_label="M3", tier="sonnet", live=True, has_key=False)
    text = sp.renderable_text
    assert "LIVE" not in text, f"无 key 时绝不含 LIVE,实际: {text!r}"
    assert "未配 key" in text


def test_splash_no_key_shows_eye_not_live():
    """has_key=False → 状态眼停在 ◌(不睁开),不出现 ◉ 和 LIVE。"""
    sp = StartupSplash(model_label="M3", tier="sonnet", live=True, has_key=False)
    text = sp.renderable_text
    # 无 key 永远停在 ◌
    assert "◌" in text, f"无 key 应显 ◌ 空态眼,实际: {text!r}"
    assert "LIVE" not in text


def test_splash_advance_eye_api_exists():
    """advance_eye(stage) 方法存在(v3 新增,睁眼仪式驱动)。"""
    sp = StartupSplash(model_label="M3", tier="sonnet", live=True, has_key=True)
    # 纯新增 API,不应抛出
    sp.advance_eye("scan")
    sp.advance_eye("half")
    sp.advance_eye("focus")
    sp.advance_eye("open")
