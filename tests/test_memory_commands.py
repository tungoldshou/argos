"""#9 T4: /remember / /forget / /memory 命令解析 + 副作用。"""
from __future__ import annotations

import time

import pytest

from argos_agent.memory import auto as mem_auto
from argos_agent.tui import commands as tui_cmd


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


# ── parse_remember / parse_forget ────────────────────────────────────────────
def test_parse_remember_text_only():
    out = mem_auto.parse_remember("用 tabs 而非 spaces")
    assert out is not None
    assert out.text == "用 tabs 而非 spaces"
    assert out.scope == "user"  # 默认


def test_parse_remember_with_project_keyword():
    out = mem_auto.parse_remember("本项目用 pytest 跑测")
    assert out is not None
    assert out.scope == "project"  # 检测到"项目"


def test_parse_remember_with_explicit_scope():
    out = mem_auto.parse_remember("--project build: pytest -q")
    assert out is not None
    assert out.scope == "project"
    assert out.key == "build"
    assert out.value == "pytest -q"


def test_parse_remember_empty_returns_none():
    assert mem_auto.parse_remember("") is None
    assert mem_auto.parse_remember("   ") is None


def test_parse_forget_by_id():
    out = mem_auto.parse_forget("mem_abc123")
    assert out is not None
    assert out.kind == "id"
    assert out.query == "mem_abc123"


def test_parse_forget_by_key():
    out = mem_auto.parse_forget("indent_style")
    assert out is not None
    assert out.kind == "key"
    assert out.query == "indent_style"


def test_parse_forget_empty_returns_none():
    assert mem_auto.parse_forget("") is None
    assert mem_auto.parse_forget("  ") is None


# ── remember() 副作用 ────────────────────────────────────────────────────────
def test_remember_writes_to_user_tier(mem_root):
    e = mem_auto.remember("用 tabs 而非 spaces")
    assert e.scope == "user"
    assert e.confidence == 1.0
    assert e.value == "用 tabs 而非 spaces"
    entries = mem_auto._read_jsonl(mem_auto._user_path())
    assert any(x.value == "用 tabs 而非 spaces" for x in entries)


def test_remember_detects_project_keyword(mem_root):
    e = mem_auto.remember("本项目 build 命令是 pytest -q")
    assert e.scope == "project"


def test_remember_respects_explicit_scope(mem_root, monkeypatch, tmp_path):
    pid = mem_auto.project_id_for(tmp_path)
    monkeypatch.setattr(mem_auto, "project_id_for", lambda cwd=None: pid)
    e = mem_auto.remember("build: pytest -q", scope="project", key="build",
                          project_id=pid)
    assert e.scope == "project"
    assert e.key == "build"


def test_remember_dedups_within_24h(mem_root):
    e1 = mem_auto.remember("用 tabs")
    e2 = mem_auto.remember("用 tabs")
    # 24h 内同 (scope,key,value) → 第二次返 None
    assert e2 is None


# ── forget() 副作用 ──────────────────────────────────────────────────────────
def test_forget_by_id_soft_deletes(mem_root):
    e1 = mem_auto.remember("记住这个")
    out = mem_auto.forget(e1.id)
    assert len(out) == 1
    assert out[0].id == e1.id
    # 软删:confidence=0
    entries = mem_auto._read_jsonl(mem_auto._user_path())
    target = next(x for x in entries if x.id == e1.id)
    assert target.confidence == 0.0


def test_forget_by_key_fuzzy(mem_root):
    e1 = mem_auto.remember("用 tabs", key="indent")
    e2 = mem_auto.remember("用 4 空格缩进", key="indent")
    out = mem_auto.forget("indent")
    # 两个都 key==indent → 都被软删
    assert len(out) >= 2


def test_forget_by_text_substring(mem_root):
    e1 = mem_auto.remember("用 tabs 而非 spaces")
    out = mem_auto.forget("tabs")
    assert len(out) >= 1


def test_forget_no_match_returns_empty(mem_root):
    out = mem_auto.forget("mem_doesnotexist")
    assert out == []


# ── TUI dispatch: parse_slash 识别 ───────────────────────────────────────────
def test_parse_slash_recognizes_remember():
    cmd = tui_cmd.parse_slash("/remember 用 tabs")
    assert cmd is not None
    assert cmd.name == "remember"
    assert cmd.arg == "用 tabs"
    assert cmd.known is True


def test_parse_slash_recognizes_forget():
    cmd = tui_cmd.parse_slash("/forget indent_style")
    assert cmd is not None
    assert cmd.name == "forget"
    assert cmd.known is True


def test_parse_slash_recognizes_memory():
    cmd = tui_cmd.parse_slash("/memory")
    assert cmd is not None
    assert cmd.name == "memory"
    assert cmd.known is True


def test_remember_not_in_command_help():
    """D16: /memory /remember /forget 不在 COMMAND_HELP(避免菜单过宽)。"""
    assert "memory" not in tui_cmd.COMMAND_HELP
    assert "remember" not in tui_cmd.COMMAND_HELP
    assert "forget" not in tui_cmd.COMMAND_HELP


# ── /memory view ─────────────────────────────────────────────────────────────
def test_view_all_lists_all_tiers(mem_root):
    mem_auto.remember("user pref: tabs")
    text = mem_auto.view_all()
    assert "[User memories]" in text
    assert "user pref: tabs" in text
    assert "[Skill memories]" in text


def test_view_all_marks_empty_tier(mem_root):
    text = mem_auto.view_all()
    # user / skill 空时标 (空)
    assert "(空)" in text


def test_view_all_includes_project_when_pid_given(mem_root, tmp_path):
    pid = mem_auto.project_id_for(tmp_path)
    mem_auto.capture_event("undo", project_id=pid, reason="test reason")
    text = mem_auto.view_all(project_id=pid)
    assert "[Project memories]" in text
    assert "undo" in text.lower()


def test_view_all_includes_session_when_sid_given(mem_root):
    e = mem_auto.remember("session memo")
    assert e is not None
    text = mem_auto.view_all(session_id="abc")
    assert "[Session memories]" in text
    # 空 session tier → (空)
    assert "(空)" in text


def test_memory_command_renders_to_transcript(mem_root):
    """TUI _memory_cmd 调 view_all 推到 transcript(只测函数,不动 widget)。"""
    from argos_agent.memory.auto import view_all
    text = view_all()
    assert "memories" in text


def test_memory_command_not_in_command_help():
    """D16: /memory 不在 COMMAND_HELP。"""
    assert "memory" not in tui_cmd.COMMAND_HELP


def test_memory_command_known_in_parse_slash():
    """D16: parse_slash 仍识别 /memory 为 known。"""
    cmd = tui_cmd.parse_slash("/memory")
    assert cmd is not None
    assert cmd.known is True
