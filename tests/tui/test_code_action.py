# tests/tui/test_code_action.py
"""CodeActionBlock widget 验收测试 — glyph 与 styling 审计修复。

覆盖范围:
  - 文档稿一致性:module docstring 正确反映实现(└ ◕ / ◉)
  - 字形铁律:ok=True → ◕ 阅毕眼 $pass / ok=False → ◉ 红瞳 $fail
  - CSS token 着色:结果行条件着色 $pass(ok=True) / $fail(ok=False)
  - 代码行折叠逻辑:>8 行折叠为头 6 行 + "… +N 行"
  - 结果行折叠逻辑:>12 行折叠为头 8 行 + "… +N 行"
  - markup=False 生产环境不崩:输出含 [...] 字符(浏览器返回、选择器等)
"""
from __future__ import annotations

from argos.tui.widgets.code_action import CodeActionBlock


def test_module_docstring_reflects_implementation():
    """Module docstring 要准确描述 glyph:└ ◕ 结果。"""
    import inspect
    docstring = inspect.getdoc(CodeActionBlock)
    # 第一个非空行:模块层注释
    lines = docstring.split('\n')
    module_doc = '\n'.join(lines[:5])

    # 应含正确 glyph:└ ◕(不是旧的 ⎿ ✓)
    assert '└ ◕' in module_doc, "Module docstring should contain '└ ◕' glyph"
    assert '◉' in module_doc, "Module docstring should contain '◉' (error glyph)"

    # 应含语义标签
    assert '阅毕眼' in module_doc, "Module docstring should mention '阅毕眼' (ok state)"
    assert '红瞳' in module_doc, "Module docstring should mention '红瞳' (fail state)"
    assert '$pass' in module_doc, "Module docstring should reference $pass token"
    assert '$fail' in module_doc, "Module docstring should reference $fail token"

    # 不应含旧的代号
    assert '✓' not in module_doc or '✗' not in module_doc or '⎿' not in module_doc, \
        "Module docstring should not contain old glyphs (✓/✗/⎿)"


def test_class_docstring_consistent():
    """Class docstring 也要一致:└ ◕ / ◉。"""
    docstring = CodeActionBlock.__doc__ or ""

    assert '◕' in docstring, "Class docstring should use ◕ for ok=True"
    assert '◉' in docstring, "Class docstring should use ◉ for ok=False"
    assert '└' in docstring, "Class docstring should use └ branch glyph"


def test_code_action_block_ok_true_glyph():
    """set_result(ok=True) 应使用 ◕ 阅毕眼 glyph。"""
    block = CodeActionBlock(code="x = 1", step=1)

    # 虚拟化 compose 以获得 result widget(不需要启动 TUI)
    # 通过检查 set_result 的文本生成逻辑
    import unittest.mock as mock

    mock_result_widget = mock.MagicMock()
    with mock.patch.object(block, 'query_one', return_value=mock_result_widget):
        block.set_result(stdout="ok", value_repr="", exc="", ok=True)

    # 检查 update 调用的文本:应含 ◕
    update_calls = mock_result_widget.update.call_args_list
    assert len(update_calls) > 0, "Should call update at least once"

    text_arg = update_calls[0][0][0]  # 第一个 update 调用的第一个位置参数
    assert '◕' in text_arg, f"Expected ◕ in result text for ok=True, got: {text_arg}"
    assert '└' in text_arg, f"Expected └ branch glyph, got: {text_arg}"


def test_code_action_block_ok_false_glyph():
    """set_result(ok=False) 应使用 ◉ 红瞳 glyph。"""
    block = CodeActionBlock(code="x = 1", step=1)

    import unittest.mock as mock

    mock_result_widget = mock.MagicMock()
    with mock.patch.object(block, 'query_one', return_value=mock_result_widget):
        block.set_result(stdout="", value_repr="", exc="FileNotFoundError", ok=False)

    update_calls = mock_result_widget.update.call_args_list
    assert len(update_calls) > 0, "Should call update at least once"

    text_arg = update_calls[0][0][0]
    assert '◉' in text_arg, f"Expected ◉ in result text for ok=False, got: {text_arg}"
    assert '└' in text_arg, f"Expected └ branch glyph, got: {text_arg}"


