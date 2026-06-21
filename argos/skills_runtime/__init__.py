"""Skills runtime(spec 2026-06-06):3 个 on-demand 自检原语(/verify / /security-review / /simplify)。

模块入口:
- `register(skill)` / `get(name)` / `list_all()` —— registry 单例
- `run_skill(name, args, ctx)` —— runner 编排(Task 2 实现)
- `register_builtin_skills()` —— 注册 3 个内置 skill(Task 8/9/10 实现)

builtin/ 子模块分离:本模块纯数据契约 + 编排;builtin/ 是具体 skill 实现。"""
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
    """统一 skill 入口(Task 2 实现)。"""
    from argos.skills_runtime.runner import run_skill as _impl
    return await _impl(name, args, ctx, timeout_s=timeout_s, event_bus=event_bus)


def register_builtin_skills() -> None:
    """注册 3 个内置 skill(verify / security-review / simplify);幂等。"""
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
