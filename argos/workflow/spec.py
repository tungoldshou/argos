from __future__ import annotations

import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from argos.core.types import TRIVIAL_VERIFY_BINS
from argos.i18n import t

_OPS = {"fan_out", "pipeline", "panel", "loop_until", "synthesize", "best_of_n"}
_SCOPES = {"read", "full"}
_ISOLATION = {"none", "worktree"}
_ROLES = ("explorer", "planner", "coder", "reviewer")
_MAX_CAP = 16
_MAX_STAGES = 12
_BEST_OF_N_DEFAULT = 3
_BEST_OF_N_MAX = _MAX_CAP


class WorkflowSpecError(ValueError):
    pass




_ROLE_READ_TOOLS = frozenset({
    "read_file", "search_files", "propose_verify", "update_plan",
})


@dataclass(frozen=True, slots=True)
class _RolePreset:

    name: str
    tool_allowlist: frozenset
    system_prompt: str
    max_steps: int
    read_only: bool
    requires_verify: bool


ROLE_PRESETS: dict[str, _RolePreset] = {
    "explorer": _RolePreset(
        name="explorer",
        tool_allowlist=_ROLE_READ_TOOLS,
        system_prompt=t("wf.role.explorer.system_prompt"),
        max_steps=12,
        read_only=True,
        requires_verify=False,
    ),
    "planner": _RolePreset(
        name="planner",
        tool_allowlist=_ROLE_READ_TOOLS,
        system_prompt=t("wf.role.planner.system_prompt"),
        max_steps=8,
        read_only=True,
        requires_verify=False,
    ),
    "coder": _RolePreset(
        name="coder",
        tool_allowlist=_ROLE_READ_TOOLS | frozenset({
            "write_file", "edit_file", "run_command",
            "browser_navigate", "browser_snapshot", "browser_click",
            "browser_type", "browser_screenshot", "mcp_call",
            "web_search", "web_extract", "propose_workflow",
            "lsp_definition", "lsp_references", "lsp_hover",
            "lsp_document_symbols", "lsp_workspace_symbols", "lsp_diagnostics",
        }),
        system_prompt=t("wf.role.coder.system_prompt"),
        max_steps=20,
        read_only=False,
        requires_verify=True,
    ),
    "reviewer": _RolePreset(
        name="reviewer",
        tool_allowlist=_ROLE_READ_TOOLS | frozenset({"run_command", "lsp_diagnostics"}),
        system_prompt=t("wf.role.reviewer.system_prompt"),
        max_steps=10,
        read_only=True,
        requires_verify=True,
    ),
}


@dataclass(frozen=True, slots=True)
class AgentTask:

    prompt: str
    model: str | None = None
    tool_scope: str = "read"
    isolation: str = "none"
    verify: str | None = None
    schema: dict | None = None
    role: Optional[str] = None
    role_overrides: dict = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Stage:

    id: str
    op: str
    agent: AgentTask | tuple[AgentTask, ...]
    over: tuple | dict | None = None
    voters: int = 1
    threshold: int = 1
    target: int | None = None
    max_dry_rounds: int = 2
    cap: int = 4
    n: int | None = None
    stagger_s: float = 0.5
    per_candidate_timeout_s: float = 1800.0


@dataclass(frozen=True, slots=True)
class WorkflowSpec:

    name: str
    description: str
    stages: tuple[Stage, ...]


