# tests/tui/test_diff_view_audit.py
"""DiffView 设计审计回归测试 — 针对 2026-06-14 Part C audit 修复项。

覆盖范围:
  - [MEDIUM] diff body 颜色不得走第三方 theme(monokai);只能用项目 token hex 常量:
      $pass   #9ECE6A — added 行('+')
      $fail   #F7768E — removed 行('-')
      $ink-dim #7E869C — hunk header('@')
      $ink    #C8CCDA — context 行
  - [LOW] added 行绿色必须是 $pass #9ECE6A,不得是 monokai #A6E22E(与 function 名撞色)
  - 验证 rich.syntax.Syntax / monokai 均未被引入
  - 验证 _render_diff() 输出的 Rich Text 样式正确
  - 验证 DiffView 公开构造函数签名兼容(API 不变)
"""
from __future__ import annotations

import inspect
import sys

import pytest
from rich.text import Text


# ── token hex 常量(单一来源:diff_view._PASS / _FAIL / _DIM / _INK) ──────────
_PASS    = "#9ECE6A"   # $pass  — 唯一的绿
_FAIL    = "#F7768E"   # $fail  — 唯一的红
_DIM     = "#7E869C"   # $ink-dim
_INK     = "#C8CCDA"   # $ink

# monokai 被替换掉的 hex(禁止重现)
_MONOKAI_GREEN = "#A6E22E"
_MONOKAI_RED   = "#FF4689"


# ── 1. [MEDIUM] 不得引入 rich.syntax.Syntax 或 monokai ──────────────────────

def test_no_monokai_import() -> None:
    """diff_view.py 不得导入 rich.syntax.Syntax(monokai 着色器已移除)。"""
    import argos.tui.widgets.diff_view as m
    assert not hasattr(m, "Syntax"), (
        "diff_view 仍导出 Syntax — 应已移除 rich.syntax 导入"
    )


def test_no_rich_syntax_in_module_source() -> None:
    """diff_view.py 不得含 'rich.syntax' import 语句或可执行的 monokai 调用。

    注意:docstring/注释里用 'monokai' 描述历史是允许的;
    我们只禁止可执行代码里出现(import / Syntax(... theme="monokai"))。
    """
    import argos.tui.widgets.diff_view as m
    src_file = inspect.getfile(m)
    with open(src_file, encoding="utf-8") as f:
        src = f.read()
    # 禁止实际的 import 语句
    assert "rich.syntax" not in src, "源码仍含 rich.syntax 导入"
    # 禁止 Syntax(..., theme="monokai") 调用(可执行代码中的字符串字面量)
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


# ── 2. [MEDIUM] token hex 常量来源正确 ──────────────────────────────────────

def test_module_exposes_token_constants() -> None:
    """diff_view 必须暴露 _PASS / _FAIL / _DIM / _INK 四个 hex 常量。"""
    import argos.tui.widgets.diff_view as m
    assert hasattr(m, "_PASS"), "缺少 _PASS 常量"
    assert hasattr(m, "_FAIL"), "缺少 _FAIL 常量"
    assert hasattr(m, "_DIM"),  "缺少 _DIM 常量"
    assert hasattr(m, "_INK"),  "缺少 _INK 常量"


def test_token_pass_is_project_green_not_monokai() -> None:
    """_PASS 必须是项目 $pass #9ECE6A,不得是 monokai #A6E22E。"""
    from argos.tui.widgets.diff_view import _PASS
    assert _PASS.upper() == "#9ECE6A", (
        f"_PASS={_PASS!r} — 应为 #9ECE6A($pass),不得为 monokai #A6E22E"
    )
    assert _PASS.upper() != _MONOKAI_GREEN, (
        "added 行绿色与 monokai function-name 绿撞色(#A6E22E),应改为 $pass #9ECE6A"
    )


def test_token_fail_is_project_red_not_monokai() -> None:
    """_FAIL 必须是项目 $fail #F7768E,不得是 monokai #FF4689。"""
    from argos.tui.widgets.diff_view import _FAIL
    assert _FAIL.upper() == "#F7768E", (
        f"_FAIL={_FAIL!r} — 应为 #F7768E($fail),不得为 monokai #FF4689"
    )
    assert _FAIL.upper() != _MONOKAI_RED, (
        "removed 行红色与 monokai 撞色(#FF4689),应改为 $fail #F7768E"
    )


def test_token_dim_value() -> None:
    """_DIM 必须对应 $ink-dim #7E869C。"""
    from argos.tui.widgets.diff_view import _DIM
    assert _DIM.upper() == "#7E869C", f"_DIM={_DIM!r} — 应为 $ink-dim #7E869C"


