"""Internal documentation."""
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Mapping

from argos.approval import ApprovalLevel
from argos.i18n import t

if TYPE_CHECKING:
    from argos.core.types import Verdict
    from argos.permissions.config import PermissionsConfig


class Zone(enum.Enum):
    """Internal documentation."""

    GREEN = "green"
    YELLOW = "yellow"
    RED = "red"


@dataclass(frozen=True, slots=True)
class AutonomyPolicy:
    """Internal documentation."""

    clarification_required: bool = True
    preauth: Mapping[str, bool] = field(default_factory=dict)
    slow_actions: frozenset = field(
        default_factory=lambda: frozenset({"test", "build", "deploy", "publish", "release"})
    )

    @staticmethod
    def from_permissions_config(config: "PermissionsConfig | None") -> "AutonomyPolicy":
        """Internal documentation."""
        if config is None:
            return AutonomyPolicy()
        return AutonomyPolicy(preauth=dict(config.preauth or {}))


def _is_slow_action(action: str, slow: frozenset) -> bool:
    a = (action or "").lower()
    return any(s in a for s in slow)


def _evaluator_decision(
    action: str,
    args: dict,
    config: "PermissionsConfig",
) -> tuple[str, str]:
    """Internal documentation."""
    try:
        from argos.permissions.evaluator import evaluate
        meta = evaluate(
            action, args,
            gate_level=ApprovalLevel.CONFIRM,
            config=config,
            workspace=None,
        )
        return (meta.decision, meta.trigger)
    except Exception:  # noqa: BLE001
        return ("ask", "evaluator_error")


def classify(
    *,
    action: str,
    args: dict,
    reversible: bool,
    verdict: "Verdict | None",
    config: "PermissionsConfig",
    policy: AutonomyPolicy,
    slow_action: bool | None = None,
    goal_vague: bool | None = None,
) -> tuple[Zone, str]:
    """Internal documentation."""
    if not reversible:
        return (Zone.RED, t("perm2.zone.irreversible"))

    decision, trigger = _evaluator_decision(action, args or {}, config)

    if decision == "deny":
        return (Zone.RED, t("perm2.zone.hard_deny", trigger=trigger))
    if decision == "ask" and (
        trigger.startswith("hard_rule:")
        or trigger.startswith("secret:")
    ):
        return (Zone.RED, t("perm2.zone.hard_deny", trigger=trigger))

    if verdict is not None and getattr(verdict, "status", None) == "unverifiable":
        return (Zone.RED, t("perm2.zone.unverifiable", trigger=trigger))

    if verdict is not None and getattr(verdict, "status", None) == "failed":
        return (Zone.RED, t("perm2.zone.failed", trigger=trigger))

    if decision == "ask" and policy.preauth.get(trigger) is True:
        return (Zone.GREEN, t("perm2.zone.preauth_green", trigger=trigger))

    if decision == "ask":
        return (Zone.RED, t("perm2.zone.ask_red", trigger=trigger))

    # 6. slow_action / goal_vague → YELLOW
    eff_slow = slow_action if slow_action is not None else _is_slow_action(action, policy.slow_actions)
    if eff_slow:
        return (Zone.YELLOW, t("perm2.zone.slow_yellow", action=action))
    if goal_vague:
        return (Zone.YELLOW, t("perm2.zone.vague_yellow"))

    return (Zone.GREEN, t("perm2.zone.green", trigger=trigger))


def on_unverifiable_completion(
    *,
    verify_cmd: str | None,
    verdict: "Verdict | None",
    policy: AutonomyPolicy,  # noqa: ARG001
) -> tuple[Zone, str] | None:
    """Internal documentation."""
    if verdict is None or getattr(verdict, "status", None) != "unverifiable":
        return None
    if not verify_cmd:
        return None
    detail = getattr(verdict, "detail", "") or ""
    return (
        Zone.RED,
        t("perm2.zone.unverifiable_completion", cmd=verify_cmd, detail=detail[:120]),
    )
