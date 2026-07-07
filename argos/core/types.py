from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

VerdictStatus = Literal["passed", "failed", "unverifiable"]
Phase = Literal["plan", "act", "verify", "report"]
PermissionModeName = Literal["smart", "full"]
DecisionKind = Literal["deny", "once", "session", "always"]
RiskLevel = Literal["low", "medium", "high"]
ModelTierName = str

TRIVIAL_VERIFY_BINS: frozenset[str] = frozenset({
    "echo", "true", "false", ":", "ls", "pwd", "cat", "printf", "head", "tail",
    "yes", "whoami", "date", "env", "sleep", "test", "[", "dirname", "basename",
})


@dataclass(frozen=True, slots=True)
class Verdict:
    status: VerdictStatus
    detail: str
    verify_cmd: str | None
    attempts: int
    tampered: list[str] = field(default_factory=list)
    self_verified: bool = False
    no_test: bool = False

    @staticmethod
    def passed(detail: str, verify_cmd: str | None, attempts: int) -> "Verdict":
        return Verdict(status="passed", detail=detail, verify_cmd=verify_cmd, attempts=attempts)

    @staticmethod
    def passed_self(detail: str, verify_cmd: str | None, attempts: int) -> "Verdict":
        return Verdict(
            status="passed", detail=detail, verify_cmd=verify_cmd,
            attempts=attempts, self_verified=True,
        )

    @property
    def is_user_verified(self) -> bool:
        return self.status == "passed" and not self.self_verified

    @staticmethod
    def failed(detail: str, verify_cmd: str | None, attempts: int) -> "Verdict":
        return Verdict(status="failed", detail=detail, verify_cmd=verify_cmd, attempts=attempts)

    @staticmethod
    def unverifiable(detail: str, tampered: list[str], attempts: int) -> "Verdict":
        return Verdict(
            status="unverifiable", detail=detail, verify_cmd=None,
            attempts=attempts, tampered=list(tampered),
        )

    @staticmethod
    def no_check(detail: str, attempts: int) -> "Verdict":
        return Verdict(
            status="unverifiable", detail=detail, verify_cmd=None,
            attempts=attempts, tampered=[], no_test=True,
        )