def test_token_ink_value() -> None:
    """_INK 必须对应 $ink #C8CCDA。"""
    from argos.tui.widgets.diff_view import _INK
    assert _INK.upper() == "#C8CCDA", f"_INK={_INK!r} — 应为 $ink #C8CCDA"


# ── 3. [MEDIUM] _render_diff 输出 Rich Text 着色正确 ────────────────────────

def _spans_for(text: Text) -> dict[str, list[str]]:
    """提取各行内容 → 对应的 style 字符串列表。"""
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
    """_render_diff 必须返回 rich.text.Text 实例,不得返回 Syntax 对象。"""
    from argos.tui.widgets.diff_view import _render_diff
    result = _render_diff(sample_diff)
    assert isinstance(result, Text), (
        f"_render_diff 返回 {type(result).__name__},应为 rich.text.Text"
    )


def test_added_line_uses_pass_token(sample_diff: str) -> None:
    """'+' 开头行必须用 $pass (#9ECE6A) 着色。"""
    from argos.tui.widgets.diff_view import _render_diff
    result = _render_diff(sample_diff)
    plain = result.plain
    # 找到 '+added line' 的位置,确认对应 span 的 style 是 _PASS
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
    """-' 开头行必须用 $fail (#F7768E) 着色。"""
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
    """'@' 开头行必须用 $ink-dim (#7E869C) 着色。"""
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
    """context 行(空格开头)必须用 $ink (#C8CCDA) 着色。"""
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
    """[LOW] added 行颜色不得是 monokai #A6E22E(与 function-name 撞色)。"""
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
    """[LOW] removed 行颜色不得是 monokai #FF4689。"""
    from argos.tui.widgets.diff_view import _render_diff
    result = _render_diff(sample_diff)
    plain = result.plain
    for span in result._spans:
        fragment = plain[span.start:span.end]
        if fragment.startswith("-") and "---" not in fragment:
            assert str(span.style).upper() != _MONOKAI_RED, (
                f"removed 行 style={span.style!r} 仍是 monokai #FF4689,违反铁律"
            )


# ── 4. [API] DiffView 公开构造函数签名兼容 ─────────────────────────────────

def test_diff_view_constructor_signature() -> None:
    """DiffView.__init__ 公开签名不得改变(path/added/removed/unified 全 keyword-only)。"""
    from argos.tui.widgets.diff_view import DiffView
    sig = inspect.signature(DiffView.__init__)
    params = list(sig.parameters.keys())
    for name in ("path", "added", "removed", "unified"):
        assert name in params, f"DiffView.__init__ 缺少参数 {name!r}"
    # 确认为 keyword-only(原 def __init__(self, *, path, ...))
    for name in ("path", "added", "removed", "unified"):
        p = sig.parameters[name]
        assert p.kind == inspect.Parameter.KEYWORD_ONLY, (
            f"参数 {name!r} 应为 keyword-only,当前为 {p.kind}"
        )


def test_diff_view_instantiation() -> None:
    """DiffView 可正常实例化,公开属性均正确赋值。"""
    from argos.tui.widgets.diff_view import DiffView
    dv = DiffView(path="argos/replay.py", added=3, removed=1, unified="+new\n-old\n")
    assert dv.path == "argos/replay.py"
    assert dv.added == 3
    assert dv.removed == 1
    assert dv.unified == "+new\n-old\n"
    assert dv._unified == "+new\n-old\n"


def test_diff_view_border_title_format() -> None:
    """border_title 格式必须是 'Edit · {path}'(v3:去掉 ⏺ 前缀)。"""
    from argos.tui.widgets.diff_view import DiffView
    dv = DiffView(path="foo/bar.py", added=2, removed=0, unified="")
    assert dv.border_title == "Edit · foo/bar.py", (
        f"border_title={dv.border_title!r},应为 'Edit · foo/bar.py'"
    )


def test_diff_view_border_subtitle_uses_unicode_minus() -> None:
    """border_subtitle 减号必须用 U+2212(−),不得用 ASCII '-'(v3 铁律)。"""
    from argos.tui.widgets.diff_view import DiffView
    dv = DiffView(path="x.py", added=5, removed=2, unified="")
    subtitle = dv.border_subtitle
    assert "−" in subtitle, (
        f"border_subtitle={subtitle!r} 缺少 U+2212 减号 '−'"
    )
    assert subtitle == "+5 −2", (
        f"border_subtitle={subtitle!r},应为 '+5 −2'"
    )
    # 确认不是 ASCII 连字符充当减号
    assert "-2" not in subtitle, (
        f"border_subtitle={subtitle!r} 仍用 ASCII '-' 而非 U+2212 '−'"
    )
