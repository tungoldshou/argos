from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable, Literal, Mapping, TYPE_CHECKING

from argos.i18n import t

if TYPE_CHECKING:
    from argos.core.loop import LoopState  # noqa: F401


Severity = Literal["error", "warning", "info"]
_SEV_VALUES: frozenset[str] = frozenset({"error", "warning", "info"})

Verdict = Literal["passed", "failed", "partial", "n_a", "skipped"]
_VERDICT_VALUES: frozenset[str] = frozenset({"passed", "failed", "partial", "n_a", "skipped"})

# duplicate / complexity / dead_code / verify / config
_CATEGORY_VALUES: frozenset[str] = frozenset({
    "secret", "dep_vuln", "dep_audit", "permission",
    "duplicate", "complexity", "dead_code", "verify", "config",
})


@dataclass(frozen=True, slots=True)
class Finding:
    severity: Severity
    category: str
    message: str
    file: str | None = None
    line: int | None = None
    snippet: str | None = None
    suggestion: str | None = None

    def __post_init__(self) -> None:
        if self.severity not in _SEV_VALUES:
            raise ValueError(t("skill.finding_severity_invalid", valid=_SEV_VALUES, value=self.severity))
        if self.snippet is not None and len(self.snippet) > 120:
            raise ValueError(t("skill.finding_snippet_too_long", length=len(self.snippet)))


@dataclass(frozen=True, slots=True)
class AnalysisSkillContext:
    workspace: Path
    approval_level: str
    run_id: str
    loop: "LoopState | None" = None


@dataclass(frozen=True, slots=True)
class AnalysisSkillResult:
    summary: str
    findings: tuple[Finding, ...]
    duration_ms: int
    errors: tuple[str, ...]
    verdict: Verdict
    raw: Mapping[str, object] | None = None

    def __post_init__(self) -> None:
        if self.verdict not in _VERDICT_VALUES:
            raise ValueError(t("skill.result_verdict_invalid", valid=_VERDICT_VALUES, value=self.verdict))
        if self.duration_ms < 0:
            raise ValueError(t("skill.result_duration_negative", value=self.duration_ms))


AnalysisSkillRun = Callable[[Mapping[str, object], AnalysisSkillContext], Awaitable[AnalysisSkillResult]]


@dataclass(frozen=True, slots=True)
class AnalysisSkill:
    name: str
    description: str
    parameters_schema: Mapping[str, object]
    run: AnalysisSkillRun
    requires_approval: bool

    def __post_init__(self) -> None:
        if not self.name or not all(c.isascii() and (c.isalnum() or c in "_-") for c in self.name):
            raise ValueError(t("skill.name_invalid", name=self.name))
