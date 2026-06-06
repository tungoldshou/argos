"""#10 T7 推荐引擎 (13 规则,纯启发式,无学习).

D19:无 LLM 反馈学习(留 v1.1)
R1-R13 见 spec 2026-06-07-skills-curator-design.md §8.3

不接 skills_runtime.AnalysisSkill;recommend 是元层(对 skill 选择),不是 skill 本身。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from argos_agent.skills_curator.index import IndexCache

_PY_FILE = re.compile(r"\.(py|pyi)$")
_TS_FILE = re.compile(r"\.(ts|tsx|js|jsx)$")
_SQL_FILE = re.compile(r"\.(sql)$")
_TEST_FILE = re.compile(r"(^|/)tests?/test_")


@dataclass(frozen=True, slots=True)
class SessionActivity:
    files_edited: tuple[str, ...] = ()
    verify_failures: int = 0
    commands_run: tuple[str, ...] = ()
    tools_called: tuple[str, ...] = ()
    skill_invocations: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Recommendation:
    name: str
    score: float
    reason: str
    in_index: bool
    description: str = ""


# ── 13 规则 ───────────────────────────────────────────────


def _r1_py_files(activity: SessionActivity) -> Recommendation | None:
    py_count = sum(1 for f in activity.files_edited if _PY_FILE.search(f))
    if py_count >= 3:
        return Recommendation(
            "python-lint", 1.0, f"编辑 {py_count} 个 .py 文件", True, ""
        )
    return None


def _r2_test_files(activity: SessionActivity) -> Recommendation | None:
    test_count = sum(1 for f in activity.files_edited if _TEST_FILE.search(f))
    if test_count >= 1:
        return Recommendation(
            "test-debugger", 1.0, f"编辑 {test_count} 个 test 文件", True, ""
        )
    return None


def _r3_verify_failures(activity: SessionActivity) -> Recommendation | None:
    if activity.verify_failures >= 1:
        return Recommendation(
            "test-debugger", 1.0, f"verify 失败 {activity.verify_failures} 次", True, ""
        )
    return None


def _r4_verify_failures_3plus(activity: SessionActivity) -> Recommendation | None:
    if activity.verify_failures >= 3:
        return Recommendation("simplify", 1.0, "verify 连续失败", True, "")
    return None


def _r5_ts_files(activity: SessionActivity) -> Recommendation | None:
    ts_count = sum(1 for f in activity.files_edited if _TS_FILE.search(f))
    if ts_count >= 2:
        return Recommendation(
            "ts-lint", 1.0, f"编辑 {ts_count} 个 TS 文件", True, ""
        )
    return None


def _r6_sql_files(activity: SessionActivity) -> Recommendation | None:
    sql_count = sum(1 for f in activity.files_edited if _SQL_FILE.search(f))
    if sql_count >= 1:
        return Recommendation(
            "sql-query-safety", 1.0, f"编辑 {sql_count} 个 .sql 文件", True, ""
        )
    return None


def _r7_git_commit(activity: SessionActivity) -> Recommendation | None:
    if any("git commit" in c for c in activity.commands_run):
        return Recommendation(
            "git-commit-hygiene", 1.0, "跑过 git commit", True, ""
        )
    return None


def _r8_web_search(activity: SessionActivity) -> Recommendation | None:
    if "web_search" in activity.tools_called:
        return Recommendation(
            "web-search-recipe", 1.0, "用过 web_search", True, ""
        )
    return None


def _r9_security_review_used(activity: SessionActivity) -> Recommendation | None:
    if "/security-review" in activity.skill_invocations:
        return Recommendation(
            "security-review-extended", 1.0, "已用 /security-review", True, ""
        )
    return None


def _r10_many_suffixes(activity: SessionActivity) -> Recommendation | None:
    exts = {Path(f).suffix for f in activity.files_edited}
    if len(exts) >= 5 and len(activity.files_edited) >= 5:
        return Recommendation(
            "simplify", 1.0, f"项目扩展 {len(exts)} 种后缀", True, ""
        )
    return None


def _r11_debug_pattern(activity: SessionActivity) -> Recommendation | None:
    if activity.verify_failures >= 2 and activity.tools_called.count("edit_file") >= 5:
        return Recommendation(
            "test-debugger", 1.0, "调试中(失败 + 多 edit)", True, ""
        )
    return None


def _r12_long_session(activity: SessionActivity) -> Recommendation | None:
    if len(activity.commands_run) + len(activity.tools_called) >= 30:
        return Recommendation("simplify", 1.0, "长 session,扫下死代码", True, "")
    return None


# R13 memory 接入留 v1.1


DEFAULT_RULES: tuple = (
    _r1_py_files, _r2_test_files, _r3_verify_failures, _r4_verify_failures_3plus,
    _r5_ts_files, _r6_sql_files, _r7_git_commit, _r8_web_search,
    _r9_security_review_used, _r10_many_suffixes, _r11_debug_pattern,
    _r12_long_session,
)


def recommend(
    activity: SessionActivity,
    *,
    installed: set[str],
    cache: IndexCache | None = None,
    rules: Iterable = DEFAULT_RULES,
) -> list[Recommendation]:
    """跑 13 规则 → 按 score 倒序返 Recommendation list.

    跳过已 enabled 安装的 skill(spec §8.4);in_index 字段标 false 若不在 cache.
    """
    from argos_agent.skills_curator.capabilities import list_installed

    enabled = {s.name for s in list_installed() if s.enabled}
    index_names: set[str] = set()
    if cache is not None:
        index_names = {e.name for e in cache.skills}

    acc: dict[str, Recommendation] = {}
    for rule in rules:
        rec = rule(activity)
        if rec is None:
            continue
        if rec.name in enabled:
            continue
        in_index = rec.name in index_names
        if rec.name in acc:
            old = acc[rec.name]
            acc[rec.name] = Recommendation(
                name=rec.name,
                score=old.score + rec.score,
                reason=old.reason + "; " + rec.reason,
                in_index=in_index,
            )
        else:
            acc[rec.name] = Recommendation(
                name=rec.name,
                score=rec.score,
                reason=rec.reason,
                in_index=in_index,
            )
    return sorted(acc.values(), key=lambda r: r.score, reverse=True)


def build_activity_from_session() -> SessionActivity:
    """v1: 简化为空 dataclass;v1.1 接 session_event_log."""
    return SessionActivity()


__all__ = [
    "DEFAULT_RULES",
    "Recommendation",
    "SessionActivity",
    "build_activity_from_session",
    "recommend",
]
