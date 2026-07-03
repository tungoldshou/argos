from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from argos.conductor.orders import OrderAction
from argos.i18n import t

if TYPE_CHECKING:
    from argos.conductor.orders import StandingOrder


def _new_suggestion_id() -> str:
    return uuid.uuid4().hex


@dataclass(frozen=True, slots=True)
class ProactiveSuggestion:
    id: str
    order_id: str
    goal: str
    reason_human: str
    suggested_at: float
    requires_confirmation: bool
    action: OrderAction = "run"

    def __post_init__(self) -> None:
        if not self.requires_confirmation:
            raise ValueError(t("cond.proposal.requires_confirmation_true"))
        if self.action not in ("run", "dream"):
            raise ValueError(t("cond.proposal.action_invalid", action=self.action))


def propose(
    order: "StandingOrder",
    context: dict,
    *,
    clock: object = None,
) -> ProactiveSuggestion:
    import time as _t

    now: float = clock() if callable(clock) else _t.time()

    goal = _safe_format(order.goal_template, context)

    if order.kind == "schedule":
        reason = t("cond.proposal.reason_schedule", schedule=order.schedule, utterance=order.utterance)
    else:
        triggered_path = context.get("path", order.trigger_glob or "")
        reason = t("cond.proposal.reason_file", path=triggered_path, utterance=order.utterance)

    return ProactiveSuggestion(
        id=_new_suggestion_id(),
        order_id=order.id,
        goal=goal,
        reason_human=reason,
        suggested_at=now,
        requires_confirmation=True,
        action=order.action,
    )


def _safe_format(template: str, context: dict) -> str:
    import string

    class _SafeDict(dict):
        def __missing__(self, key: str) -> str:
            return "{" + key + "}"

    try:
        return string.Formatter().vformat(template, (), _SafeDict(context))
    except Exception:  # noqa: BLE001
        return template
