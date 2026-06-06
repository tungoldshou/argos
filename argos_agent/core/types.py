"""类型基石(SHARED INTERFACE CONTRACT §0)——Phase 2-6 共用。

不变量:
1. 不可变:所有值对象用 @dataclass(frozen=True, slots=True)。
2. 三态 fail-closed:VerdictStatus 含 "unverifiable",绝不当 passed(spec §12.5)。
3. 回执不可伪造 / 一份事件三用——见 §1 events.py / §6 Verdict/Receipt(Phase 3)。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

VerdictStatus = Literal["passed", "failed", "unverifiable"]
Phase = Literal["plan", "act", "verify", "report"]
ApprovalLevelName = Literal["observe", "propose", "confirm", "auto"]
DecisionKind = Literal["deny", "once", "session", "always"]
RiskLevel = Literal["low", "medium", "high"]
# 模型 profile 名:自由字符串(已无 worker/premium 档位之分;就是 config.json 里的 profile 名)。
ModelTierName = str


@dataclass(frozen=True, slots=True)
class Verdict:
    """三态 verify 裁决(契约 §6.1;spec §12.5)。'unverifiable' 绝不当 passed。

    canonical 归属:types.py(契约 §6.1 指定)。
    verify_gate.py 重新导出此类以保持旧 import 路径(from argos_agent.core.verify_gate import Verdict)。
    """
    status: VerdictStatus
    detail: str
    verify_cmd: str | None
    attempts: int
    tampered: list[str] = field(default_factory=list)

    @staticmethod
    def passed(detail: str, verify_cmd: str | None, attempts: int) -> "Verdict":
        return Verdict(status="passed", detail=detail, verify_cmd=verify_cmd, attempts=attempts)

    @staticmethod
    def failed(detail: str, verify_cmd: str | None, attempts: int) -> "Verdict":
        return Verdict(status="failed", detail=detail, verify_cmd=verify_cmd, attempts=attempts)

    @staticmethod
    def unverifiable(detail: str, tampered: list[str], attempts: int) -> "Verdict":
        # 篡改 → 强制 unverifiable；verify_cmd 可能根本没跑，设 None。
        return Verdict(
            status="unverifiable", detail=detail, verify_cmd=None,
            attempts=attempts, tampered=list(tampered),
        )
