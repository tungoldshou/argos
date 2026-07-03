from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Literal, Mapping


Verdict = Literal["passed", "failed", "partial", "n_a", "skipped"]


@dataclass(frozen=True, slots=True)
class SkillRunStart:
    kind: ClassVar[str] = "skill_run_start"
    skill_name: str
    args: Mapping[str, object]
    cwd: str = ""
    timestamp_ms: int = 0


@dataclass(frozen=True, slots=True)
class SkillRunEnd:
    kind: ClassVar[str] = "skill_run_end"
    skill_name: str
    verdict: Verdict
    duration_ms: int
    finding_count: int
    error_count: int
    cwd: str = ""
    timestamp_ms: int = 0
