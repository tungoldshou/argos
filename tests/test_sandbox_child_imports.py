"""沙箱白名单回归:os.path 等无副作用 stdlib 子模块不应被 smolagents AST 层误伤。

根因:smolagents LocalPythonExecutor 按模块真实 __name__ 做 authorized_imports 检查。
os.path 在 darwin/Linux 上其实是 posixpath 模块 —— 白名单只有 "os" 不够(也不是 "os.*"/
"os.path",实测只有真模块名 "posixpath" 命中),缺它 agent 一调 os.path.expanduser 就抛
InterpreterError: Forbidden access to module: posixpath。
"""
from __future__ import annotations

from argos.sandbox._sandbox_child import (
    _PREINJECT_MODULES,
    _resolve_authorized_imports,
)


def test_preinject_modules_all_importable():
    import importlib

    # 预注入清单里每个模块都必须真能 import(否则 child init 直接崩)。
    for name in _PREINJECT_MODULES:
        assert importlib.import_module(name) is not None


def test_required_imports_include_posixpath():
    out = _resolve_authorized_imports(None)
    # posixpath 是修复的核心 —— os.path 的真实模块名。
    assert "posixpath" in out
    assert "os" in out and "sys" in out and "pathlib" in out


def test_host_authorized_list_is_augmented_not_replaced():
    out = _resolve_authorized_imports(["requests"])
    assert "requests" in out          # host 自定义保留
    assert "posixpath" in out         # 必备项仍补上


def test_no_duplicates_when_already_present():
    out = _resolve_authorized_imports(["os", "posixpath", "sys", "pathlib"])
    assert out.count("posixpath") == 1
    assert out.count("os") == 1


def test_os_path_executes_under_resolved_imports():
    """端到端证据:用 child 解析出的白名单跑真 smolagents,os.path.* 不再 forbidden。"""
    import os
    import pathlib
    import sys

    from smolagents.local_python_executor import LocalPythonExecutor

    ex = LocalPythonExecutor(
        additional_authorized_imports=_resolve_authorized_imports(None)
    )
    ex.send_tools({})
    ex.state["os"] = os
    ex.state["sys"] = sys
    ex.state["pathlib"] = pathlib
    result = ex(
        'p = os.path.expanduser("~/projects/x")\n'
        'print(os.path.join(p, "js"))'
    )
    assert result.logs.strip().endswith("/projects/x/js")
