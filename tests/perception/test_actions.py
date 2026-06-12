"""tests/perception/test_actions.py — ComputerAction 入参校验测试。

全部为纯内存单元测试(不调任何 subprocess,不碰屏幕)。
"""
from __future__ import annotations

import pytest

from argos_agent.perception.actions import ComputerAction, TEXT_MAX_LEN


# ── 合法构造 ──────────────────────────────────────────────────────────────────

def test_screenshot_no_fields():
    """screenshot 无需坐标/文本/app。"""
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
    """app 名允许 点 和 连字符。"""
    a = ComputerAction(kind="open_app", app="Some-App.v2")
    assert a.app == "Some-App.v2"


def test_frozen_dataclass():
    """ComputerAction 是冻结 dataclass,不可修改字段。"""
    a = ComputerAction(kind="screenshot")
    with pytest.raises((AttributeError, TypeError)):
        a.kind = "click"  # type: ignore[misc]


# ── 坐标非负校验 ──────────────────────────────────────────────────────────────

def test_negative_x_raises():
    with pytest.raises(ValueError, match="x 必须 >= 0"):
        ComputerAction(kind="click", x=-1, y=0)


def test_negative_y_raises():
    with pytest.raises(ValueError, match="y 必须 >= 0"):
        ComputerAction(kind="click", x=0, y=-5)


def test_zero_coord_is_valid():
    """坐标 0 合法(左上角)。"""
    a = ComputerAction(kind="click", x=0, y=0)
    assert a.x == 0 and a.y == 0


# ── text 长度上限 ─────────────────────────────────────────────────────────────

def test_text_at_limit_is_valid():
    a = ComputerAction(kind="type_text", text="a" * TEXT_MAX_LEN)
    assert len(a.text) == TEXT_MAX_LEN


def test_text_over_limit_raises():
    with pytest.raises(ValueError, match="超过上限"):
        ComputerAction(kind="type_text", text="x" * (TEXT_MAX_LEN + 1))


# ── app 名白名单字符集 ────────────────────────────────────────────────────────

def test_app_name_with_semicolon_raises():
    """分号是 shell 注入字符,必须拒绝。"""
    with pytest.raises(ValueError, match="含非法字符"):
        ComputerAction(kind="open_app", app="Finder; rm -rf /")


def test_app_name_with_slash_raises():
    """斜杠不在白名单中。"""
    with pytest.raises(ValueError, match="含非法字符"):
        ComputerAction(kind="open_app", app="../../bin/bash")


def test_app_name_with_backtick_raises():
    with pytest.raises(ValueError, match="含非法字符"):
        ComputerAction(kind="open_app", app="`whoami`")


# ── 各 kind 必填字段缺失 ──────────────────────────────────────────────────────

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
