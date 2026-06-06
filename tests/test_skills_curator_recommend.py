"""#10 T7 推荐引擎测试。"""
from __future__ import annotations

from pathlib import Path

import pytest

import argos_agent.skills_curator.index as _idx
import argos_agent.skills_curator.capabilities as _cap
from argos_agent.skills_curator.recommend import (
    DEFAULT_RULES,
    Recommendation,
    SessionActivity,
    build_activity_from_session,
    recommend,
)


def _install(*, name: str, enabled: bool = True, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(_idx, "_skills_root", lambda: tmp_path)
    d = tmp_path / name
    d.mkdir()
    (d / "SKILL.md").write_text(
        f"---\nname: {name}\nversion: 0.1.0\nauthor: t\n"
        f"description: x\ncapabilities: [read]\n"
        f"enabled: {str(bool(enabled)).lower()}\n---\n\n# body\n",
        encoding="utf-8",
    )


# ── 13 规则触发 ────────────────────────────────────────────


def test_r1_py_files_recommends_python_lint():
    a = SessionActivity(files_edited=("a.py", "b.py", "c.py"))
    recs = recommend(a, installed=set())
    assert any(r.name == "python-lint" for r in recs)


def test_r2_test_files_recommends_test_debugger():
    a = SessionActivity(files_edited=("tests/test_x.py",))
    recs = recommend(a, installed=set())
    assert any(r.name == "test-debugger" for r in recs)


def test_r3_verify_failures_recommends_test_debugger():
    a = SessionActivity(verify_failures=1)
    recs = recommend(a, installed=set())
    assert any(r.name == "test-debugger" for r in recs)


def test_r4_three_failures_also_recommends_simplify():
    a = SessionActivity(verify_failures=3)
    recs = recommend(a, installed=set())
    names = [r.name for r in recs]
    assert "test-debugger" in names
    assert "simplify" in names


def test_r5_ts_files_recommends_ts_lint():
    a = SessionActivity(files_edited=("x.ts", "y.tsx"))
    recs = recommend(a, installed=set())
    assert any(r.name == "ts-lint" for r in recs)


def test_r6_sql_files_recommends_sql_safety():
    a = SessionActivity(files_edited=("queries.sql",))
    recs = recommend(a, installed=set())
    assert any(r.name == "sql-query-safety" for r in recs)


def test_r7_git_commit_recommends_hygiene():
    a = SessionActivity(commands_run=("git commit -m 'x'",))
    recs = recommend(a, installed=set())
    assert any(r.name == "git-commit-hygiene" for r in recs)


def test_r8_web_search_recommends_recipe():
    a = SessionActivity(tools_called=("web_search",))
    recs = recommend(a, installed=set())
    assert any(r.name == "web-search-recipe" for r in recs)


def test_r9_security_review_recommends_extended():
    a = SessionActivity(skill_invocations=("/security-review",))
    recs = recommend(a, installed=set())
    assert any(r.name == "security-review-extended" for r in recs)


def test_r10_many_suffixes_recommends_simplify():
    a = SessionActivity(files_edited=("a.py", "b.ts", "c.js", "d.go", "e.rs", "f.md"))
    recs = recommend(a, installed=set())
    assert any(r.name == "simplify" for r in recs)


def test_r11_debug_pattern_recommends_test_debugger():
    a = SessionActivity(
        verify_failures=3, tools_called=tuple(["edit_file"] * 6),
    )
    recs = recommend(a, installed=set())
    names = [r.name for r in recs]
    assert "test-debugger" in names


def test_r12_long_session_recommends_simplify():
    a = SessionActivity(
        commands_run=tuple(["ls"] * 20), tools_called=tuple(["read"] * 15),
    )
    recs = recommend(a, installed=set())
    assert any(r.name == "simplify" for r in recs)


# ── 跳过/去重/聚合 ─────────────────────────────────────────


def test_recommend_skips_already_enabled_skills(tmp_path, monkeypatch):
    _install(name="python-lint", enabled=True, tmp_path=tmp_path, monkeypatch=monkeypatch)
    a = SessionActivity(files_edited=("a.py", "b.py", "c.py"))
    recs = recommend(a, installed=set())
    assert not any(r.name == "python-lint" for r in recs)


def test_recommend_includes_unreviewed_installed(tmp_path, monkeypatch):
    """已装但 enabled=false → 仍推荐(spec §8.4 unreviewed 段)."""
    _install(name="python-lint", enabled=False, tmp_path=tmp_path, monkeypatch=monkeypatch)
    a = SessionActivity(files_edited=("a.py", "b.py", "c.py"))
    recs = recommend(a, installed=set())
    assert any(r.name == "python-lint" for r in recs)


def test_recommend_returns_empty_when_no_match():
    a = SessionActivity()
    recs = recommend(a, installed=set())
    assert recs == []


def test_recommend_combines_scores_for_same_skill():
    """R1 + R2 都 hit python-lint(test) → 分数累加."""
    a = SessionActivity(
        files_edited=("a.py", "b.py", "c.py", "tests/test_x.py"),
        verify_failures=1,
    )
    recs = recommend(a, installed=set())
    # python-lint 只 hit R1;test-debugger hit R2 + R3 → 分数 2
    td = next((r for r in recs if r.name == "test-debugger"), None)
    assert td is not None
    assert td.score >= 1.5


def test_recommend_returns_sorted_by_score():
    a = SessionActivity(
        files_edited=("a.py", "b.py", "c.py"),
        verify_failures=1,
    )
    recs = recommend(a, installed=set())
    scores = [r.score for r in recs]
    assert scores == sorted(scores, reverse=True)


def test_build_activity_from_session_returns_empty():
    a = build_activity_from_session()
    assert a.files_edited == ()
    assert a.verify_failures == 0


def test_default_rules_is_tuple_of_12():
    """R13 memory 留 v1.1,本期 12 条."""
    assert len(DEFAULT_RULES) == 12
