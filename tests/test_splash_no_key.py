from __future__ import annotations


def test_splash_live_with_key_shows_live_badge():
    from argos.tui.widgets.splash import StartupSplash
    sp = StartupSplash(model_label="M3", tier="sonnet", live=True, has_key=True)
    text = sp.renderable_text
    assert "LIVE" in text, f"有 key + live=True 应显 LIVE,实际 text={text!r}"
    assert "✳" not in text, f"v3 禁止 ✳ 字形,实际 text={text!r}"
    assert "未配 key" not in text


def test_splash_live_without_key_downgrades_and_warns():
    from argos.tui.widgets.splash import StartupSplash
    sp = StartupSplash(model_label="M3", tier="sonnet", live=True, has_key=False)
    text = sp.renderable_text
    assert "LIVE" not in text, (
        f"无 key 时绝不能显 LIVE 徽标(撒了谎),实际 text={text!r}"
    )
    assert "未配 key" in text, f"无 key 应显未配 key 警告,实际 text={text!r}"
    assert "/setup" in text or "setup" in text, (
        f"无 key 警告应带'去 setup'指引,实际 text={text!r}"
    )


def test_splash_default_has_key_true_preserves_existing_callers():
    from argos.tui.widgets.splash import StartupSplash
    sp = StartupSplash(model_label="M3", tier="sonnet", live=True)
    text = sp.renderable_text
    assert "LIVE" in text
    assert "✳" not in text, f"v3 禁止 ✳ 字形,实际 text={text!r}"
    assert "未配 key" not in text
