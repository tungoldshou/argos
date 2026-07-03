# tests/tui/test_diff_view_audit.py
from __future__ import annotations

import inspect
import sys

import pytest
from rich.text import Text


_PASS    = "#9ECE6A"
_FAIL    = "#F7768E"
_DIM     = "#7E869C"   # $ink-dim
_INK     = "#C8CCDA"   # $ink

_MONOKAI_GREEN = "#A6E22E"
_MONOKAI_RED   = "#FF4689"



def test_no_monokai_import() -> None:
    import argos.tui.widgets.diff_view as m
    assert not hasattr(m, "Syntax"), (
        "diff_view 仍导出 Syntax — 应已移除 rich.syntax 导入"
    )


def test_no_rich_syntax_in_module_source() -> None:
    import argos.tui.widgets.diff_view as m
    src_file = inspect.getfile(m)
    with open(src_file, encoding="utf-8") as f:
        src = f.read()
    assert "rich.syntax" not in src, "源码仍含 rich.syntax 导入"
    import ast
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func_name = ""
            if isinstance(node.func, ast.Name):
                func_name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                func_name = node.func.attr
            if func_name == "Syntax":
                pytest.fail("源码仍含 Syntax(...) 调用 — 应已移除 rich.syntax 用法")



def test_module_exposes_token_constants() -> None:
    import argos.tui.widgets.diff_view as m
    assert hasattr(m, "_PASS"), "缺少 _PASS 常量"
    assert hasattr(m, "_FAIL"), "缺少 _FAIL 常量"
    assert hasattr(m, "_DIM"),  "缺少 _DIM 常量"
    assert hasattr(m, "_INK"),  "缺少 _INK 常量"


def test_token_pass_is_project_green_not_monokai() -> None:
    from argos.tui.widgets.diff_view import _PASS
    assert _PASS.upper() == "#9ECE6A", (
        f"_PASS={_PASS!r} — 应为 #9ECE6A($pass),不得为 monokai #A6E22E"
    )
    assert _PASS.upper() != _MONOKAI_GREEN, (
        "added 行绿色与 monokai function-name 绿撞色(#A6E22E),应改为 $pass #9ECE6A"
    )


def test_token_fail_is_project_red_not_monokai() -> None:
    from argos.tui.widgets.diff_view import _FAIL
    assert _FAIL.upper() == "#F7768E", (
        f"_FAIL={_FAIL!r} — 应为 #F7768E($fail),不得为 monokai #FF4689"
    )
    assert _FAIL.upper() != _MONOKAI_RED, (
        "removed 行红色与 monokai 撞色(#FF4689),应改为 $fail #F7768E"
    )


def test_token_dim_value() -> None:
    from argos.tui.widgets.diff_view import _DIM
    assert _DIM.upper() == "#7E869C", f"_DIM={_DIM!r} — 应为 $ink-dim #7E869C"


def test_token_ink_value() -> None:
    from argos.tui.widgets.diff_view import _INK
    assert _INK.upper() == "#C8CCDA", f"_INK={_INK!r} — 应为 $ink #C8CCDA"



def _spans_for(text: Text) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for span in text._spans:
        fragment = text.plain[span.start:span.end]
        result.setdefault(fragment.strip(), []).append(str(span.style))
    return result


@pytest.fixture
def sample_diff() -> str:
    return (
        "--- a/foo.py\n"
        "+++ b/foo.py\n"
        "@@ -1,3 +1,4 @@\n"
        " context line\n"
        "+added line\n"
        "-removed line\n"
    )


def test_render_diff_returns_rich_text(sample_diff: str) -> None:
    from argos.tui.widgets.diff_view import _render_diff
    result = _render_diff(sample_diff)
    assert isinstance(result, Text), (
        f"_render_diff 返回 {type(result).__name__},应为 rich.text.Text"
    )


def test_added_line_uses_pass_token(sample_diff: str) -> None:
    from argos.tui.widgets.diff_view import _render_diff
    result = _render_diff(sample_diff)
    plain = result.plain
    found = False
    for span in result._spans:
        fragment = plain[span.start:span.end]
        if fragment.startswith("+added"):
            assert str(span.style).upper() == _PASS.upper(), (
                f"added 行 style={span.style!r},应为 {_PASS}"
            )
            found = True
    assert found, "未找到 '+added' 行的 span"


