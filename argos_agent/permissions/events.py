"""ApprovalDecision 事件 dataclass(投 EventBus,spec §2.7)。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

DecisionType = Literal["approved", "denied", "asked"]
ByType = Literal["rule", "allowlist", "denylist", "asklist", "level", "user", "secret"]


@dataclass(frozen=True, slots=True)
class ApprovalDecision:
    """approval 决策事件(投 TUI EventBus + audit log 复用字段)。"""
    tool: str
    args: str
    decision: DecisionType        # approved | denied | asked
    trigger: str                  # 标签:hard_rule:<n> / soft_allow:<m> / ...
    by: ByType
    rule_name: str | None = None
    secret_pattern: str | None = None
    risk: str = "medium"
    session_id: str = ""
