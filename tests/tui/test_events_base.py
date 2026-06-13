"""事件一致性验收(任务:全局 EventBus 唯一,事件基类/约定一致)。

约束:
- protocol/events.EventBus 是【全局唯一】总线(契约 §1;v6 P0 由 tui/ 搬入协议层)
- 5 个领域 events.py(permissions/daemon/hooks/lsp/skills_runtime)只定义事件 dataclass,
  不重复实现 EventBus
- 所有事件 dataclass 有 `kind` 类属性(类名 snake_case,用于 EventBus 路由与 replay)
"""
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


# ── 1. 全局只有一个 EventBus 实现 ─────────────────────
def test_only_one_eventbus_class_in_whole_argos():
    """扫 argos 子包所有 .py 模块 → 只应找到 1 个 `class EventBus` 定义。"""
    import os
    import argos

    root = os.path.dirname(argos.__file__)
    found: list[tuple[str, int, str]] = []
    for dirpath, _dirs, files in os.walk(root):
        # 跳过缓存与测试
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
    # 全局应该只有 protocol.events.EventBus 一个(v6 P0:总线是内核基础设施,搬入协议层)
    assert len(found) == 1, f"期望 1 个 EventBus,实得 {len(found)}:{found}"
    assert found[0][0].endswith("/protocol/events.py"), (
        f"EventBus 必须在 protocol/events.py,实得 {found[0][0]}"
    )


def test_eventbus_is_in_tui_events_module():
    """EventBus 经 tui.events shim 仍可 import(兼容保证),且是运行时类(可实例化)。"""
    assert hasattr(tui_events, "EventBus")
    assert inspect.isclass(EventBus)
    bus = EventBus()
    assert hasattr(bus, "emit")
    assert hasattr(bus, "close")
    assert hasattr(bus, "__aiter__")


# ── 2. 5 个领域事件 dataclass 都有 `kind` 类属性 ──────────
def _all_event_classes_in(module):
    """从模块里收集所有 dataclass(非 EventBus 本体)。

    注意:用 `dataclasses.is_dataclass()` 检测,不要用 `dataclass(obj) is obj` —
    后者会把 obj 当类型去构造,遇 typing.Any 之类会抛 TypeError。
    """
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
    """5 个领域 events.py 中每个事件 dataclass 都有 `kind` 类属性(沿用 EventBus 路由约定)。"""
    import importlib
    mod = importlib.import_module(module_path)
    classes = _all_event_classes_in(mod)
    assert classes, f"{module_path} 应至少含 1 个事件 dataclass"
    for name, cls in classes:
        assert hasattr(cls, "kind"), f"{module_name}.events.{name} 缺 `kind` 类属性"
        kind = getattr(cls, "kind")
        assert isinstance(kind, str) and kind, f"{module_name}.events.{name}.kind 必须是非空 str"


# ── 3. `kind` 必须是 snake_case 类名变体 ─────────────────
@pytest.mark.parametrize("module_path", [
    "argos.permissions.events",
    "argos.daemon.events",
    "argos.hooks.events",
    "argos.lsp.events",
    "argos.skills_runtime.events",
])
def test_event_kind_is_snake_case_version_of_class_name(module_path):
    """`kind` 字段约定 = 类名的 snake_case(EventBus 路由依赖)。"""
    import importlib
    mod = importlib.import_module(module_path)
    for name, cls in _all_event_classes_in(mod):
        kind = getattr(cls, "kind")
        # 把 ClassName 转 snake_case(简化:大写字母前缀 _ + 小写;首字母小写)
        snake = re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()
        assert kind == snake, (
            f"{module_path}.{name}.kind={kind!r} 应等于 snake_case 类名 {snake!r}"
        )


# ── 4. 领域事件 dataclass 经 serialize_event 写出"kind"字段(路由用) ─────────
def _make_placeholder(cls) -> object:
    """造一个 frozen dataclass 实例(必填字段用 "" / 0 / {} / () 占位)。"""
    import dataclasses as _dc
    kwargs = {}
    for f in _dc.fields(cls):
        if f.default is not _dc.MISSING or f.default_factory is not _dc.MISSING:
            continue  # 已有默认值
        t = f.type
        # 类型占位(避开 Any —— Any 不可实例化)
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
            # 兜底:None(可空字段)
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
    """serialize_event(ev) 必须含 `kind` 字段(路由与 replay 依赖),每个领域事件都行。"""
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


# ── 5. 领域 events.py 不重新定义 EventBus ─────────────
@pytest.mark.parametrize("module_path", [
    "argos.permissions.events",
    "argos.daemon.events",
    "argos.hooks.events",
    "argos.lsp.events",
    "argos.skills_runtime.events",
])
def test_no_domain_event_module_defines_local_eventbus(module_path):
    """5 个领域 events.py 不应有 `class EventBus` 定义(只复用 tui.events.EventBus)。"""
    import importlib
    mod = importlib.import_module(module_path)
    assert not hasattr(mod, "EventBus"), (
        f"{module_path} 不应重新定义 EventBus(应复用 tui.events.EventBus)"
    )