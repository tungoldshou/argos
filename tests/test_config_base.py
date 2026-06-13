"""config_base 助手验收(任务:lsp/hooks/permissions 的 dataclass+JSON+单例样板抽出)。

约束:
- 对外行为完全一致(校验报错信息、单例语义)
- 不合并各模块的 schema
- 行为与重构前一致
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from argos import config_base


# ── read_json_file 验收 ─────────────────────────────
def test_read_json_file_returns_parsed_dict(tmp_path):
    """正常 JSON → 返 dict。"""
    p = tmp_path / "cfg.json"
    p.write_text(json.dumps({"version": 1, "x": 1}), encoding="utf-8")
    data = config_base.read_json_file(p, ErrorCls=ValueError)
    assert data == {"version": 1, "x": 1}


def test_read_json_file_missing_returns_none(tmp_path):
    """FileNotFoundError → 返 None(让 caller 决定返 empty/raise,不在助手层拍板)。"""
    p = tmp_path / "nope.json"
    assert config_base.read_json_file(p, ErrorCls=ValueError) is None


def test_read_json_file_invalid_json_raises_error_cls(tmp_path):
    """JSON 坏 → 抛 ErrorCls(<path> 不是合法 JSON: <inner>),消息格式与重构前一致。"""
    p = tmp_path / "bad.json"
    p.write_text("{not json", encoding="utf-8")

    class _TestError(Exception):
        pass

    with pytest.raises(_TestError, match="不是合法 JSON"):
        config_base.read_json_file(p, ErrorCls=_TestError)


def test_read_json_file_top_level_not_dict_raises(tmp_path):
    """顶层非 dict → 抛 ErrorCls(原 hooks/permissions 行为:json 顶层必须 object)。"""
    p = tmp_path / "list.json"
    p.write_text("[1, 2, 3]", encoding="utf-8")

    class _TestError(Exception):
        pass

    with pytest.raises(_TestError, match="顶层必须是 object"):
        config_base.read_json_file(p, ErrorCls=_TestError)


# ── cached_singleton 验收 ──────────────────────────
def test_cached_singleton_loads_on_first_call():
    """首次调用 → 调 getter 拿配置;后续调用 → 直接返缓存(不再调 getter)。"""
    calls: list[int] = []

    def getter() -> dict:
        calls.append(1)
        return {"v": 1}

    # 模拟"模块级 _config"模式
    cache: dict | None = None
    def get1() -> dict:
        nonlocal cache
        cache = config_base.cached_singleton(getter, ErrorCls=ValueError, _state=cache)
        return cache

    get1()
    get1()
    get1()
    # getter 只被调 1 次(后续都走缓存)
    assert len(calls) == 1
    assert cache == {"v": 1}


def test_cached_singleton_propagates_getter_errors():
    """getter 抛 ErrorCls 子类 → 不缓存,后续调用会再试(spec D11:坏配置不静默 fallback)。"""
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

    get1()  # 抛
    get1()  # 缓存没被设置(仍是 None)→ 再次调 getter
    assert len(calls) == 2, "getter 失败时不应缓存失败结果"


def test_reload_singleton_swallows_errors_keeps_old():
    """reload 失败 → 保旧 + 抛(spec §3 / D11 行为:reload 坏配置不静默崩)。"""
    class _TestError(Exception):
        pass

    new_calls: list[int] = []
    def new_getter() -> dict:
        new_calls.append(1)
        raise _TestError("reload failed")

    cache = {"old": True}
    with pytest.raises(_TestError, match="reload failed"):
        config_base.reload_singleton(new_getter, cache, ErrorCls=_TestError)
    # 旧 cache 未变
    assert cache == {"old": True}
    assert new_calls == [1]


def test_reload_singleton_replaces_on_success():
    """reload 成功 → 返新配置(调用方负责写回 _state 模块变量)。"""
    new = {"new": 1}
    def getter() -> dict:
        return new

    cache = {"old": True}  # 模块级 _state 的"占位",reload 返新后 caller 写回
    out = config_base.reload_singleton(getter, cache, ErrorCls=ValueError)
    # 返新(调用方拿到后赋给 _state)
    assert out == {"new": 1}


# ── ErrorCls 在 read_json_file 必须显式传(防 caller 误用) ──
def test_read_json_file_requires_error_cls(tmp_path):
    """read_json_file 必须传 ErrorCls(显式约定,防止"不知道抛啥"的歧义)。"""
    p = tmp_path / "x.json"
    p.write_text("not json", encoding="utf-8")
    with pytest.raises(TypeError):
        config_base.read_json_file(p)  # type: ignore[call-arg]
