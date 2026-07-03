"""Internal documentation."""
from __future__ import annotations

from argos.sandbox._sandbox_child import (
    _PREINJECT_MODULES,
    _resolve_authorized_imports,
)


def test_preinject_modules_all_importable():
    import importlib

    for name in _PREINJECT_MODULES:
        assert importlib.import_module(name) is not None


def test_required_imports_include_posixpath():
    out = _resolve_authorized_imports(None)
    assert "posixpath" in out
    assert "os" in out and "sys" in out and "pathlib" in out


def test_host_authorized_list_is_augmented_not_replaced():
    out = _resolve_authorized_imports(["requests"])
    assert "requests" in out
    assert "posixpath" in out


def test_no_duplicates_when_already_present():
    out = _resolve_authorized_imports(["os", "posixpath", "sys", "pathlib"])
    assert out.count("posixpath") == 1
    assert out.count("os") == 1


def test_os_path_executes_under_resolved_imports():
    """Internal documentation."""
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
