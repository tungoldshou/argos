"""#9 T7: decay / prune / 容量 cap / session 30 天清理。"""
from __future__ import annotations

import time

import pytest

from argos_agent.memory import auto as mem_auto


@pytest.fixture
def mem_root(monkeypatch, tmp_path):
    root = tmp_path / "memory"
    monkeypatch.setenv("ARGOS_MEMORY_DIR", str(root))
    yield root


def _entry(**overrides) -> mem_auto.MemoryEntry:
    base = dict(
        id=mem_auto._new_id(), type="fact", scope="user", key="k", value="v",
        confidence=0.5, evidence=(), ts=time.time(), last_used_at=time.time(),
        use_count=0,
    )
    base.update(overrides)
    return mem_auto.MemoryEntry(**base)


# ── decay_pass ───────────────────────────────────────────────────────────────
def test_decay_reduces_confidence_for_old_entries(mem_root):
    p = mem_auto._user_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    now = time.time()
    old = _entry(key="old", confidence=0.9, ts=now - 86400 * 100, last_used_at=now - 86400 * 100)
    mem_auto._append_jsonl(p, old)
    n = mem_auto.decay_pass()
    assert n >= 1
    got = mem_auto._read_jsonl(p)[0]
    # 100 天 → 大约 confidence -= 1.0 → ≤ 0
    assert got.confidence < 0.9


def test_decay_does_not_apply_to_recently_used(mem_root):
    p = mem_auto._user_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    now = time.time()
    fresh = _entry(key="fresh", confidence=0.5, ts=now, last_used_at=now)
    mem_auto._append_jsonl(p, fresh)
    mem_auto.decay_pass()
    got = mem_auto._read_jsonl(p)[0]
    # last_used_at = now → 不衰减
    assert got.confidence == pytest.approx(0.5, abs=1e-9)


# ── touch ────────────────────────────────────────────────────────────────────
def test_touch_boosts_confidence_and_increments_use_count(mem_root):
    p = mem_auto._user_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    e = _entry(key="k", confidence=0.5, use_count=0, last_used_at=0.0)
    mem_auto._append_jsonl(p, e)
    before = mem_auto._read_jsonl(p)[0]
    time.sleep(0.01)
    mem_auto.touch(before)
    after = mem_auto._read_jsonl(p)[0]
    assert after.use_count == 1
    assert after.confidence == pytest.approx(0.52, abs=1e-9)
    assert after.last_used_at > before.last_used_at


# ── prune ────────────────────────────────────────────────────────────────────
def test_prune_removes_zero_confidence(mem_root):
    p = mem_auto._user_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    e = _entry(key="k", confidence=0.5)
    mem_auto._append_jsonl(p, e)
    # 软删
    mem_auto.forget("k")
    n = mem_auto.prune()
    assert n >= 1
    got = mem_auto._read_jsonl(p)
    # 0 confidence 的被物理删
    assert all(g.confidence > 0 for g in got)


def test_prune_idempotent(mem_root):
    n1 = mem_auto.prune()
    n2 = mem_auto.prune()
    assert n1 == 0 and n2 == 0


# ── cap 强制 ────────────────────────────────────────────────────────────────
def test_cap_enforced_on_write(mem_root, tmp_path):
    """写入超 cap → 触发 prune,把最旧的删到 < cap。"""
    pid = mem_auto.project_id_for(tmp_path)
    p = mem_auto._project_path(pid)
    p.parent.mkdir(parents=True, exist_ok=True)
    # cap 设小(1KB)便于测
    cap = 1024
    # 写很多大条目
    for i in range(20):
        big = _entry(
            key=f"k{i}", scope="project", project_id=pid,
            value="x" * 200, confidence=0.9, type="fact",
        )
        mem_auto._append_jsonl(p, big)
        mem_auto._enforce_cap(p, max_bytes=cap)
    # 文件应 < cap
    assert p.stat().st_size < cap + 500  # 容差


# ── session 30 天清理 ───────────────────────────────────────────────────────
def test_session_tier_purged_after_30_days(mem_root, tmp_path):
    p = mem_auto._session_path("s-old")
    p.parent.mkdir(parents=True, exist_ok=True)
    e = _entry(
        key="k", scope="session", session_id="s-old",
        ts=time.time() - 86400 * 31, last_used_at=time.time() - 86400 * 31,
    )
    mem_auto._append_jsonl(p, e)
    n = mem_auto.purge_old_sessions(max_age_days=30)
    assert n >= 1
    assert not p.exists() or len(mem_auto._read_jsonl(p)) == 0
