# tests/test_transcript_fences.py
from argos.tui.widgets.transcript import strip_code_fences


def test_strip_complete_block():
    assert strip_code_fences("前言\n```python\nx=1\n```\n后语") == "前言\n后语"


def test_strip_unclosed_trailing_block():
    # 流式中途:围栏开了还没闭合 → 从开围栏处剥掉
    assert strip_code_fences("写代码:\n```python\nwrite_file('a')") == "写代码:"


def test_no_fence_unchanged():
    assert strip_code_fences("没有代码块,只有 `inline` 行内码") == "没有代码块,只有 `inline` 行内码"


def test_multiple_blocks():
    assert strip_code_fences("a\n```py\n1\n```\nb\n```\n2\n```\nc") == "a\nb\nc"
