from __future__ import annotations

from dataclasses import dataclass

from argos.context.tokens import token_estimate
from argos.i18n import t



def _prefix(key: str) -> str:
    s = t(key).lstrip()
    for cut in ("{", "\n"):
        i = s.find(cut)
        if i >= 0:
            s = s[:i]
    return s.rstrip()


def _markers() -> tuple[tuple[str, ...], tuple[str, ...], str]:
    tool = (_prefix("loop.exec.result"), _prefix("loop.exec.no_output"), _prefix("loop.exec.value_repr"))
    dead = (_prefix("loop.exec.exception"),)
    plan = _prefix("loop.todos.header")
    return tool, dead, plan


@dataclass(frozen=True, slots=True)
class CoreKeep:
    recent_turns: int = 6
    verify_cmd: str | None = None


@dataclass(frozen=True, slots=True)
class PruneResult:
    messages: list[dict]
    removed: int
    removed_tokens: int
    kept_core: int


def _bucket(content: str) -> str:
    c = (content or "").lstrip()
    tool_markers, dead_markers, plan_marker = _markers()
    if plan_marker and c.startswith(plan_marker):
        return "plan"
    for m in dead_markers:
        if m and c.startswith(m):
            return "dead_end"
    for m in tool_markers:
        if m and c.startswith(m):
            return "tool_output"
    return "keep"


def _stub_for(bucket: str) -> str:
    return {
        "tool_output": t("ctx.stub_tool"),
        "plan": t("ctx.stub_plan"),
        "dead_end": t("ctx.stub_dead"),
    }[bucket]


def prune_messages(
    messages: list[dict],
    *,
    core: CoreKeep,
    aggressiveness: float = 0.5,
) -> PruneResult:
    n = len(messages)
    if aggressiveness <= 0 or n == 0:
        return PruneResult(messages=list(messages), removed=0, removed_tokens=0, kept_core=n)

    recent = max(0, int(core.recent_turns))
    protected_tail_start = max(0, n - recent)
    fold_tool = aggressiveness > 0
    fold_more = aggressiveness >= 0.66

    last_plan_idx = -1
    for i, m in enumerate(messages):
        if _bucket(m.get("content") or "") == "plan":
            last_plan_idx = i

    out: list[dict] = []
    removed = 0
    removed_tokens = 0
    kept_core = 0
    for i, m in enumerate(messages):
        content = m.get("content") or ""
        is_core = (
            i == 0
            or i >= protected_tail_start
            or (core.verify_cmd and core.verify_cmd in content)
        )
        if is_core:
            kept_core += 1
            out.append(m)
            continue
        bucket = _bucket(content)
        do_fold = False
        if bucket == "tool_output" and fold_tool:
            do_fold = True
        elif bucket == "dead_end" and fold_more:
            do_fold = True
        elif bucket == "plan" and fold_more and i != last_plan_idx:
            do_fold = True
        if do_fold:
            stub = _stub_for(bucket)
            before, _ = token_estimate(content)
            after, _ = token_estimate(stub)
            removed += 1
            removed_tokens += max(0, before - after)
            out.append({**m, "content": stub})
        else:
            out.append(m)
    return PruneResult(
        messages=out, removed=removed, removed_tokens=removed_tokens, kept_core=kept_core,
    )
