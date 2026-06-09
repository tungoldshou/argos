"""StartupSplash 模式徽标必须真反映 key 状态(诚实底线:不假装 LIVE)。

bug 复现(2026-06-09):app.py:204 `live=not self._demo` — 只查 demo 开关, 不查
active_key() 真值。结果:用户 `argos setup` 没跑过 / key 已失效 / env var 没设 →
启动 TUI 显 `✳ LIVE` 徽标 → 输入目标 → 真 loop 调模型 401 → 任务失败。
徽标撒了谎,用户多走一步才发现。

修法:splash 接收 `has_key` 参数(默认 True 保持向后兼容);has_key=False 时
模式显 `⚠ 未配 key`(绝不再显 `✳ LIVE`),文案带"跑 /setup"指引。
"""
from __future__ import annotations


def test_splash_live_with_key_shows_live_badge():
    """live=True + has_key=True → 显 `✳ LIVE`(原行为不变)。"""
    from argos_agent.tui.widgets.splash import StartupSplash
    sp = StartupSplash(model_label="M3", tier="sonnet", live=True, has_key=True)
    text = sp.renderable_text
    assert "✳ LIVE" in text, f"有 key + live=True 应显 LIVE,实际 text={text!r}"
    assert "未配 key" not in text


def test_splash_live_without_key_downgrades_and_warns():
    """live=True + has_key=False → 不显 `✳ LIVE`,改显 `⚠ 未配 key` + 指引文案。
    防止徽标撒谎说"真能用"实际一跑就 401。"""
    from argos_agent.tui.widgets.splash import StartupSplash
    sp = StartupSplash(model_label="M3", tier="sonnet", live=True, has_key=False)
    text = sp.renderable_text
    assert "✳ LIVE" not in text, (
        f"无 key 时绝不能显 LIVE 徽标(撒了谎),实际 text={text!r}"
    )
    assert "未配 key" in text, f"无 key 应显未配 key 警告,实际 text={text!r}"
    # 指引用户去 /setup 或 env var
    assert "/setup" in text or "setup" in text, (
        f"无 key 警告应带'去 setup'指引,实际 text={text!r}"
    )


def test_splash_demo_mode_unchanged_when_no_key():
    """live=False(demo 模式)+ has_key=False → 仍显 `⚠ DEMO 演示`(向后兼容)。"""
    from argos_agent.tui.widgets.splash import StartupSplash
    sp = StartupSplash(model_label="M3", tier="sonnet", live=False, has_key=False)
    text = sp.renderable_text
    assert "DEMO" in text
    assert "✳ LIVE" not in text


def test_splash_default_has_key_true_preserves_existing_callers():
    """默认 has_key=True → 旧调用方(没传 has_key 的)行为不变,不显未配 key 警告。"""
    from argos_agent.tui.widgets.splash import StartupSplash
    sp = StartupSplash(model_label="M3", tier="sonnet", live=True)  # 无 has_key
    text = sp.renderable_text
    assert "✳ LIVE" in text
    assert "未配 key" not in text
