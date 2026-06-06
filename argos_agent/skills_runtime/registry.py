"""SkillRegistry 模块级单例(spec §2.1 / §2.6)。

- 单例 dict: name → AnalysisSkill
- 不可变 views:list_all() 返 list 副本(防 caller 旁路改)
- 同名重复注册 → ValueError(spec §2.1 frozen:runtime 不可改)
- 测试用 _reset_registry() 清空
- 对位 lsp._config / hooks._registry 模式"""
from __future__ import annotations

from argos_agent.skills_runtime.analysis import AnalysisSkill


_SKILLS: dict[str, AnalysisSkill] = {}


def register(skill: AnalysisSkill) -> None:
    """注册 skill;同名重复 → ValueError(防 silent 覆盖)。"""
    if skill.name in _SKILLS:
        raise ValueError(f"skill {skill.name!r} already registered")
    _SKILLS[skill.name] = skill


def get(name: str) -> AnalysisSkill | None:
    """按 name 拿 skill;不在 → None(不抛,让 caller 走 spec §3 skipped 路径)。"""
    return _SKILLS.get(name)


def list_all() -> list[AnalysisSkill]:
    """返当前所有 skill 的 list 副本(按注册顺序)。"""
    return list(_SKILLS.values())


def _reset_registry() -> None:
    """清空单例(测试用)。"""
    _SKILLS.clear()
