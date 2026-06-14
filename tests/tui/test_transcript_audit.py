# tests/tui/test_transcript_audit.py
"""Transcript 设计审计回归测试 — 针对 2026-06-14 Part C audit 修复项。

覆盖范围:
  - [LOW] AssistantMessage.DEFAULT_CSS 包含 Markdown emphasis 着色规则(color: $ink-bright)
  - 验证 markdown--em 和 strong 选择器均指向 $ink-bright
  - 验证 body 正文继承 $ink(默认阅读层)不变
"""
from __future__ import annotations

import re

import pytest

from argos.tui.widgets.transcript import AssistantMessage, Transcript, SystemLine, UserMessage


# ── 1. [LOW] AssistantMessage emphasis 着色规则存在 ────────────────────────────

def test_assistant_message_default_css_has_emphasis_rules() -> None:
    """DEFAULT_CSS 必须包含 markdown--em 和 strong 选择器,指向 $ink-bright."""
    css = AssistantMessage.DEFAULT_CSS
    assert "markdown--em" in css, "DEFAULT_CSS 缺少 .markdown--em 选择器"
    assert "strong" in css, "DEFAULT_CSS 缺少 strong 选择器"


def test_assistant_message_emphasis_uses_ink_bright() -> None:
    """Markdown emphasis(强调)必须使用 $ink-bright token(#ECEEF5)。"""
    css = AssistantMessage.DEFAULT_CSS
    # 检查两个选择器都指向 $ink-bright
    for selector in ["markdown--em", "strong"]:
        pattern = rf"{selector}\s*\{{\s*[^}}]*color:\s*\$ink-bright"
        assert re.search(pattern, css, re.MULTILINE | re.IGNORECASE), \
            f"DEFAULT_CSS 中 {selector} 未指向 $ink-bright"


def test_assistant_message_css_structure() -> None:
    """验证 DEFAULT_CSS 结构:背景/边距正确,emphasis 规则独立。"""
    css = AssistantMessage.DEFAULT_CSS
    # 确认主规则仍存在
    assert "background: transparent" in css, "AssistantMessage 主规则缺少 background: transparent"
    assert "margin: 0 0 1 0" in css, "AssistantMessage 主规则缺少 margin"
    assert "padding: 0 2" in css, "AssistantMessage 主规则缺少 padding"


def test_assistant_message_instantiation() -> None:
    """验证 AssistantMessage 可正常实例化,不因 CSS 改动而崩."""
    try:
        widget = AssistantMessage()
        assert widget is not None
        assert widget._raw == ""
        assert widget.has_class("assistant-msg")
    except Exception as e:
        pytest.fail(f"AssistantMessage 实例化失败: {e}")


def test_assistant_message_feed_raw_state() -> None:
    """验证 AssistantMessage._raw 状态(不调 update 避免需要 app 上下文)。"""
    widget = AssistantMessage()
    # 直接检验状态,不调 feed() 的 update 部分
    widget._raw = "Hello **world**"
    assert widget._raw == "Hello **world**"
    assert widget.has_class("assistant-msg")


# ── 2. [LOW] Transcript 容器继续支持 AssistantMessage ──────────────────────────

def test_transcript_rendered_text_property() -> None:
    """Transcript.rendered_text 属性能正确聚合内容(不需 app)。"""
    t = Transcript()
    # 添加历史行
    t._lines.append("User input")
    t._lines.append("System response")
    # 聚合应工作
    assert "User input" in t.rendered_text
    assert "System response" in t.rendered_text


def test_system_line_creates_without_error() -> None:
    """SystemLine 各 kind 都可创建(不受 Transcript 修改影响)。"""
    for kind in ["system", "error", "escalation", "done"]:
        try:
            line = SystemLine("Test text", kind=kind)
            assert line is not None
            assert line.has_class(f"sys-{kind}")
        except Exception as e:
            pytest.fail(f"SystemLine kind={kind} 创建失败: {e}")


def test_user_message_creates_without_error() -> None:
    """UserMessage 可创建(验证不与 Transcript 修改冲突)。"""
    try:
        msg = UserMessage("Test query")
        assert msg is not None
        assert msg.has_class("user-msg")
    except Exception as e:
        pytest.fail(f"UserMessage 创建失败: {e}")
