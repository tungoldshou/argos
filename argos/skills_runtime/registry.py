from __future__ import annotations

from argos.skills_runtime.analysis import AnalysisSkill


_SKILLS: dict[str, AnalysisSkill] = {}


def register(skill: AnalysisSkill) -> None:
    if skill.name in _SKILLS:
        raise ValueError(f"skill {skill.name!r} already registered")
    _SKILLS[skill.name] = skill


def get(name: str) -> AnalysisSkill | None:
    return _SKILLS.get(name)


def list_all() -> list[AnalysisSkill]:
    return list(_SKILLS.values())


def _reset_registry() -> None:
    _SKILLS.clear()
