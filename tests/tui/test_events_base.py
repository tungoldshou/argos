"""Internal documentation."""
from __future__ import annotations

import ast
import inspect
import re
from dataclasses import dataclass

import pytest

from argos.tui import events as tui_events
from argos.tui.events import (
    Event, EventBus, deserialize_event, event_kind, serialize_event,
)


def test_only_one_eventbus_class_in_whole_argos():
    """Internal documentation."""
    import os
    import argos

    root = os.path.dirname(argos.__file__)
    found: list[tuple[str, int, str]] = []
    for dirpath, _dirs, files in os.walk(root):
        if "__pycache__" in dirpath or "/tests" in dirpath:
            continue
        for fn in files:
            if not fn.endswith(".py"):
                continue
            p = os.path.join(dirpath, fn)
            try:
                src = open(p, encoding="utf-8").read()
            except (OSError, UnicodeDecodeError):
                continue
            try:
                tree = ast.parse(src, filename=p)
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef) and node.name == "EventBus":
                    found.append((p, node.lineno, node.name))
    assert len(found) == 1, f"期望 1 个 EventBus,实得 {len(found)}:{found}"
    assert found[0][0].endswith("/protocol/events.py"), (
        f"EventBus 必须在 protocol/events.py,实得 {found[0][0]}"
    )


def test_eventbus_is_in_tui_events_module():
    """Internal documentation."""
    assert hasattr(tui_events, "EventBus")
    assert inspect.isclass(EventBus)
    bus = EventBus()
    assert hasattr(bus, "emit")
    assert hasattr(bus, "close")
    assert hasattr(bus, "__aiter__")


def _all_event_classes_in(module):
    """Internal documentation."""
    import dataclasses as _dc
    out = []
    for name, obj in inspect.getmembers(module, inspect.isclass):
        if obj is EventBus:
            continue
        if _dc.is_dataclass(obj):
            out.append((name, obj))
    return out


@pytest.mark.parametrize("module_path,module_name", [
    ("argos.permissions.events", "permissions"),
    ("argos.daemon.events", "daemon"),
    ("argos.hooks.events", "hooks"),
    ("argos.lsp.events", "lsp"),
    ("argos.skills_runtime.events", "skills_runtime"),
])
def test_all_domain_event_classes_have_kind_attribute(module_path, module_name):
    """Internal documentation."""
    import importlib
    mod = importlib.import_module(module_path)
    classes = _all_event_classes_in(mod)
    assert classes, f"{module_path} 应至少含 1 个事件 dataclass"
    for name, cls in classes:
        assert hasattr(cls, "kind"), f"{module_name}.events.{name} 缺 `kind` 类属性"
        kind = getattr(cls, "kind")
        assert isinstance(kind, str) and kind, f"{module_name}.events.{name}.kind 必须是非空 str"


@pytest.mark.parametrize("module_path", [
    "argos.permissions.events",
    "argos.daemon.events",
    "argos.hooks.events",
    "argos.lsp.events",
    "argos.skills_runtime.events",
])
def test_event_kind_is_snake_case_version_of_class_name(module_path):
    """Internal documentation."""
    import importlib
    mod = importlib.import_module(module_path)
    for name, cls in _all_event_classes_in(mod):
        kind = getattr(cls, "kind")
        snake = re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()
        assert kind == snake, (
            f"{module_path}.{name}.kind={kind!r} 应等于 snake_case 类名 {snake!r}"
        )


def _make_placeholder(cls) -> object:
    """Internal documentation."""
    import dataclasses as _dc
    kwargs = {}
    for f in _dc.fields(cls):
        if f.default is not _dc.MISSING or f.default_factory is not _dc.MISSING:
            continue
        t = f.type
        if t is str or t == "str":
            kwargs[f.name] = ""
        elif t is int or t == "int":
            kwargs[f.name] = 0
        elif t is float or t == "float":
            kwargs[f.name] = 0.0
        elif t is bool or t == "bool":
            kwargs[f.name] = False
        elif t is dict or t == "dict":
            kwargs[f.name] = {}
        elif t is tuple or t == "tuple":
            kwargs[f.name] = ()
        elif t is list or t == "list":
            kwargs[f.name] = []
        else:
            kwargs[f.name] = None
    return cls(**kwargs)


@pytest.mark.parametrize("module_path", [
    "argos.permissions.events",
    "argos.daemon.events",
    "argos.hooks.events",
    "argos.lsp.events",
    "argos.skills_runtime.events",
])
def test_serialize_event_includes_kind_for_all_domain_events(module_path):
    """Internal documentation."""
    import importlib
    import json as _json

    mod = importlib.import_module(module_path)
    classes = _all_event_classes_in(mod)
    assert classes
    for name, cls in classes:
        ev = _make_placeholder(cls)
        blob = serialize_event(ev)
        obj = _json.loads(blob)
        assert "kind" in obj, f"{module_path}.{name} serialize 后缺 `kind`"
        assert obj["kind"] == getattr(cls, "kind")


@pytest.mark.parametrize("module_path", [
    "argos.permissions.events",
    "argos.daemon.events",
    "argos.hooks.events",
    "argos.lsp.events",
    "argos.skills_runtime.events",
])
def test_no_domain_event_module_defines_local_eventbus(module_path):
    """Internal documentation."""
    import importlib
    mod = importlib.import_module(module_path)
    assert not hasattr(mod, "EventBus"), (
        f"{module_path} 不应重新定义 EventBus(应复用 tui.events.EventBus)"
    )