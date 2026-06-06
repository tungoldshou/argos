"""#9 T2: loader + recency × confidence ranking + type 优先级 + threshold 过滤。"""
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


# ── load: 多 tier 合并 + 过滤 ────────────────────────────────────────────────
def test_load_returns_recent_first(mem_root):
    p = mem_auto._user_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    older = _entry(key="old", ts=100.0, last_used_at=100.0)
    newer = _entry(key="new", ts=200.0, last_used_at=200.0)
    mem_auto._append_jsonl(p, older)
    mem_auto._append_jsonl(p, newer)
    out = mem_auto.load(scope="user", limit=10)
    assert [e.key for e in out] == ["new", "old"]


def test_confidence_below_threshold_excluded(mem_root):
    p = mem_auto._user_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    good = _entry(key="good", confidence=0.5)
    bad = _entry(key="bad", confidence=0.2)  # 低于 0.3 阈值
    mem_auto._append_jsonl(p, good)
    mem_auto._append_jsonl(p, bad)
    out = mem_auto.load(scope="user", limit=10)
    keys = {e.key for e in out}
    assert "good" in keys
    assert "bad" not in keys


def test_failure_type_outranks_fact(mem_root):
    p = mem_auto._user_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    fact = _entry(key="fact", type="fact", confidence=0.9, last_used_at=time.time())
    fail = _entry(key="fail", type="failure", confidence=0.5, last_used_at=time.time())
    mem_auto._append_jsonl(p, fact)
    mem_auto._append_jsonl(p, fail)
    out = mem_auto.load(scope="user", limit=10)
    # failure type priority(5) > fact(1),即便 conf 低
    assert out[0].key == "fail"


def test_load_filters_by_scope(mem_root):
    user_p = mem_auto._user_path()
    pid = mem_auto.project_id_for(mem_root.parent)  # = cwd when called with parent of memory
    proj_p = mem_auto._project_path(pid)
    user_p.parent.mkdir(parents=True, exist_ok=True)
    proj_p.parent.mkdir(parents=True, exist_ok=True)
    mem_auto._append_jsonl(user_p, _entry(key="u", scope="user"))
    mem_auto._append_jsonl(proj_p, _entry(key="p", scope="project", project_id=pid))
    user_only = mem_auto.load(scope="user", limit=10)
    proj_only = mem_auto.load(scope="project", project_id=pid, limit=10)
    all_tiers = mem_auto.load(limit=10, cwd=mem_root.parent)
    assert {e.key for e in user_only} == {"u"}
    assert {e.key for e in proj_only} == {"p"}
    assert {e.key for e in all_tiers} == {"u", "p"}


def test_limit_truncates(mem_root):
    p = mem_auto._user_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    for i in range(10):
        mem_auto._append_jsonl(p, _entry(key=f"k{i}"))
    out = mem_auto.load(scope="user", limit=3)
    assert len(out) == 3


# ── score / recency ─────────────────────────────────────────────────────────
def test_score_decays_with_age(monkeypatch, mem_root):
    """100 天前的条目 score < 今天的(同 conf)。"""
    p = mem_auto._user_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    now = time.time()
    old = _entry(key="old", confidence=0.9, ts=now - 86400 * 100, last_used_at=now - 86400 * 100)
    fresh = _entry(key="fresh", confidence=0.9, ts=now, last_used_at=now)
    assert mem_auto._score(old) < mem_auto._score(fresh)


def test_use_count_boost_confidence(monkeypatch, mem_root):
    """touch 后 confidence + 0.02,use_count + 1,last_used_at 更新。"""
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


# ── dedup: 24h 内同 (scope,key,value) 重复检测 ──────────────────────────────
def test_dedup_returns_true_within_24h(mem_root):
    p = mem_auto._user_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    e = _entry(key="k", value="v", ts=time.time())
    mem_auto._append_jsonl(p, e)
    # 同一 (scope,key,value) 立即再查 → 应命中
    assert mem_auto._dedup("user", "k", "v", path=p) is True


def test_dedup_returns_false_when_value_changed(mem_root):
    p = mem_auto._user_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    e = _entry(key="k", value="v1")
    mem_auto._append_jsonl(p, e)
    assert mem_auto._dedup("user", "k", "v2", path=p) is False


def test_dedup_returns_false_when_old(mem_root):
    """> 24h 的同 key+value 不算 dup(过完窗口期可重写)。"""
    p = mem_auto._user_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    e = _entry(key="k", value="v", ts=time.time() - 86400 * 2)  # 2 天前
    mem_auto._append_jsonl(p, e)
    assert mem_auto._dedup("user", "k", "v", path=p, hours=24) is False
