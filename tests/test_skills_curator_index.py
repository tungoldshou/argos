"""#10 T1 Index schema + 本地 cache + refresh CLI 测试。

沿用 #7/#9 风格:RED 写 → 跑挂 → 写 impl → 跑绿。
"""
from __future__ import annotations

import io
import json
import urllib.error
from pathlib import Path

import pytest

from argos.skills_curator.index import (
    BUILTIN_NAMES,
    DEFAULT_INDEX_URL,
    IndexCache,
    IndexEntry,
    IndexFetchError,
    _parse_entry,
    cache_age_days,
    fetch_remote,
    load_cache,
    save_cache,
)


# ── helpers ──────────────────────────────────────────────────────


class _FakeResp(io.BytesIO):
    """最小 urllib 响应,带 .read() / context manager。"""

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()

    def read(self, *a, **k):  # type: ignore[override]
        return super().read(*a, **k)


def _make_entry_dict(**over) -> dict:
    base = {
        "name": "python-lint",
        "version": "0.2.1",
        "author": "tungoldshou",
        "sha256": "a" * 64,
        "description": "lint python",
        "skill_md_url": "https://raw.githubusercontent.com/test/test/main/SKILL.md",
        "compatibility": ">=0.1.0",
        "capabilities": ["read", "execute"],
        "size_bytes": 1234,
    }
    base.update(over)
    return base


# ── parse_entry tests ──────────────────────────────────────────


def test_parse_entry_happy_path():
    e = _parse_entry(_make_entry_dict())
    assert e.name == "python-lint"
    assert e.version == "0.2.1"
    assert e.sha256 == "a" * 64
    assert e.capabilities == ("read", "execute")
    assert e.is_builtin() is False


def test_parse_entry_rejects_invalid_name():
    with pytest.raises(ValueError, match="invalid name"):
        _parse_entry(_make_entry_dict(name="BadName"))


def test_parse_entry_rejects_invalid_version():
    with pytest.raises(ValueError, match="invalid version"):
        _parse_entry(_make_entry_dict(version="v1"))


def test_parse_entry_rejects_bad_sha256():
    with pytest.raises(ValueError, match="invalid sha256"):
        _parse_entry(_make_entry_dict(sha256="not-hex"))


def test_parse_entry_rejects_unknown_capability():
    with pytest.raises(ValueError, match="invalid capability"):
        _parse_entry(_make_entry_dict(capabilities=["read", "evil"]))


def test_index_entry_is_builtin_for_three_names():
    for n in ("verify", "security-review", "simplify"):
        e = _parse_entry(_make_entry_dict(name=n))
        assert e.is_builtin() is True


def test_index_cache_find_returns_match():
    e1 = _parse_entry(_make_entry_dict(name="python-lint"))
    e2 = _parse_entry(_make_entry_dict(name="test-debugger", sha256="b" * 64))
    c = IndexCache(version=1, generated_at=0.0, skills=(e1, e2))
    assert c.find("python-lint") is e1
    assert c.find("test-debugger") is e2
    assert c.find("nope") is None


def test_builtin_names_frozen():
    assert BUILTIN_NAMES == frozenset({"verify", "security-review", "simplify"})


# ── fetch_remote tests ────────────────────────────────────────


def test_fetch_remote_parses_valid_index(monkeypatch):
    payload = {
        "version": 1,
        "generated_at": 1717700000.0,
        "skills": [_make_entry_dict()],
    }
    data = json.dumps(payload).encode("utf-8")

    def fake_urlopen(url, timeout=10.0):
        assert url == DEFAULT_INDEX_URL
        return _FakeResp(data)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    cache = fetch_remote()
    assert len(cache.skills) == 1
    assert cache.skills[0].name == "python-lint"


