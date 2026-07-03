"""Internal documentation."""
from __future__ import annotations

from argos.skills_runtime.analysis import AnalysisSkill


_SKILLS: dict[str, AnalysisSkill] = {}


def register(skill: AnalysisSkill) -> None:
    """Internal documentation."""
    if skill.name in _SKILLS:
        raise ValueError(f"skill {skill.name!r} already registered")
    _SKILLS[skill.name] = skill


def get(name: str) -> AnalysisSkill | None:
    """Internal documentation."""
    return _SKILLS.get(name)


def list_all() -> list[AnalysisSkill]:
    """Internal documentation."""
    return list(_SKILLS.values())


def _reset_registry() -> None:
    """Internal documentation."""
    _SKILLS.clear()
