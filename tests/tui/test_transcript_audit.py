# tests/tui/test_transcript_audit.py
from __future__ import annotations

import re

import pytest

from argos.tui.widgets.transcript import AssistantMessage, Transcript, SystemLine, UserMessage



def test_assistant_message_default_css_has_emphasis_rules() -> None:
    css = AssistantMessage.DEFAULT_CSS
    assert "markdown--em" in css, "DEFAULT_CSS 缺少 .markdown--em 选择器"
    assert "strong" in css, "DEFAULT_CSS 缺少 strong 选择器"


def test_assistant_message_emphasis_uses_ink_bright() -> None:
    css = AssistantMessage.DEFAULT_CSS
    for selector in ["markdown--em", "strong"]:
        pattern = rf"{selector}\s*\{{\s*[^}}]*color:\s*\$ink-bright"
        assert re.search(pattern, css, re.MULTILINE | re.IGNORECASE),\
            f"DEFAULT_CSS 中 {selector} 未指向 $ink-bright"


def test_assistant_message_css_structure() -> None:
    css = AssistantMessage.DEFAULT_CSS
    assert "background: transparent" in css, "AssistantMessage 主规则缺少 background: transparent"
    assert "margin: 0 0 1 0" in css, "AssistantMessage 主规则缺少 margin"
    assert "padding: 0 2" in css, "AssistantMessage 主规则缺少 padding"


def test_assistant_message_instantiation() -> None:
    try:
        widget = AssistantMessage()
        assert widget is not None
        assert widget._raw == ""
        assert widget.has_class("assistant-msg")
    except Exception as e:
        pytest.fail(f"AssistantMessage 实例化失败: {e}")


def test_assistant_message_feed_raw_state() -> None:
    widget = AssistantMessage()
    widget._raw = "Hello **world**"
    assert widget._raw == "Hello **world**"
    assert widget.has_class("assistant-msg")



def test_transcript_rendered_text_property() -> None:
    t = Transcript()
    t._lines.append("User input")
    t._lines.append("System response")
    assert "User input" in t.rendered_text
    assert "System response" in t.rendered_text


def test_system_line_creates_without_error() -> None:
    for kind in ["system", "error", "escalation", "done"]:
        try:
            line = SystemLine("Test text", kind=kind)
            assert line is not None
            assert line.has_class(f"sys-{kind}")
        except Exception as e:
            pytest.fail(f"SystemLine kind={kind} 创建失败: {e}")


def test_user_message_creates_without_error() -> None:
    try:
        msg = UserMessage("Test query")
        assert msg is not None
        assert msg.has_class("user-msg")
    except Exception as e:
        pytest.fail(f"UserMessage 创建失败: {e}")
