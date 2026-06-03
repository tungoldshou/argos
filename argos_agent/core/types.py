"""类型基石(SHARED INTERFACE CONTRACT §0)——Phase 2-6 共用。

不变量:
1. 不可变:所有值对象用 @dataclass(frozen=True, slots=True)。
2. 三态 fail-closed:VerdictStatus 含 "unverifiable",绝不当 passed(spec §12.5)。
3. 回执不可伪造 / 一份事件三用——见 §1 events.py / §6 Verdict/Receipt(Phase 3)。
"""
from __future__ import annotations

from typing import Literal

VerdictStatus = Literal["passed", "failed", "unverifiable"]
Phase = Literal["plan", "act", "verify", "report"]
ApprovalLevelName = Literal["observe", "propose", "confirm", "auto"]
DecisionKind = Literal["deny", "once", "session", "always"]
RiskLevel = Literal["low", "medium", "high"]
ModelTierName = Literal["worker", "premium"]
