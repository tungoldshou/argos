"""#9 T3: CLAUDE.md / AGENTS.md auto-walk + 合并 + secret redact。"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from argos.memory import auto as mem_auto


@pytest.fixture
def cwd_tree(monkeypatch, tmp_path):
    """建一个临时目录树用于 walk 测试。"""
    # 模拟 workspace 目录
    ws = tmp_path / "ws"
    ws.mkdir()
    yield ws


# ── walk_claude_md_files ─────────────────────────────────────────────────────
def test_walk_finds_own_dir(cwd_tree, monkeypatch):
    (cwd_tree / "CLAUDE.md").write_text("root rules", encoding="utf-8")
    out = mem_auto.walk_claude_md_files(cwd_tree)
    assert cwd_tree / "CLAUDE.md" in out


def test_walk_finds_parent_chain(cwd_tree, monkeypatch):
    """子目录里的 CLAUDE.md + 父目录里的 CLAUDE.md 都收。"""
    (cwd_tree / "CLAUDE.md").write_text("parent", encoding="utf-8")
    sub = cwd_tree / "sub"
    sub.mkdir()
    (sub / "CLAUDE.md").write_text("child", encoding="utf-8")
    out = mem_auto.walk_claude_md_files(sub)
    # 两个文件都在
    assert (sub / "CLAUDE.md") in out
    assert (cwd_tree / "CLAUDE.md") in out
    # 子优先于父(sub 比 parent 索引小)
    assert out.index(sub / "CLAUDE.md") < out.index(cwd_tree / "CLAUDE.md")


def test_walk_finds_both_claude_and_agents(cwd_tree, monkeypatch):
    (cwd_tree / "CLAUDE.md").write_text("c", encoding="utf-8")
    (cwd_tree / "AGENTS.md").write_text("a", encoding="utf-8")
    out = mem_auto.walk_claude_md_files(cwd_tree)
    assert (cwd_tree / "CLAUDE.md") in out
    assert (cwd_tree / "AGENTS.md") in out


def test_walk_skips_nonexistent(cwd_tree, monkeypatch):
    out = mem_auto.walk_claude_md_files(cwd_tree)
    assert out == []


def test_walk_handles_dot_git_like_dirs(cwd_tree, monkeypatch):
    """即使没 .git 也应正常 walk 到 root,不断。"""
    (cwd_tree / "CLAUDE.md").write_text("x", encoding="utf-8")
    out = mem_auto.walk_claude_md_files(cwd_tree)
    assert len(out) >= 1
    # 不会无限循环
    assert len(out) < 100  # 任意上限


# ── merge_claude_documents ───────────────────────────────────────────────────
def test_merge_returns_empty_when_no_files():
    out = mem_auto.merge_claude_documents([], global_paths=[])
    assert out == ""


def test_merge_includes_global_and_project(cwd_tree, monkeypatch):
    g = cwd_tree / "global.md"
    p = cwd_tree / "project.md"
    g.write_text("global rules", encoding="utf-8")
    p.write_text("project rules", encoding="utf-8")
    out = mem_auto.merge_claude_documents([p], global_paths=[g])
    assert "global rules" in out
    assert "project rules" in out
    assert "<memory_context>" in out
    assert "</memory_context>" in out


def test_merge_truncates_per_file_to_20k(cwd_tree, monkeypatch):
    p = cwd_tree / "big.md"
    p.write_text("x" * 25000, encoding="utf-8")
    out = mem_auto.merge_claude_documents([p])
    # 截到 20k 之内
    assert "<truncated>" in out
    # 单文件 <= 20k 字符(标记之后)
    assert len("x" * 25000) > 20000  # sanity


def test_merge_redacts_secrets(cwd_tree, monkeypatch):
    p = cwd_tree / "leaky.md"
    p.write_text(
        "我的 API key 是 sk-ant-api03-abcdefghijklmnopqrstuvwxyz1234567890ABCD\n"
        "Bearer ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnop\n"
        "正常的文本",
        encoding="utf-8",
    )
    out = mem_auto.merge_claude_documents([p])
    assert "sk-ant-api03" not in out
    assert "Bearer ABCDEF" not in out
    assert "<redacted" in out
    assert "正常的文本" in out


def test_merge_wraps_in_memory_context_tag(cwd_tree, monkeypatch):
    p = cwd_tree / "r.md"
    p.write_text("hi", encoding="utf-8")
    out = mem_auto.merge_claude_documents([p])
    assert out.startswith("<memory_context>")
    assert out.rstrip().endswith("</memory_context>")


# ── _global_claude / _global_agents ──────────────────────────────────────────
def test_global_claude_returns_argos_home_path(monkeypatch, tmp_path):
    monkeypatch.setattr(mem_auto, "_ARGOS_HOME", lambda: tmp_path / "ah")
    p = mem_auto._global_claude()
    assert p == tmp_path / "ah" / "CLAUDE.md"


def test_global_agents_returns_argos_home_path(monkeypatch, tmp_path):
    monkeypatch.setattr(mem_auto, "_ARGOS_HOME", lambda: tmp_path / "ah")
    p = mem_auto._global_agents()
    assert p == tmp_path / "ah" / "AGENTS.md"