def _parse_agent(raw: dict) -> AgentTask:
    if not isinstance(raw, dict) or "prompt" not in raw:
        raise WorkflowSpecError(t("wf.spec.agent_missing_prompt"))
    scope = raw.get("tool_scope", "read")
    if scope not in _SCOPES:
        raise WorkflowSpecError(t("wf.spec.invalid_tool_scope", scope=scope, scopes=_SCOPES))
    iso = raw.get("isolation", "none")
    if iso not in _ISOLATION:
        raise WorkflowSpecError(t("wf.spec.invalid_isolation", iso=iso))
    role = raw.get("role")
    if role is not None:
        if role not in _ROLES:
            raise WorkflowSpecError(t("wf.spec.invalid_role", role=role, roles=_ROLES))
        preset = ROLE_PRESETS[role]
        if "tool_scope" in raw:
            scope_implies_readonly = (scope == "read")
            if preset.read_only != scope_implies_readonly:
                raise WorkflowSpecError(
                    t(
                        "wf.spec.role_scope_conflict",
                        role=role,
                        scope=scope,
                        role_read_only=preset.read_only,
                        scope_read_only=scope_implies_readonly,
                    )
                )
    verify = raw.get("verify")
    if verify is not None:
        try:
            _vbin = Path(shlex.split(str(verify))[0]).name
        except (ValueError, IndexError):
            _vbin = ""
        if _vbin in TRIVIAL_VERIFY_BINS:
            raise WorkflowSpecError(
                t("wf.spec.trivial_verify", verify=verify)
            )
    return AgentTask(
        prompt=str(raw["prompt"]),
        model=raw.get("model"),
        tool_scope=scope,
        isolation=iso,
        verify=verify,
        schema=raw.get("schema"),
        role=role,
        role_overrides=raw.get("role_overrides", {}) or {},
    )


def parse_spec(raw: dict) -> WorkflowSpec:
    if not isinstance(raw, dict):
        raise WorkflowSpecError(t("wf.spec.not_a_dict"))
    name = str(raw.get("name") or "").strip()
    if not name:
        raise WorkflowSpecError(t("wf.spec.missing_name"))
    stages_raw = raw.get("stages")
    if not isinstance(stages_raw, list) or not stages_raw:
        raise WorkflowSpecError(t("wf.spec.missing_stages"))
    if len(stages_raw) > _MAX_STAGES:
        raise WorkflowSpecError(t("wf.spec.too_many_stages", max_stages=_MAX_STAGES))
    seen_ids: set[str] = set()
    stages: list[Stage] = []
    for sr in stages_raw:
        if not isinstance(sr, dict):
            raise WorkflowSpecError(t("wf.spec.stage_not_a_dict"))
        sid = str(sr.get("id") or "").strip()
        if not sid:
            raise WorkflowSpecError(t("wf.spec.stage_missing_id"))
        if sid in seen_ids:
            raise WorkflowSpecError(t("wf.spec.duplicate_stage_id", sid=sid))
        op = sr.get("op")
        if op not in _OPS:
            raise WorkflowSpecError(t("wf.spec.invalid_op", op=op, ops=_OPS))
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
                    t("wf.spec.invalid_over_ref", ref=ref)
                )
            over = {"from": ref}
        else:
            raise WorkflowSpecError(t("wf.spec.invalid_over", over=over_raw))
        agent_raw = sr.get("agent")
        if isinstance(agent_raw, list):
            agent: AgentTask | tuple[AgentTask, ...] = tuple(
                _parse_agent(a) for a in agent_raw
            )
        else:
            agent = _parse_agent(agent_raw)
        voters = max(1, int(sr.get("voters", 1)))
        threshold = max(1, int(sr.get("threshold", 1)))
        if op == "panel" and threshold > voters:
            raise WorkflowSpecError(
                t("wf.spec.panel_threshold_exceeds_voters", threshold=threshold, voters=voters)
            )
        cap = min(int(sr.get("cap", 4)), _MAX_CAP)
        if op == "best_of_n":
            try:
                n = int(sr.get("n", _BEST_OF_N_DEFAULT))
            except (TypeError, ValueError):
                raise WorkflowSpecError(
                    t("wf.spec.best_of_n_invalid", sid=sid, n=sr.get("n"))
                )
            n = max(1, min(n, _BEST_OF_N_MAX))
            n_val: int | None = n
        else:
            n_val = None
        stages.append(
            Stage(
                id=sid,
                op=op,
                agent=agent,
                over=over,
                voters=voters,
                threshold=threshold,
                target=sr.get("target"),
                max_dry_rounds=int(sr.get("max_dry_rounds", 2)),
                cap=max(1, cap),
                n=n_val,
                stagger_s=max(0.0, float(sr.get("stagger_s", 0.5))),
                per_candidate_timeout_s=max(0.1, float(sr.get("per_candidate_timeout_s", 1800.0))),
            )
        )
        seen_ids.add(sid)
    return WorkflowSpec(
        name=name,
        description=str(raw.get("description") or ""),
        stages=tuple(stages),
    )
