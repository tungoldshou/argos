"""Internal documentation."""
from __future__ import annotations

from argos.i18n import t
from argos.skills_runtime.analysis import (
    AnalysisSkill,
    AnalysisSkillContext,
    AnalysisSkillResult,
    Finding,
)
from argos.skills_runtime.registry import (
    _reset_registry,
    get,
    list_all,
    register,
)

__all__ = [
    "AnalysisSkill",
    "AnalysisSkillContext",
    "AnalysisSkillResult",
    "Finding",
    "register",
    "get",
    "list_all",
    "run_skill",
    "register_builtin_skills",
]


async def run_skill(name, args, ctx, *, timeout_s=60.0, event_bus=None):  # type: ignore[no-untyped-def]
    """Internal documentation."""
    from argos.skills_runtime.runner import run_skill as _impl
    return await _impl(name, args, ctx, timeout_s=timeout_s, event_bus=event_bus)


def register_builtin_skills() -> None:
    """Internal documentation."""
    from argos.skills_runtime.analysis import AnalysisSkill
    from argos.skills_runtime.builtin import security_review, simplify
    from argos.skills_runtime.builtin.verify import run as _verify_run

    for name, run_fn, desc in [
        ("verify", _verify_run, t("skill.builtin_verify_desc")),
        ("security-review", security_review.run, t("skill.builtin_security_review_desc")),
        ("simplify", simplify.run, t("skill.builtin_simplify_desc")),
    ]:
        if get(name) is not None:
            continue
        try:
            register(AnalysisSkill(
                name=name,
                description=desc,
                parameters_schema={"path": "optional str", "top": "optional int"},
                run=run_fn,
                requires_approval=False,
            ))
        except ValueError:
            pass
