"""Internal documentation."""
from __future__ import annotations

import pytest

from argos.perception.actions import ComputerAction, TEXT_MAX_LEN



def test_screenshot_no_fields():
    """Internal documentation."""
    a = ComputerAction(kind="screenshot")
    assert a.kind == "screenshot"
    assert a.x is None and a.y is None
    assert a.text is None and a.app is None


def test_click_with_coords():
    a = ComputerAction(kind="click", x=100, y=200)
    assert a.x == 100 and a.y == 200


def test_double_click_with_coords():
    a = ComputerAction(kind="double_click", x=0, y=0)
    assert a.kind == "double_click"


def test_type_text_with_text():
    a = ComputerAction(kind="type_text", text="hello")
    assert a.text == "hello"


def test_key_with_combo():
    a = ComputerAction(kind="key", text="command+c")
    assert a.text == "command+c"


def test_scroll_with_coords_and_dy():
    a = ComputerAction(kind="scroll", x=50, y=100, text="3")
    assert a.x == 50 and a.text == "3"


def test_open_app_with_valid_name():
    a = ComputerAction(kind="open_app", app="Finder")
    assert a.app == "Finder"


def test_open_app_with_dots_and_dashes():
    """Internal documentation."""
    a = ComputerAction(kind="open_app", app="Some-App.v2")
    assert a.app == "Some-App.v2"


def test_frozen_dataclass():
    """Internal documentation."""
    a = ComputerAction(kind="screenshot")
    with pytest.raises((AttributeError, TypeError)):
        a.kind = "click"  # type: ignore[misc]



def test_negative_x_raises():
    with pytest.raises(ValueError, match="x 必须 >= 0"):
        ComputerAction(kind="click", x=-1, y=0)


def test_negative_y_raises():
    with pytest.raises(ValueError, match="y 必须 >= 0"):
        ComputerAction(kind="click", x=0, y=-5)


def test_zero_coord_is_valid():
    """Internal documentation."""
    a = ComputerAction(kind="click", x=0, y=0)
    assert a.x == 0 and a.y == 0



def test_text_at_limit_is_valid():
    a = ComputerAction(kind="type_text", text="a" * TEXT_MAX_LEN)
    assert len(a.text) == TEXT_MAX_LEN


def test_text_over_limit_raises():
    with pytest.raises(ValueError, match="超过上限"):
        ComputerAction(kind="type_text", text="x" * (TEXT_MAX_LEN + 1))



def test_app_name_with_semicolon_raises():
    """Internal documentation."""
    with pytest.raises(ValueError, match="含非法字符"):
        ComputerAction(kind="open_app", app="Finder; rm -rf /")


def test_app_name_with_slash_raises():
    """Internal documentation."""
    with pytest.raises(ValueError, match="含非法字符"):
        ComputerAction(kind="open_app", app="../../bin/bash")


def test_app_name_with_backtick_raises():
    with pytest.raises(ValueError, match="含非法字符"):
        ComputerAction(kind="open_app", app="`whoami`")



def test_click_without_coords_raises():
    with pytest.raises(ValueError, match="需要 x 和 y 坐标"):
        ComputerAction(kind="click")


def test_click_partial_coord_raises():
    with pytest.raises(ValueError, match="需要 x 和 y 坐标"):
        ComputerAction(kind="click", x=10)


def test_double_click_without_coords_raises():
    with pytest.raises(ValueError, match="需要 x 和 y 坐标"):
        ComputerAction(kind="double_click", y=50)


def test_type_text_without_text_raises():
    with pytest.raises(ValueError, match="需要非空 text"):
        ComputerAction(kind="type_text")


def test_type_text_empty_text_raises():
    with pytest.raises(ValueError, match="需要非空 text"):
        ComputerAction(kind="type_text", text="")


def test_key_without_text_raises():
    with pytest.raises(ValueError, match="需要非空 text"):
        ComputerAction(kind="key")


def test_scroll_without_coords_raises():
    with pytest.raises(ValueError, match="需要 x 和 y 坐标"):
        ComputerAction(kind="scroll", text="3")


def test_scroll_without_text_raises():
    with pytest.raises(ValueError, match="需要 text=str"):
        ComputerAction(kind="scroll", x=0, y=0)


def test_open_app_without_app_raises():
    with pytest.raises(ValueError, match="需要非空 app"):
        ComputerAction(kind="open_app")


def test_open_app_empty_app_raises():
    with pytest.raises(ValueError, match="需要非空 app"):
        ComputerAction(kind="open_app", app="")