def test_removed_line_uses_fail_token(sample_diff: str) -> None:
    from argos.tui.widgets.diff_view import _render_diff
    result = _render_diff(sample_diff)
    plain = result.plain
    found = False
    for span in result._spans:
        fragment = plain[span.start:span.end]
        if fragment.startswith("-removed"):
            assert str(span.style).upper() == _FAIL.upper(), (
                f"removed 行 style={span.style!r},应为 {_FAIL}"
            )
            found = True
    assert found, "未找到 '-removed' 行的 span"


def test_hunk_header_uses_dim_token(sample_diff: str) -> None:
    from argos.tui.widgets.diff_view import _render_diff
    result = _render_diff(sample_diff)
    plain = result.plain
    found = False
    for span in result._spans:
        fragment = plain[span.start:span.end]
        if fragment.startswith("@@"):
            assert str(span.style).upper() == _DIM.upper(), (
                f"hunk header style={span.style!r},应为 {_DIM}"
            )
            found = True
    assert found, "未找到 '@@' hunk header 行的 span"


def test_context_line_uses_ink_token(sample_diff: str) -> None:
    from argos.tui.widgets.diff_view import _render_diff
    result = _render_diff(sample_diff)
    plain = result.plain
    found = False
    for span in result._spans:
        fragment = plain[span.start:span.end]
        if "context line" in fragment:
            assert str(span.style).upper() == _INK.upper(), (
                f"context 行 style={span.style!r},应为 {_INK}"
            )
            found = True
    assert found, "未找到 'context line' 行的 span"


def test_added_line_not_monokai_green(sample_diff: str) -> None:
    from argos.tui.widgets.diff_view import _render_diff
    result = _render_diff(sample_diff)
    plain = result.plain
    for span in result._spans:
        fragment = plain[span.start:span.end]
        if fragment.startswith("+"):
            assert str(span.style).upper() != _MONOKAI_GREEN, (
                f"added 行 style={span.style!r} 仍是 monokai #A6E22E,违反铁律"
            )


def test_removed_line_not_monokai_red(sample_diff: str) -> None:
    from argos.tui.widgets.diff_view import _render_diff
    result = _render_diff(sample_diff)
    plain = result.plain
    for span in result._spans:
        fragment = plain[span.start:span.end]
        if fragment.startswith("-") and "---" not in fragment:
            assert str(span.style).upper() != _MONOKAI_RED, (
                f"removed 行 style={span.style!r} 仍是 monokai #FF4689,违反铁律"
            )



def test_diff_view_constructor_signature() -> None:
    from argos.tui.widgets.diff_view import DiffView
    sig = inspect.signature(DiffView.__init__)
    params = list(sig.parameters.keys())
    for name in ("path", "added", "removed", "unified"):
        assert name in params, f"DiffView.__init__ 缺少参数 {name!r}"
    for name in ("path", "added", "removed", "unified"):
        p = sig.parameters[name]
        assert p.kind == inspect.Parameter.KEYWORD_ONLY, (
            f"参数 {name!r} 应为 keyword-only,当前为 {p.kind}"
        )


def test_diff_view_instantiation() -> None:
    from argos.tui.widgets.diff_view import DiffView
    dv = DiffView(path="argos/replay.py", added=3, removed=1, unified="+new\n-old\n")
    assert dv.path == "argos/replay.py"
    assert dv.added == 3
    assert dv.removed == 1
    assert dv.unified == "+new\n-old\n"
    assert dv._unified == "+new\n-old\n"


def test_diff_view_border_title_format() -> None:
    from argos.tui.widgets.diff_view import DiffView
    dv = DiffView(path="foo/bar.py", added=2, removed=0, unified="")
    assert dv.border_title == "Edit · foo/bar.py", (
        f"border_title={dv.border_title!r},应为 'Edit · foo/bar.py'"
    )


def test_diff_view_border_subtitle_uses_unicode_minus() -> None:
    from argos.tui.widgets.diff_view import DiffView
    dv = DiffView(path="x.py", added=5, removed=2, unified="")
    subtitle = dv.border_subtitle
    assert "−" in subtitle, (
        f"border_subtitle={subtitle!r} 缺少 U+2212 减号 '−'"
    )
    assert subtitle == "+5 −2", (
        f"border_subtitle={subtitle!r},应为 '+5 −2'"
    )
    assert "-2" not in subtitle, (
        f"border_subtitle={subtitle!r} 仍用 ASCII '-' 而非 U+2212 '−'"
    )
