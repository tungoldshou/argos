"""Internal documentation."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from argos.i18n import t


class PlanModeError(Exception):
    """Internal documentation."""


PlanExitAction = Literal["approve_start", "approve_accept_edits", "keep_planning", "refine"]
_VALID_ACTIONS = ("approve_start", "approve_accept_edits", "keep_planning", "refine")


def set_plan_mode(active: bool) -> None:
    """Internal documentation."""
    from argos import runtime as _rt
    ctx = _rt._current_var.get()
    if ctx is None:
        ctx = _rt._make_default_ctx()
        _rt._current_var.set(ctx)
    ctx.plan_mode = active


def is_plan_mode() -> bool:
    """Internal documentation."""
    from argos import runtime as _rt
    return _rt.current().plan_mode


@dataclass(frozen=True)
class PlanExitDecision:
    """Internal documentation."""
    action: PlanExitAction
    feedback: str | None = None

    def __post_init__(self):
        if self.action not in _VALID_ACTIONS:
            raise ValueError(
                t("plan.decision.invalid_action", valid=_VALID_ACTIONS, action=self.action)
            )


def EnterPlanMode(loop) -> str:
    """Internal documentation."""
    if getattr(loop, "_busy", False):
        return t("plan.enter.busy")
    if getattr(loop, "mode", "act") == "plan":
        return t("plan.enter.already")
    loop.mode = "plan"
    set_plan_mode(True)
    if hasattr(loop, "_emit_phase"):
        loop._emit_phase("plan")
    return t("plan.enter.ok")



def ExitPlanMode(loop, action: str, feedback: str | None = None) -> str:
    """Internal documentation."""
    if getattr(loop, "mode", "act") != "plan":
        return t("plan.exit.not_in_plan")
    if action == "refine" and not (feedback and feedback.strip()):
        return t("plan.exit.refine_no_feedback")
    try:
        decision = PlanExitDecision(action=action, feedback=feedback)
    except ValueError as e:
        return t("plan.exit.invalid_action", exc=e)
    loop.mode = "act"
    set_plan_mode(False)
    loop._plan_decision = decision
    ev = getattr(loop, "_plan_decision_event", None)
    if ev is not None:
        ev.set()
    return t("plan.exit.ok", action=action)


class PlanRenderer:
    """Internal documentation."""

    @staticmethod
    def render(
        goal: str,
        todos: list[dict],
        tool_calls: list[dict],
        risks: list[str] | None = None,
    ) -> str:
        """Internal documentation."""
        title = goal.strip()[:50] + ("..." if len(goal.strip()) > 50 else "")
        lines = [f"# Plan: {title}", ""]

        lines.append(t("plan.render.tasks"))
        if todos:
            for todo in todos:
                step = todo.get("step", "?")
                desc = todo.get("description", "")
                tool = todo.get("tool", "")
                tool_part = f"(tool: {tool})" if tool else ""
                lines.append(f"- [ ] **step {step}**: {desc} {tool_part}")
        else:
            lines.append(t("plan.render.no_tasks"))
        lines.append("")

        files_set = set()
        for tc in tool_calls:
            if tc.get("tool") in ("write_file", "edit_file", "read_file"):
                p = tc.get("args", {}).get("path")
                if p:
                    files_set.add(p)
        if files_set:
            lines.append(t("plan.render.files"))
            for f in sorted(files_set):
                lines.append(f"- `{f}`")
            lines.append("")

        if risks:
            lines.append(t("plan.render.risks"))
            for r in risks:
                lines.append(f"- {r}")
            lines.append("")

        if tool_calls:
            lines.append(t("plan.render.tool_calls"))
            for tc in tool_calls:
                tool = tc.get("tool", "?")
                args = tc.get("args", {})
                args_str = ", ".join(f"{k}={v!r}" for k, v in args.items()) if args else ""
                lines.append(f"- `{tool}({args_str})`")
            lines.append("")

        lines.extend([
            t("plan.render.approval"),
            t("plan.render.approval_prompt"),
            t("plan.render.approve_start"),
            t("plan.render.approve_edits"),
            t("plan.render.keep_planning"),
            t("plan.render.refine"),
        ])
        return "\n".join(lines)
