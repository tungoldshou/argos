from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Literal

from argos.core.types import RiskLevel
from argos.i18n import t

KindName = Literal["tool", "mcp", "computer", "browser", "hook", "skill", "lsp", "plugin"]

VisibilityName = Literal["all", "developer"]


@dataclass(frozen=True, slots=True)
class Capability:
    name: str
    kind: KindName
    risk: RiskLevel | None
    reversible: bool | None = None
    egress_hosts: tuple[str, ...] = field(default_factory=tuple)
    schema: dict[str, Any] | None = None
    verify_hint: str = ""
    visibility: VisibilityName = "all"
    dispatch: Callable[..., Any] | None = None
    sandbox_callable: bool = True

    def __post_init__(self) -> None:
        if not self.name or not self.name.strip():
            raise ValueError(t("cap.manifest.empty_name"))
        if self.kind not in (
            "tool", "mcp", "computer", "browser", "hook", "skill", "lsp", "plugin"
        ):
            raise ValueError(t("cap.manifest.invalid_kind", kind=self.kind))
        if self.visibility not in ("all", "developer"):
            raise ValueError(t("cap.manifest.invalid_visibility", visibility=self.visibility))
