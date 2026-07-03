"""Internal documentation."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

DecisionType = Literal["approved", "denied", "asked"]
ByType = Literal["rule", "allowlist", "denylist", "asklist", "level", "user", "secret"]


@dataclass(frozen=True, slots=True)
class ApprovalDecision:
    """Internal documentation."""
    tool: str
    args: str
    decision: DecisionType        # approved | denied | asked
    trigger: str
    by: ByType
    rule_name: str | None = None
    secret_pattern: str | None = None
    risk: str = "medium"
    session_id: str = ""

    kind = "approval_decision"
