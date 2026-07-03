from __future__ import annotations

import json

import pytest
from argos.tui.app import ArgosApp
from argos.tui.fakeloop import FakeLoop
from argos.tui.widgets.splash import StartupSplash


@pytest.mark.asyncio
async def test_splash_shown_on_mount_with_mode_badge():
    app = ArgosApp(loop_factory=lambda **kw: FakeLoop())
    async with app.run_test() as pilot:
        await pilot.pause()
        sp = list(app.query(StartupSplash))
        assert len(sp) == 1
        assert "ARGOS" in sp[0].renderable_text
        assert "DEMO" not in sp[0].renderable_text


@pytest.mark.asyncio
async def test_splash_bad_model_config_does_not_crash(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(tmp_path))
    (tmp_path / "config.json").write_text(json.dumps({
        "active": "bad",
        "models": {"bad": {
            "protocol": "openai",
            "base_url": "https://x/v1",
            "model": "bad",
            "api_key_env": "BAD.NAME_KEY",
        }},
    }))

    app = ArgosApp(loop_factory=lambda **kw: FakeLoop())
    async with app.run_test() as pilot:
        await pilot.pause()
        sp = app.query_one(StartupSplash)
        text = sp.renderable_text
        assert "LIVE" not in text
        assert "未配 key" in text
        assert "配置错误" in text


@pytest.mark.asyncio
async def test_splash_cleared_on_first_run():
    app = ArgosApp(loop_factory=lambda **kw: FakeLoop())
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.start_run("演示任务")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert len(list(app.query(StartupSplash))) == 0, "起一轮后 splash 应被清除"


def test_splash_no_ascii_giant_eye():
    sp = StartupSplash(model_label="M3", tier="sonnet", live=True, has_key=True)
    text = sp.renderable_text
    assert "╔" not in text and "╗" not in text and "╚" not in text and "╝" not in text, (
        f"v3 禁止旧 box-drawing 大字 logo 字符,实际 text={text!r}"
    )


def test_splash_has_key_live_shows_live_badge():
    sp = StartupSplash(model_label="M3", tier="sonnet", live=True, has_key=True)
    text = sp.renderable_text
    assert "LIVE" in text, f"有 key + live=True 应含 LIVE,实际: {text!r}"
    assert "未配 key" not in text


def test_splash_has_key_false_no_live():
    sp = StartupSplash(model_label="M3", tier="sonnet", live=True, has_key=False)
    text = sp.renderable_text
    assert "LIVE" not in text, f"无 key 时绝不含 LIVE,实际: {text!r}"
    assert "未配 key" in text


def test_splash_no_key_shows_eye_not_live():
    sp = StartupSplash(model_label="M3", tier="sonnet", live=True, has_key=False)
    text = sp.renderable_text
    assert "◌" in text, f"无 key 应显 ◌ 空态眼,实际: {text!r}"
    assert "LIVE" not in text


def test_splash_advance_eye_api_exists():
    sp = StartupSplash(model_label="M3", tier="sonnet", live=True, has_key=True)
    sp.advance_eye("scan")
    sp.advance_eye("half")
    sp.advance_eye("focus")
    sp.advance_eye("open")
