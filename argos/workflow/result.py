"""Internal documentation."""
from __future__ import annotations

from dataclasses import dataclass

from argos.i18n import t
from argos.workflow.spec import AgentTask, Stage, WorkflowSpec


@dataclass(frozen=True, slots=True)
class AgentResult:
    agent_id: str
    ok: bool
    output: object
    verdict: str | None = None
    error: str | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    diff_ref: str | None = None
    diff_summary: str | None = None
    diff_file_count: int = 0


@dataclass(frozen=True, slots=True)
class StageResult:
    stage_id: str
    results: tuple[AgentResult, ...]
    candidates: tuple[AgentResult, ...] = ()


@dataclass(frozen=True, slots=True)
class WorkflowResult:
    name: str
    stages: tuple[StageResult, ...]
    synthesis: str
    total_tokens_in: int
    total_tokens_out: int
    notes: tuple[str, ...]


def _agent_count(stage: Stage) -> int:
    """Internal documentation."""
    if stage.op == "panel":
        return stage.voters
    if stage.op == "best_of_n":
        return max(1, stage.n or 3)
    if stage.op in ("fan_out", "pipeline"):
        n = len(stage.over) if isinstance(stage.over, tuple) else 1
        return max(1, n)
    return 1


def _model_of(agent: AgentTask | tuple[AgentTask, ...]) -> str:
    """Internal documentation."""
    a = agent[0] if isinstance(agent, tuple) else agent
    return a.model or "active"


def render_preview(spec: WorkflowSpec) -> str:
    """Internal documentation."""
    lines = [
        t("wf.result.preview_header", name=spec.name, description=spec.description),
        t("wf.result.preview_will_run"),
    ]
    total = 0
    for s in spec.stages:
        n = _agent_count(s)
        total += n
        a = s.agent[0] if isinstance(s.agent, tuple) else s.agent
        scope = t("wf.result.preview_scope_write") if a.tool_scope == "full" else t("wf.result.preview_scope_read")
        iso = t("wf.result.preview_worktree_iso") if a.isolation == "worktree" else ""
        lines.append(
            t(
                "wf.result.preview_stage_line",
                op=s.op,
                stage_id=s.id,
                n=n,
                model=_model_of(s.agent),
                scope=scope,
                iso=iso,
            )
        )
    lines.append(t("wf.result.preview_footer", total=total))
    return "\n".join(lines)
