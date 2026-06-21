"""工作流结果模型 + 审批预览文案。预览字段必须与 spec 一致(诚实:审批所见即所跑)。"""
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
    # 任务:并行子 agent diff 摘要模式(默认 inline_diff=False)——
    # 完整 diff 落盘到 diff_ref(路径),output 不再含整段 diff;diff_summary 是
    # "N files changed, +X/-Y" 一句话摘要;diff_file_count 是改动文件数。
    # inline_diff=True 旧路径下三个字段全 None/0(diff 已 inline 在 output)。
    diff_ref: str | None = None
    diff_summary: str | None = None
    diff_file_count: int = 0


@dataclass(frozen=True, slots=True)
class StageResult:
    stage_id: str
    results: tuple[AgentResult, ...]
    # best_of_n 专用:同任务 N 个候选的"全本"。results 里只装 winner(通过的或最佳非通过),
    # 这里装全部,供人看"另外几个都跑了啥"。其它 op 时为空 tuple(向后兼容)。
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
    """根据 op 类型推断本阶段将起几个子 agent。"""
    if stage.op == "panel":
        return stage.voters
    if stage.op == "best_of_n":
        return max(1, stage.n or 3)
    if stage.op in ("fan_out", "pipeline"):
        n = len(stage.over) if isinstance(stage.over, tuple) else 1
        return max(1, n)
    return 1


def _model_of(agent: AgentTask | tuple[AgentTask, ...]) -> str:
    """取第一个 agent 的 model 标签;未设则显示 active(跟随当前活跃模型)。"""
    a = agent[0] if isinstance(agent, tuple) else agent
    return a.model or "active"


def render_preview(spec: WorkflowSpec) -> str:
    """审批模态用:逐 stage 列将起几个 agent、用什么模型、是否写/隔离。"""
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
