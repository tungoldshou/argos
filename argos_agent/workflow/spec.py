"""声明式工作流规格(IR)+ 校验。agent 经 propose_workflow({...}) 提议;parse_spec 把原始 dict
校验成不可变 spec —— fail-closed:任何非法字段/引用/枚举即抛 WorkflowSpecError(诚实拒,不起子 agent)。"""
from __future__ import annotations

from dataclasses import dataclass

# 合法 op 集合
_OPS = {"fan_out", "pipeline", "panel", "loop_until", "synthesize"}
# 合法 tool_scope 枚举
_SCOPES = {"read", "full"}
# 合法 isolation 枚举
_ISOLATION = {"none", "worktree"}
# 单 stage 并发上限
_MAX_CAP = 16
# 单 workflow 最大 stage 数
_MAX_STAGES = 12


class WorkflowSpecError(ValueError):
    """spec 校验失败(诚实 fail-closed)。"""


@dataclass(frozen=True, slots=True)
class AgentTask:
    """单个子 agent 任务描述。"""

    prompt: str
    model: str | None = None
    tool_scope: str = "read"
    isolation: str = "none"
    verify: str | None = None
    schema: dict | None = None


@dataclass(frozen=True, slots=True)
class Stage:
    """工作流中的一个执行阶段。"""

    id: str
    op: str
    agent: AgentTask | tuple[AgentTask, ...]
    over: tuple | dict | None = None
    voters: int = 1
    threshold: int = 1
    target: int | None = None
    max_dry_rounds: int = 2
    cap: int = 4


@dataclass(frozen=True, slots=True)
class WorkflowSpec:
    """完整工作流规格,不可变。"""

    name: str
    description: str
    stages: tuple[Stage, ...]


def _parse_agent(raw: dict) -> AgentTask:
    """解析并校验单个 agent 任务描述。"""
    if not isinstance(raw, dict) or "prompt" not in raw:
        raise WorkflowSpecError("agent 缺 prompt")
    scope = raw.get("tool_scope", "read")
    if scope not in _SCOPES:
        raise WorkflowSpecError(f"非法 tool_scope:{scope!r}(只允许 {_SCOPES})")
    iso = raw.get("isolation", "none")
    if iso not in _ISOLATION:
        raise WorkflowSpecError(f"非法 isolation:{iso!r}")
    return AgentTask(
        prompt=str(raw["prompt"]),
        model=raw.get("model"),
        tool_scope=scope,
        isolation=iso,
        verify=raw.get("verify"),
        schema=raw.get("schema"),
    )


def parse_spec(raw: dict) -> WorkflowSpec:
    """将原始 dict 解析为 WorkflowSpec,任何非法输入立即抛 WorkflowSpecError。"""
    if not isinstance(raw, dict):
        raise WorkflowSpecError("spec 必须是 dict")
    name = str(raw.get("name") or "").strip()
    if not name:
        raise WorkflowSpecError("spec 缺 name")
    stages_raw = raw.get("stages")
    if not isinstance(stages_raw, list) or not stages_raw:
        raise WorkflowSpecError("spec 缺非空 stages")
    if len(stages_raw) > _MAX_STAGES:
        raise WorkflowSpecError(f"stages 过多(>{_MAX_STAGES})")
    seen_ids: set[str] = set()
    stages: list[Stage] = []
    for sr in stages_raw:
        if not isinstance(sr, dict):
            raise WorkflowSpecError("stage 必须是 dict")
        sid = str(sr.get("id") or "").strip()
        if not sid:
            raise WorkflowSpecError("stage 缺 id")
        op = sr.get("op")
        if op not in _OPS:
            raise WorkflowSpecError(f"非法 op:{op!r}(只允许 {_OPS})")
        over_raw = sr.get("over")
        over: tuple | dict | None
        if over_raw is None:
            over = None
        elif isinstance(over_raw, list):
            over = tuple(over_raw)
        elif isinstance(over_raw, dict) and "from" in over_raw:
            ref = over_raw["from"]
            if ref not in seen_ids:
                raise WorkflowSpecError(
                    f"over.from 引用了不存在或非更早的 stage:{ref!r}"
                )
            over = {"from": ref}
        else:
            raise WorkflowSpecError(f"非法 over:{over_raw!r}")
        agent_raw = sr.get("agent")
        if isinstance(agent_raw, list):
            agent: AgentTask | tuple[AgentTask, ...] = tuple(
                _parse_agent(a) for a in agent_raw
            )
        else:
            agent = _parse_agent(agent_raw)
        voters = int(sr.get("voters", 1))
        threshold = int(sr.get("threshold", 1))
        if op == "panel" and threshold > voters:
            raise WorkflowSpecError(
                f"panel threshold({threshold})不可大于 voters({voters})"
            )
        cap = min(int(sr.get("cap", 4)), _MAX_CAP)
        stages.append(
            Stage(
                id=sid,
                op=op,
                agent=agent,
                over=over,
                voters=max(1, voters),
                threshold=max(1, threshold),
                target=sr.get("target"),
                max_dry_rounds=int(sr.get("max_dry_rounds", 2)),
                cap=max(1, cap),
            )
        )
        seen_ids.add(sid)
    return WorkflowSpec(
        name=name,
        description=str(raw.get("description") or ""),
        stages=tuple(stages),
    )
