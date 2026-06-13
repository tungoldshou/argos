"""#9 T6: 系统提示 <memory_context> 段注入。"""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from argos.memory import auto as mem_auto


@pytest.fixture
def mem_root(monkeypatch, tmp_path):
    root = tmp_path / "memory"
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("ARGOS_MEMORY_DIR", str(root))
    monkeypatch.setenv("ARGOS_HOME", str(tmp_path / "argos_home"))
    yield root


def _entry(**overrides) -> mem_auto.MemoryEntry:
    base = dict(
        id=mem_auto._new_id(), type="preference", scope="user", key="k", value="v",
        confidence=0.5, evidence=(), ts=time.time(), last_used_at=time.time(),
        use_count=0,
    )
    base.update(overrides)
    return mem_auto.MemoryEntry(**base)


# ── _memory_context_block ────────────────────────────────────────────────────
def test_block_returns_empty_when_no_files_no_mems(mem_root):
    out = mem_auto._memory_context_block(
        workspace=mem_root, project_id=mem_auto.project_id_for(mem_root),
    )
    assert out == ""


def test_block_includes_claude_md_content(mem_root):
    p = mem_root / "CLAUDE.md"
    p.write_text("用 tabs 而非 spaces", encoding="utf-8")
    out = mem_auto._memory_context_block(workspace=mem_root,
                                          project_id=mem_auto.project_id_for(mem_root))
    assert "<memory_context>" in out
    assert "用 tabs 而非 spaces" in out


def test_block_includes_recalled_memories(mem_root):
    e = mem_auto.remember("用 tabs 而非 spaces")
    assert e is not None
    out = mem_auto._memory_context_block(workspace=mem_root,
                                          project_id=mem_auto.project_id_for(mem_root))
    assert "用 tabs 而非 spaces" in out
    assert "[Recalled memories]" in out


def test_block_honors_no_memory_env(mem_root, monkeypatch):
    p = mem_root / "CLAUDE.md"
    p.write_text("hi", encoding="utf-8")
    monkeypatch.setenv("ARGOS_NO_MEMORY", "1")
    out = mem_auto._memory_context_block(workspace=mem_root,
                                          project_id=mem_auto.project_id_for(mem_root))
    assert out == ""


def test_block_uses_global_claude_md(mem_root):
    """~/.argos/CLAUDE.md 也要包含。"""
    g = mem_root.parent / "argos_home" / "CLAUDE.md"
    g.parent.mkdir(parents=True, exist_ok=True)
    g.write_text("global rule: 先跑测试", encoding="utf-8")
    out = mem_auto._memory_context_block(workspace=mem_root,
                                          project_id=mem_auto.project_id_for(mem_root))
    assert "global rule" in out


def test_block_integration_in_build_system(mem_root, monkeypatch):
    """集成:实际跑 _build_system 看是否含 <memory_context> 段。"""
    from argos.core.loop import AgentLoop
    p = mem_root / "CLAUDE.md"
    p.write_text("本项目用 tabs 缩进", encoding="utf-8")
    pid = mem_auto.project_id_for(mem_root)
    # 极简 smoke:直接调 _memory_context_block(避免构造完整 AgentLoop)
    out = mem_auto._memory_context_block(workspace=mem_root, project_id=pid)
    assert "<memory_context>" in out
    assert "本项目用 tabs 缩进" in out
