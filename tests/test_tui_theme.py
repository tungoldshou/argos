# tests/test_tui_theme.py
"""Internal documentation."""
import pytest
from argos.tui.app import ArgosApp
from argos.tui.fakeloop import FakeLoop


@pytest.mark.asyncio
async def test_argos_night_theme_registered_and_applied():
    app = ArgosApp(loop_factory=lambda **kw: FakeLoop())
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.theme == "argos-night", "应默认应用 argos-night 主题"
        assert "argos-night" in app.available_themes, "主题必须已注册"


@pytest.mark.asyncio
async def test_argos_night_tokens():
    """Internal documentation."""
    from argos.tui.theme import ARGOS_NIGHT

    assert ARGOS_NIGHT.dark is True

    assert ARGOS_NIGHT.primary.lower() == "#d9a85c", "primary 应为 $eye 暖金"
    assert ARGOS_NIGHT.accent is not None
    assert ARGOS_NIGHT.accent.lower() == "#d9a85c", "accent == primary == $eye"

    assert ARGOS_NIGHT.secondary is not None
    assert ARGOS_NIGHT.secondary.lower() == "#7aa2f7", "secondary 应为 $plan 蓝"

    assert ARGOS_NIGHT.foreground is not None
    assert ARGOS_NIGHT.foreground.lower() == "#c8ccda", "foreground 应为 $ink"

    assert ARGOS_NIGHT.background is not None
    assert ARGOS_NIGHT.background.lower() == "#0b0c10", "background 应为 $abyss"

    assert ARGOS_NIGHT.surface is not None
    assert ARGOS_NIGHT.surface.lower() == "#0e0f15", "surface 应为 $well"

    assert ARGOS_NIGHT.panel is not None
    assert ARGOS_NIGHT.panel.lower() == "#1b1d29", "panel 应为 $raise"

    assert ARGOS_NIGHT.success is not None
    assert ARGOS_NIGHT.success.lower() == "#9ece6a", "success 应为 $pass 绿"

    assert ARGOS_NIGHT.warning is not None
    assert ARGOS_NIGHT.warning.lower() == "#ff9e64", "warning 应为 $unverif 橙(裁决①更橙更饱和)"

    assert ARGOS_NIGHT.error is not None
    assert ARGOS_NIGHT.error.lower() == "#f7768e", "error 应为 $fail 红"

    # boost = $raise-2
    assert ARGOS_NIGHT.boost is not None
    assert ARGOS_NIGHT.boost.lower() == "#23263a", "boost 应为 $raise-2"


def test_argos_night_variables_background_layers():
    """Internal documentation."""
    from argos.tui.theme import ARGOS_NIGHT

    v = ARGOS_NIGHT.variables
    assert v["abyss"] == "#0B0C10"
    assert v["well"] == "#0E0F15"
    assert v["stream"] == "#13141B"
    assert v["raise"] == "#1B1D29"
    assert v["raise-2"] == "#23263A"
    assert v["hairline"] == "#23252E"
    assert v["hairline-lit"] == "#2E3142"


def test_argos_night_variables_ink_scale():
    """Internal documentation."""
    from argos.tui.theme import ARGOS_NIGHT

    v = ARGOS_NIGHT.variables
    assert v["ink-bright"] == "#ECEEF5"
    assert v["ink"] == "#C8CCDA"
    assert v["ink-dim"] == "#7E869C"
    assert v["ink-faint"] == "#6B7494"
    assert v["ink-ghost"] == "#3A4055"


def test_argos_night_variables_eye_system():
    """Internal documentation."""
    from argos.tui.theme import ARGOS_NIGHT

    v = ARGOS_NIGHT.variables
    assert v["eye-soft"] == "#A8854A"
    assert v["eye"] == "#D9A85C"
    assert v["eye-glow"] == "#F0C078"
    assert v["eye"] != "#FF9E64", "金橙分家：$eye 不得为 $unverif 橙"
    assert v["eye-glow"] != "#FF9E64", "金橙分家：$eye-glow 不得为 $unverif 橙"


def test_argos_night_variables_semantic_colors():
    """Internal documentation."""
    from argos.tui.theme import ARGOS_NIGHT

    v = ARGOS_NIGHT.variables
    assert v["pass"] == "#9ECE6A"
    assert v["pass-weak"] == "#73A857"
    assert v["fail"] == "#F7768E"
    assert v["unverif"] == "#FF9E64"
    assert v["unverif-deep"] == "#9A6E2E"
    assert v["cyan"] == "#7DCFFF"

    assert v["pass"] != v["pass-weak"], "E4 防火墙：强通过 vs 弱通过颜色必须不同"

    assert v["unverif"] != v["eye"], "金橙分家：$unverif 不得等于 $eye"


def test_argos_night_variables_plan_and_cursor():
    """Internal documentation."""
    from argos.tui.theme import ARGOS_NIGHT

    v = ARGOS_NIGHT.variables
    assert v["plan"] == "#7AA2F7"
    assert v["block-cursor-foreground"] == "#0B0C10"
    assert v["block-cursor-background"] == "#F0C078"


def test_argos_night_variables_scrollbar_and_border():
    """Internal documentation."""
    from argos.tui.theme import ARGOS_NIGHT

    v = ARGOS_NIGHT.variables
    assert v["scrollbar"] == "#1B1D29"
    assert v["scrollbar-hover"] == "#23263A"
    assert v["border"] == "#2E3142"


def test_argos_night_variables_text_muted_compat():
    """Internal documentation."""
    from argos.tui.theme import ARGOS_NIGHT

    v = ARGOS_NIGHT.variables
    assert "text-muted" in v, "$text-muted 向后兼容 token 必须存在"
    assert v["text-muted"] == v["ink-dim"], "$text-muted 必须映射到 $ink-dim"


def test_argos_night_name_unchanged():
    """Internal documentation."""
    from argos.tui.theme import ARGOS_NIGHT

    assert ARGOS_NIGHT.name == "argos-night"


def test_argos_night_variables_count():
    """Internal documentation."""
    from argos.tui.theme import ARGOS_NIGHT

    assert len(ARGOS_NIGHT.variables) >= 28, (
        f"variables 数量不足，期望 >=28，实际 {len(ARGOS_NIGHT.variables)}"
    )
