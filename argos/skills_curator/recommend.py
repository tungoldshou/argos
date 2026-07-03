"""Internal documentation."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from argos.i18n import t
from argos.skills_curator.index import IndexCache

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




def _r1_py_files(activity: SessionActivity) -> Recommendation | None:
    py_count = sum(1 for f in activity.files_edited if _PY_FILE.search(f))
    if py_count >= 3:
        return Recommendation(
            "python-lint", 1.0, t("skill.recommend_py_files", count=py_count), True, ""
        )
    return None


def _r2_test_files(activity: SessionActivity) -> Recommendation | None:
    test_count = sum(1 for f in activity.files_edited if _TEST_FILE.search(f))
    if test_count >= 1:
        return Recommendation(
            "test-debugger", 1.0, t("skill.recommend_test_files", count=test_count), True, ""
        )
    return None


def _r3_verify_failures(activity: SessionActivity) -> Recommendation | None:
    if activity.verify_failures >= 1:
        return Recommendation(
            "test-debugger", 1.0, t("skill.recommend_verify_fail", count=activity.verify_failures), True, ""
        )
    return None


def _r4_verify_failures_3plus(activity: SessionActivity) -> Recommendation | None:
    if activity.verify_failures >= 3:
        return Recommendation("simplify", 1.0, t("skill.recommend_verify_fail_3plus"), True, "")
    return None


def _r5_ts_files(activity: SessionActivity) -> Recommendation | None:
    ts_count = sum(1 for f in activity.files_edited if _TS_FILE.search(f))
    if ts_count >= 2:
        return Recommendation(
            "ts-lint", 1.0, t("skill.recommend_ts_files", count=ts_count), True, ""
        )
    return None


def _r6_sql_files(activity: SessionActivity) -> Recommendation | None:
    sql_count = sum(1 for f in activity.files_edited if _SQL_FILE.search(f))
    if sql_count >= 1:
        return Recommendation(
            "sql-query-safety", 1.0, t("skill.recommend_sql_files", count=sql_count), True, ""
        )
    return None


def _r7_git_commit(activity: SessionActivity) -> Recommendation | None:
    if any("git commit" in c for c in activity.commands_run):
        return Recommendation(
            "git-commit-hygiene", 1.0, t("skill.recommend_git_commit"), True, ""
        )
    return None


def _r8_web_search(activity: SessionActivity) -> Recommendation | None:
    if "web_search" in activity.tools_called:
        return Recommendation(
            "web-search-recipe", 1.0, t("skill.recommend_web_search"), True, ""
        )
    return None


def _r9_security_review_used(activity: SessionActivity) -> Recommendation | None:
    if "/security-review" in activity.skill_invocations:
        return Recommendation(
            "security-review-extended", 1.0, t("skill.recommend_security_review"), True, ""
        )
    return None


def _r10_many_suffixes(activity: SessionActivity) -> Recommendation | None:
    exts = {Path(f).suffix for f in activity.files_edited}
    if len(exts) >= 5 and len(activity.files_edited) >= 5:
        return Recommendation(
            "simplify", 1.0, t("skill.recommend_many_suffixes", count=len(exts)), True, ""
        )
    return None


def _r11_debug_pattern(activity: SessionActivity) -> Recommendation | None:
    if activity.verify_failures >= 2 and activity.tools_called.count("edit_file") >= 5:
        return Recommendation(
            "test-debugger", 1.0, t("skill.recommend_debug_pattern"), True, ""
        )
    return None


def _r12_long_session(activity: SessionActivity) -> Recommendation | None:
    if len(activity.commands_run) + len(activity.tools_called) >= 30:
        return Recommendation("simplify", 1.0, t("skill.recommend_long_session"), True, "")
    return None




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
    """Internal documentation."""
    from argos.skills_curator.capabilities import list_installed

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
    """Internal documentation."""
    return SessionActivity()


__all__ = [
    "DEFAULT_RULES",
    "Recommendation",
    "SessionActivity",
    "build_activity_from_session",
    "recommend",
]
