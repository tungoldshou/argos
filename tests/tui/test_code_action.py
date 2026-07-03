# tests/tui/test_code_action.py
from __future__ import annotations

from argos.tui.widgets.code_action import CodeActionBlock


def test_module_docstring_reflects_implementation():
    import inspect
    docstring = inspect.getdoc(CodeActionBlock)
    lines = docstring.split('\n')
    module_doc = '\n'.join(lines[:5])

    assert '└ ◕' in module_doc, "Module docstring should contain '└ ◕' glyph"
    assert '◉' in module_doc, "Module docstring should contain '◉' (error glyph)"

    assert 'ok eye' in module_doc, "Module docstring should mention ok eye state"
    assert 'fail eye' in module_doc, "Module docstring should mention fail eye state"
    assert '$pass' in module_doc, "Module docstring should reference $pass token"
    assert '$fail' in module_doc, "Module docstring should reference $fail token"

    assert '✓' not in module_doc or '✗' not in module_doc or '⎿' not in module_doc,\
        "Module docstring should not contain old glyphs (✓/✗/⎿)"


def test_class_docstring_consistent():
    docstring = CodeActionBlock.__doc__ or ""

    assert '◕' in docstring, "Class docstring should use ◕ for ok=True"
    assert '◉' in docstring, "Class docstring should use ◉ for ok=False"
    assert '└' in docstring, "Class docstring should use └ branch glyph"


def test_code_action_block_ok_true_glyph():
    block = CodeActionBlock(code="x = 1", step=1)

    import unittest.mock as mock

    mock_result_widget = mock.MagicMock()
    with mock.patch.object(block, 'query_one', return_value=mock_result_widget):
        block.set_result(stdout="ok", value_repr="", exc="", ok=True)

    update_calls = mock_result_widget.update.call_args_list
    assert len(update_calls) > 0, "Should call update at least once"

    text_arg = update_calls[0][0][0]
    assert '◕' in text_arg, f"Expected ◕ in result text for ok=True, got: {text_arg}"
    assert '└' in text_arg, f"Expected └ branch glyph, got: {text_arg}"


def test_code_action_block_ok_false_glyph():
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
    assert "InterpreterError: The variable `undefined` is not defined" in text, text
    assert "内部堆栈已折叠" in text, text
    assert "local_python_executor.py" not in text, text


def test_css_class_ok_false_set_correctly():
    block = CodeActionBlock(code="x = 1", step=1)

    import unittest.mock as mock
    with mock.patch.object(block, 'set_class') as mock_set_class:
        block.watch_ok(False)

        mock_set_class.assert_called_once_with(True, "ok-false")


def test_css_class_ok_true_not_set():
    block = CodeActionBlock(code="x = 1", step=1)

    import unittest.mock as mock
    with mock.patch.object(block, 'set_class') as mock_set_class:
        block.watch_ok(True)

        mock_set_class.assert_called_once_with(False, "ok-false")


def test_code_folding_threshold():
    long_code = "\n".join([f"line {i}" for i in range(10)])
    block = CodeActionBlock(code=long_code, step=1)

    # _CODE_MAX = 8, _CODE_HEAD = 6
    lines = long_code.splitlines()
    assert len(lines) == 10, "Should have 10 lines"

    from argos.tui.widgets.code_action import _CODE_MAX, _CODE_HEAD
    assert _CODE_MAX == 8, "Folding threshold should be 8"
    assert _CODE_HEAD == 6, "Folding head size should be 6"


def test_result_folding_threshold():
    block = CodeActionBlock(code="x = 1", step=1)

    long_output = "\n".join([f"output line {i}" for i in range(15)])

    import unittest.mock as mock
    mock_result_widget = mock.MagicMock()
    with mock.patch.object(block, 'query_one', return_value=mock_result_widget):
        block.set_result(stdout=long_output, value_repr="", exc="", ok=True)

    update_calls = mock_result_widget.update.call_args_list
    assert len(update_calls) > 0, "Should call update"

    text_arg = update_calls[0][0][0]
    assert '…' in text_arg, f"Expected fold indicator in: {text_arg}"


def test_markup_false_preserves_brackets():
    block = CodeActionBlock(code='run("button[aria-label=\'x\']")', step=1)

    import unittest.mock as mock
    mock_result_widget = mock.MagicMock()
    with mock.patch.object(block, 'query_one', return_value=mock_result_widget):
        block.set_result(
            stdout='已点击 "input[value=\'x\']"',
            value_repr="",
            exc="",
            ok=True
        )

    update_calls = mock_result_widget.update.call_args_list
    assert len(update_calls) > 0

    text_arg = update_calls[0][0][0]
    assert 'input[value=' in text_arg,\
        f"Square brackets should be preserved in output, got: {text_arg}"


def test_default_css_raise_background():
    css = CodeActionBlock.DEFAULT_CSS

    assert '$raise' in css, "DEFAULT_CSS should reference $raise token"
    assert 'background: $raise' in css, "CodeActionBlock container should have $raise background"


def test_result_color_tokens():
    css = CodeActionBlock.DEFAULT_CSS

    assert '#result' in css, "Should have #result selector"

    assert 'ok-false #result' in css, "Should have ok-false variant"
    assert '$fail' in css, "Should reference $fail token"
