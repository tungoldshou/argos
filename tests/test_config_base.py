from __future__ import annotations

import json
from pathlib import Path

import pytest

from argos import config_base


def test_read_json_file_returns_parsed_dict(tmp_path):
    p = tmp_path / "cfg.json"
    p.write_text(json.dumps({"version": 1, "x": 1}), encoding="utf-8")
    data = config_base.read_json_file(p, ErrorCls=ValueError)
    assert data == {"version": 1, "x": 1}


def test_read_json_file_missing_returns_none(tmp_path):
    p = tmp_path / "nope.json"
    assert config_base.read_json_file(p, ErrorCls=ValueError) is None


def test_read_json_file_invalid_json_raises_error_cls(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{not json", encoding="utf-8")

    class _TestError(Exception):
        pass

    with pytest.raises(_TestError, match="不是合法 JSON"):
        config_base.read_json_file(p, ErrorCls=_TestError)


def test_read_json_file_top_level_not_dict_raises(tmp_path):
    p = tmp_path / "list.json"
    p.write_text("[1, 2, 3]", encoding="utf-8")

    class _TestError(Exception):
        pass

    with pytest.raises(_TestError, match="顶层必须是 object"):
        config_base.read_json_file(p, ErrorCls=_TestError)


def test_cached_singleton_loads_on_first_call():
    calls: list[int] = []

    def getter() -> dict:
        calls.append(1)
        return {"v": 1}

    cache: dict | None = None
    def get1() -> dict:
        nonlocal cache
        cache = config_base.cached_singleton(getter, ErrorCls=ValueError, _state=cache)
        return cache

    get1()
    get1()
    get1()
    assert len(calls) == 1
    assert cache == {"v": 1}


def test_cached_singleton_propagates_getter_errors():
    calls: list[int] = []

    class _TestError(Exception):
        pass

    def getter() -> dict:
        calls.append(1)
        raise _TestError("bad")

    cache: dict | None = None
    def get1() -> dict:
        nonlocal cache
        try:
            cache = config_base.cached_singleton(getter, ErrorCls=_TestError, _state=cache)
        except _TestError:
            return None  # type: ignore[return-value]
        return cache

    get1()
    get1()
    assert len(calls) == 2, "getter 失败时不应缓存失败结果"


def test_reload_singleton_swallows_errors_keeps_old():
    class _TestError(Exception):
        pass

    new_calls: list[int] = []
    def new_getter() -> dict:
        new_calls.append(1)
        raise _TestError("reload failed")

    cache = {"old": True}
    with pytest.raises(_TestError, match="reload failed"):
        config_base.reload_singleton(new_getter, cache, ErrorCls=_TestError)
    assert cache == {"old": True}
    assert new_calls == [1]


def test_reload_singleton_replaces_on_success():
    new = {"new": 1}
    def getter() -> dict:
        return new

    cache = {"old": True}
    out = config_base.reload_singleton(getter, cache, ErrorCls=ValueError)
    assert out == {"new": 1}


def test_read_json_file_requires_error_cls(tmp_path):
    p = tmp_path / "x.json"
    p.write_text("not json", encoding="utf-8")
    with pytest.raises(TypeError):
        config_base.read_json_file(p)  # type: ignore[call-arg]
