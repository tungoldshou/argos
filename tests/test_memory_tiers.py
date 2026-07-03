from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from argos.memory import auto as mem_auto


@pytest.fixture
def mem_root(monkeypatch, tmp_path):
    root = tmp_path / "memory"
    monkeypatch.setenv("ARGOS_MEMORY_DIR", str(root))
    if hasattr(mem_auto, "_PROJECT_ID_CACHE"):
        mem_auto._PROJECT_ID_CACHE.clear()
    return root


def test_user_tier_path_resolves_under_argos_home(monkeypatch, tmp_path):
    monkeypatch.setenv("ARGOS_MEMORY_DIR", str(tmp_path / "memory"))
    p = mem_auto._user_path()
    assert p.name == "user.jsonl"
    assert p.parent == tmp_path / "memory"


def test_memory_root_defaults_to_argos_config_dir(monkeypatch, tmp_path):
    monkeypatch.delenv("ARGOS_MEMORY_DIR", raising=False)
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(tmp_path / "cfg"))

    assert mem_auto._root() == tmp_path / "cfg" / "memory"


def test_memory_root_expands_explicit_env_override(monkeypatch, tmp_path):
    fake_home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("ARGOS_MEMORY_DIR", "~/argos-memory")

    assert mem_auto._root() == fake_home / "argos-memory"


def test_global_instruction_home_defaults_to_argos_config_dir(monkeypatch, tmp_path):
    monkeypatch.delenv("ARGOS_HOME", raising=False)
    monkeypatch.setenv("ARGOS_CONFIG_DIR", str(tmp_path / "cfg"))

    assert mem_auto._ARGOS_HOME() == tmp_path / "cfg"


def test_global_instruction_home_expands_explicit_env_override(monkeypatch, tmp_path):
    fake_home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("ARGOS_HOME", "~/argos-home")

    assert mem_auto._ARGOS_HOME() == fake_home / "argos-home"


def test_project_tier_path_includes_hash(monkeypatch, tmp_path):
    monkeypatch.setenv("ARGOS_MEMORY_DIR", str(tmp_path / "memory"))
    pid = "abc123hash"
    p = mem_auto._project_path(pid)
    assert p.name == "abc123hash.jsonl"
    assert p.parent.name == "projects"


def test_skill_tier_path_per_skill(monkeypatch, tmp_path):
    monkeypatch.setenv("ARGOS_MEMORY_DIR", str(tmp_path / "memory"))
    p = mem_auto._skill_path("verify")
    assert p.name == "verify.jsonl"
    assert p.parent.name == "skills"


def test_session_tier_path_per_session(monkeypatch, tmp_path):
    monkeypatch.setenv("ARGOS_MEMORY_DIR", str(tmp_path / "memory"))
    p = mem_auto._session_path("sess-xyz")
    assert p.name == "sess-xyz.jsonl"
    assert p.parent.name == "sessions"


def test_project_id_for_deterministic(monkeypatch, tmp_path):
    monkeypatch.setenv("ARGOS_MEMORY_DIR", str(tmp_path / "memory"))
    a = mem_auto.project_id_for(tmp_path)
    b = mem_auto.project_id_for(tmp_path)
    assert a == b
    assert len(a) == 16


def test_project_id_for_different_paths_differ(monkeypatch, tmp_path):
    monkeypatch.setenv("ARGOS_MEMORY_DIR", str(tmp_path / "memory"))
    a = mem_auto.project_id_for(tmp_path / "a")
    b = mem_auto.project_id_for(tmp_path / "b")
    assert a != b


# ── dataclass ────────────────────────────────────────────────────────────────
def test_memory_entry_is_frozen():
    e = mem_auto.MemoryEntry(
        id="m1", type="preference", scope="user", key="k", value="v",
        confidence=0.9, evidence=("u",), ts=1.0, last_used_at=1.0, use_count=0,
    )
    with pytest.raises((AttributeError, TypeError)):
        e.value = "tampered"  # type: ignore[misc]


def test_memory_entry_default_optional_fields():
    e = mem_auto.MemoryEntry(
        id="m1", type="fact", scope="user", key="k", value="v",
        confidence=0.5, evidence=(), ts=0.0, last_used_at=0.0, use_count=0,
    )
    assert e.skill_name is None
    assert e.project_id is None
    assert e.session_id is None


def test_read_jsonl_missing_file_returns_empty(mem_root):
    assert mem_auto._read_jsonl(mem_root / "nope.jsonl") == []


def test_read_jsonl_skips_corrupt_lines(mem_root):
    p = mem_root / "test.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps({"id": "a", "type": "preference", "scope": "user", "key": "k",
                    "value": "v", "confidence": 0.9, "evidence": [], "ts": 1.0,
                    "last_used_at": 1.0, "use_count": 0}) + "\n"
        + "{ not valid json\n"
        + json.dumps({"id": "b", "type": "fact", "scope": "user", "key": "k2",
                      "value": "v2", "confidence": 0.5, "evidence": [], "ts": 2.0,
                      "last_used_at": 2.0, "use_count": 0}) + "\n",
        encoding="utf-8",
    )
    entries = mem_auto._read_jsonl(p)
    assert [e.id for e in entries] == ["a", "b"]


def test_append_then_read_roundtrip(mem_root):
    p = mem_root / "test.jsonl"
    e = mem_auto.MemoryEntry(
        id="m1", type="preference", scope="user", key="indent_style", value="tabs",
        confidence=0.95, evidence=("u said",), ts=100.0, last_used_at=100.0, use_count=0,
    )
    mem_auto._append_jsonl(p, e)
    got = mem_auto._read_jsonl(p)
    assert len(got) == 1
    assert got[0].key == "indent_style"
    assert got[0].value == "tabs"
    assert got[0].confidence == 0.95


def test_append_creates_parent_dirs(mem_root):
    p = mem_root / "deep" / "nested" / "x.jsonl"
    e = mem_auto.MemoryEntry(
        id="m1", type="fact", scope="user", key="k", value="v",
        confidence=0.5, evidence=(), ts=0.0, last_used_at=0.0, use_count=0,
    )
    mem_auto._append_jsonl(p, e)
    assert p.exists()