def test_fetch_remote_unknown_fields_ignored(monkeypatch):
    payload = {
        "version": 1,
        "generated_at": 0.0,
        "skills": [_make_entry_dict(extra_field="ignored")],
    }
    monkeypatch.setattr(
        "urllib.request.urlopen", lambda url, timeout=10.0: _FakeResp(json.dumps(payload).encode("utf-8"))
    )
    cache = fetch_remote()
    assert len(cache.skills) == 1


def test_fetch_remote_corrupt_line_skipped(monkeypatch):
    """坏行(无 name)→ 跳过,好行保留(D4 宽松)."""
    payload = {
        "version": 1,
        "generated_at": 0.0,
        "skills": [
            {"version": "0.1.0", "sha256": "c" * 64},  # 无 name → 跳
            _make_entry_dict(name="good-one"),
        ],
    }
    monkeypatch.setattr(
        "urllib.request.urlopen", lambda url, timeout=10.0: _FakeResp(json.dumps(payload).encode("utf-8"))
    )
    cache = fetch_remote()
    assert len(cache.skills) == 1
    assert cache.skills[0].name == "good-one"


def test_fetch_remote_404_raises(monkeypatch):
    def fake_urlopen(url, timeout=10.0):
        raise urllib.error.URLError("404")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    with pytest.raises(IndexFetchError):
        fetch_remote()


def test_fetch_remote_bad_json_raises(monkeypatch):
    monkeypatch.setattr(
        "urllib.request.urlopen", lambda url, timeout=10.0: _FakeResp(b"not json {")
    )
    with pytest.raises(IndexFetchError):
        fetch_remote()


def test_fetch_remote_timeout_raises(monkeypatch):
    def fake_urlopen(url, timeout=10.0):
        raise TimeoutError("slow")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    with pytest.raises(IndexFetchError):
        fetch_remote()


# ── save_cache / load_cache tests ──────────────────────────────


def test_save_cache_atomic_write(tmp_path, monkeypatch):
    """tmp file rename,不是 partial write."""
    monkeypatch.setattr(
        "argos.skills_curator.index._skills_root", lambda: tmp_path
    )
    e = _parse_entry(_make_entry_dict())
    cache = IndexCache(version=1, generated_at=1717700000.0, skills=(e,))
    target = save_cache(cache)
    assert target.exists()
    assert (tmp_path / "index.json.tmp").exists() is False


def test_save_cache_creates_skills_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "argos.skills_curator.index._skills_root", lambda: tmp_path / "deep" / "skills"
    )
    e = _parse_entry(_make_entry_dict())
    cache = IndexCache(version=1, generated_at=0.0, skills=(e,))
    target = save_cache(cache)
    assert target.exists()


def test_load_cache_returns_none_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "argos.skills_curator.index._skills_root", lambda: tmp_path
    )
    assert load_cache() is None


def test_load_cache_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "argos.skills_curator.index._skills_root", lambda: tmp_path
    )
    e = _parse_entry(_make_entry_dict())
    cache = IndexCache(version=1, generated_at=1717700000.0, skills=(e,))
    save_cache(cache)
    loaded = load_cache()
    assert loaded is not None
    assert loaded.version == 1
    assert len(loaded.skills) == 1
    assert loaded.skills[0].name == "python-lint"


def test_load_cache_corrupt_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "argos.skills_curator.index._skills_root", lambda: tmp_path
    )
    (tmp_path / "index.json").write_text("not json", encoding="utf-8")
    assert load_cache() is None


def test_cache_age_days_none_for_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "argos.skills_curator.index._skills_root", lambda: tmp_path
    )
    assert cache_age_days() is None


def test_cache_age_days_returns_positive(tmp_path, monkeypatch):
    import time
    monkeypatch.setattr(
        "argos.skills_curator.index._skills_root", lambda: tmp_path
    )
    e = _parse_entry(_make_entry_dict())
    save_cache(IndexCache(version=1, generated_at=0.0, skills=(e,)))
    # 1 秒后再读
    time.sleep(0.01)
    age = cache_age_days()
    assert age is not None
    assert age >= 0.0
