"""Skills runtime(spec 2026-06-06):3 个 on-demand 自检原语(/verify / /security-review / /simplify)。

模块入口:
- `register(skill)` / `get(name)` / `list_all()` —— registry 单例
- `run_skill(name, args, ctx)` —— runner 编排(Task 2 实现)
- `register_builtin_skills()` —— 注册 3 个内置 skill(Task 8/9/10 实现)

builtin/ 子模块分离:本模块纯数据契约 + 编排;builtin/ 是具体 skill 实现。"""
from __future__ import annotations

from argos_agent.skills_runtime.analysis import (
    AnalysisSkill,
    AnalysisSkillContext,
    AnalysisSkillResult,
    Finding,
)
from argos_agent.skills_runtime.registry import (
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


def run_skill(name, args, ctx):  # type: ignore[no-untyped-def]
    """Task 2 实现。"""
    raise NotImplementedError("skills_runtime.run_skill 将在 Task 2 实现")


def register_builtin_skills() -> None:
    """Task 8/9/10 实现:注册 verify / security-review / simplify。"""
    raise NotImplementedError("skills_runtime.register_builtin_skills 将在 Task 8 实现")
