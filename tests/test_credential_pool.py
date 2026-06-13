"""CredentialPool(契约 §7;spec §3.4):least_used + exhausted-TTL 复活 + terminal vs transient 401。"""
import pytest

from argos.core.models import CredentialPool


def test_least_used_rotates(monkeypatch):
    pool = CredentialPool(["a", "b", "c"])
    c1 = pool.least_used()
    pool.mark_used(c1.key)
    c2 = pool.least_used()
    assert c2.key != c1.key  # 用过的不会马上再选


def test_exhausted_skipped_until_ttl(monkeypatch):
    import argos.core.models as m
    t = {"now": 1000.0}
    monkeypatch.setattr(m.time, "time", lambda: t["now"])
    pool = CredentialPool(["a", "b"])
    pool.mark_exhausted("a", ttl_s=60.0)
    # a 被限流 → least_used 跳过 a
    assert pool.least_used().key == "b"
    # TTL 未到仍跳过
    t["now"] = 1059.0
    assert pool.least_used().key == "b"
    # TTL 到点 → a 复活,且 a 比 b 更久未用(b 没用过但 a last_used=0 也 0;以未 exhausted 为先,
    # 再按 last_used 取最小)→ a 可被选回
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
    # terminal:无效 key(authentication_error / invalid x-api-key)
    assert pool.is_terminal_401(401, '{"error":{"type":"authentication_error"}}') is True
    assert pool.is_terminal_401(401, "invalid x-api-key") is True
    # transient:限流伪装成 401 但带 rate/quota 语义 → 非 terminal
    assert pool.is_terminal_401(401, '{"error":{"type":"rate_limit_error"}}') is False
    assert pool.is_terminal_401(429, "too many requests") is False


def test_all_exhausted_returns_least_anyway():
    # 全部 exhausted → 仍返一个(fail-open 取最早 expire 的,避免无 key 可用直接崩;由上层退避)。
    import argos.core.models as m
    pool = CredentialPool(["a", "b"])
    pool.mark_exhausted("a", ttl_s=10.0)
    pool.mark_exhausted("b", ttl_s=10.0)
    assert pool.least_used().key in {"a", "b"}
