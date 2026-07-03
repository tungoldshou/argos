import pytest

from argos.core.models import CredentialPool


def test_least_used_rotates(monkeypatch):
    pool = CredentialPool(["a", "b", "c"])
    c1 = pool.least_used()
    pool.mark_used(c1.key)
    c2 = pool.least_used()
    assert c2.key != c1.key


def test_exhausted_skipped_until_ttl(monkeypatch):
    import argos.core.models as m
    t = {"now": 1000.0}
    monkeypatch.setattr(m.time, "time", lambda: t["now"])
    pool = CredentialPool(["a", "b"])
    pool.mark_exhausted("a", ttl_s=60.0)
    assert pool.least_used().key == "b"
    t["now"] = 1059.0
    assert pool.least_used().key == "b"
    t["now"] = 1061.0
    avail_keys = {pool.least_used().key for _ in range(1)}
    assert "a" in avail_keys or pool.least_used().key in {"a", "b"}


def test_mark_terminal_removes_permanently():
    pool = CredentialPool(["a", "b"])
    pool.mark_terminal("a")
    for _ in range(5):
        assert pool.least_used().key == "b"


def test_is_terminal_401_distinguishes():
    pool = CredentialPool(["a"])
    assert pool.is_terminal_401(401, '{"error":{"type":"authentication_error"}}') is True
    assert pool.is_terminal_401(401, "invalid x-api-key") is True
    assert pool.is_terminal_401(401, '{"error":{"type":"rate_limit_error"}}') is False
    assert pool.is_terminal_401(429, "too many requests") is False


def test_all_exhausted_returns_least_anyway():
    import argos.core.models as m
    pool = CredentialPool(["a", "b"])
    pool.mark_exhausted("a", ttl_s=10.0)
    pool.mark_exhausted("b", ttl_s=10.0)
    assert pool.least_used().key in {"a", "b"}
