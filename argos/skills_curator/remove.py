"""#10 T4 remove 流程:backup_to_trash + builtin 保护 + 30d recoverable。

D7:builtin 3 名硬拒
D18:30d trash 提示
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from argos.skills_curator import index as _index_mod
from argos.skills_curator.index import BUILTIN_NAMES
from argos.skills_curator.install import InstallError, backup_to_trash

TRASH_TTL_S = 30 * 86400  # 30 days


@dataclass(frozen=True, slots=True)
class RemoveResult:
    name: str
    trash_path: Path
    recoverable_until: float


def remove(name: str, *, base_dir: Path | None = None) -> RemoveResult:
    if name in BUILTIN_NAMES:
        raise InstallError(
            f"protected_skill: {name!r} is builtin and cannot be removed"
        )
    root = base_dir or _index_mod._skills_root()
    target = root / name
    if not target.exists():
        raise InstallError(f"not_installed: {name!r}")
    if not (target / "SKILL.md").exists():
        raise InstallError(f"not_installed: {name!r} (no SKILL.md in {target})")

    actual = backup_to_trash(target, base_dir=root)
    return RemoveResult(
        name=name,
        trash_path=actual,
        recoverable_until=time.time() + TRASH_TTL_S,
    )


__all__ = ["RemoveResult", "remove"]