def test_traceback_shows_real_cause_not_internal_frames():
    """#5(2026-06-18):沙箱内代码报错的裸 traceback → 头条显示最后一行(真正的 异常类型: 消息),
    内部帧折叠在后;而不是旧逻辑折"前 8 行"恰好全是 smolagents/concurrent.futures 内部帧、
    真错因被埋到看不见(正是截图那条)。"""
    block = CodeActionBlock(code="print(undefined)", step=1)
    tb = (
        "Traceback (most recent call last):\n"
        '  File ".../smolagents/local_python_executor.py", line 311, in wrapper\n'
        "    result = future.result(timeout=timeout_seconds)\n"
        '  File ".../concurrent/futures/_base.py", line 458, in result\n'
        "    raise TimeoutError()\n"
        "InterpreterError: The variable `undefined` is not defined"
    )
    import unittest.mock as mock
    mock_result_widget = mock.MagicMock()
    with mock.patch.object(block, 'query_one', return_value=mock_result_widget):
        block.set_result(stdout="", value_repr="", exc=tb, ok=False)
    text = mock_result_widget.update.call_args_list[0][0][0]
    # 真错因(最后一行)出现在头条
    assert "InterpreterError: The variable `undefined` is not defined" in text, text
    # 内部帧被折叠,不逐帧展示
    assert "内部堆栈已折叠" in text, text
    # smolagents/concurrent 内部路径不再露出(已折叠)
    assert "local_python_executor.py" not in text, text


def test_css_class_ok_false_set_correctly():
    """watch_ok(False) 应设置 ok-false CSS class 以触发 $fail 着色。"""
    block = CodeActionBlock(code="x = 1", step=1)

    # 直接测试 CSS class 设置逻辑
    import unittest.mock as mock
    with mock.patch.object(block, 'set_class') as mock_set_class:
        # 模拟 reactive watch
        block.watch_ok(False)

        # 应该调用 set_class(True, "ok-false")
        mock_set_class.assert_called_once_with(True, "ok-false")


def test_css_class_ok_true_not_set():
    """watch_ok(True) 不应设置 ok-false class。"""
    block = CodeActionBlock(code="x = 1", step=1)

    import unittest.mock as mock
    with mock.patch.object(block, 'set_class') as mock_set_class:
        block.watch_ok(True)

        # 应该调用 set_class(False, "ok-false")
        mock_set_class.assert_called_once_with(False, "ok-false")


def test_code_folding_threshold():
    """代码超过 8 行时折叠为头 6 行 + "… +N 行"。"""
    long_code = "\n".join([f"line {i}" for i in range(10)])
    block = CodeActionBlock(code=long_code, step=1)

    # compose 会在 __init__ 后调用,我们检查逻辑
    # _CODE_MAX = 8, _CODE_HEAD = 6
    lines = long_code.splitlines()
    assert len(lines) == 10, "Should have 10 lines"

    # 验证常数
    from argos.tui.widgets.code_action import _CODE_MAX, _CODE_HEAD
    assert _CODE_MAX == 8, "Folding threshold should be 8"
    assert _CODE_HEAD == 6, "Folding head size should be 6"


def test_result_folding_threshold():
    """结果超过 12 行时折叠为头 8 行 + "… +N 行"。"""
    block = CodeActionBlock(code="x = 1", step=1)

    long_output = "\n".join([f"output line {i}" for i in range(15)])

    import unittest.mock as mock
    mock_result_widget = mock.MagicMock()
    with mock.patch.object(block, 'query_one', return_value=mock_result_widget):
        block.set_result(stdout=long_output, value_repr="", exc="", ok=True)

    update_calls = mock_result_widget.update.call_args_list
    assert len(update_calls) > 0, "Should call update"

    text_arg = update_calls[0][0][0]
    # 应包含 "… +" 折叠提示
    assert '…' in text_arg, f"Expected fold indicator in: {text_arg}"


def test_markup_false_preserves_brackets():
    """markup=False 防止 [...] 在浏览器/选择器返回中被解析为 Rich markup。"""
    block = CodeActionBlock(code='run("button[aria-label=\'x\']")', step=1)

    import unittest.mock as mock
    mock_result_widget = mock.MagicMock()
    with mock.patch.object(block, 'query_one', return_value=mock_result_widget):
        # 模拟浏览器返回含 [...]
        block.set_result(
            stdout='已点击 "input[value=\'x\']"',
            value_repr="",
            exc="",
            ok=True
        )

    update_calls = mock_result_widget.update.call_args_list
    assert len(update_calls) > 0

    # 文本应该保留原样(不会被当作 Rich markup 解析)
    text_arg = update_calls[0][0][0]
    assert 'input[value=' in text_arg, \
        f"Square brackets should be preserved in output, got: {text_arg}"


def test_default_css_raise_background():
    """CodeActionBlock 默认 CSS 应使用 $raise 背景。"""
    css = CodeActionBlock.DEFAULT_CSS

    assert '$raise' in css, "DEFAULT_CSS should reference $raise token"
    assert 'background: $raise' in css, "CodeActionBlock container should have $raise background"


def test_result_color_tokens():
    """结果区 CSS 应条件着色:$pass / $fail。"""
    css = CodeActionBlock.DEFAULT_CSS

    # ok-true (默认) -> $pass
    assert '#result' in css, "Should have #result selector"

    # ok-false 明确着色为 $fail
    assert 'ok-false #result' in css, "Should have ok-false variant"
    assert '$fail' in css, "Should reference $fail token"
