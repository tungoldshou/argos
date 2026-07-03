"""Internal documentation."""
from __future__ import annotations

from typing import TYPE_CHECKING

from argos.core.types import RiskLevel
from argos.i18n import t

if TYPE_CHECKING:
    from argos.capability.manifest import Capability, KindName, VisibilityName


class CapabilityRegistry:
    """Internal documentation."""

    def __init__(self) -> None:
        self._caps: dict[str, "Capability"] = {}

    # ------------------------------------------------------------------
    # ------------------------------------------------------------------

    def register(self, cap: "Capability") -> None:
        """Internal documentation."""
        if cap.risk is None:
            raise ValueError(t("cap.registry.register_no_risk", name=cap.name))
        if cap.name in self._caps:
            raise ValueError(t("cap.registry.register_duplicate", name=cap.name))
        self._caps[cap.name] = cap

    # ------------------------------------------------------------------
    # ------------------------------------------------------------------

    def get(self, name: str) -> "Capability":
        """Internal documentation."""
        try:
            return self._caps[name]
        except KeyError:
            raise KeyError(t("cap.registry.not_found", name=name)) from None

    def names(self) -> tuple[str, ...]:
        """Internal documentation."""
        return tuple(self._caps.keys())

    def callable_names(self) -> tuple[str, ...]:
        """Internal documentation."""
        return tuple(n for n, c in self._caps.items() if c.sandbox_callable)

    def by_kind(self, kind: "KindName") -> tuple["Capability", ...]:
        """Internal documentation."""
        return tuple(c for c in self._caps.values() if c.kind == kind)

    def risk_table(self) -> dict[str, RiskLevel]:
        """Internal documentation."""
        return {name: cap.risk for name, cap in self._caps.items()}  # type: ignore[return-value]

    def egress_hosts(self) -> frozenset[str]:
        """Internal documentation."""
        result: set[str] = set()
        for cap in self._caps.values():
            result.update(cap.egress_hosts)
        return frozenset(result)

    def visible_names(self, role: "VisibilityName") -> tuple[str, ...]:
        """Internal documentation."""
        if role == "developer":
            return tuple(self._caps.keys())
        return tuple(
            name for name, cap in self._caps.items() if cap.visibility == "all"
        )

    def __len__(self) -> int:
        return len(self._caps)

    def __contains__(self, name: object) -> bool:
        return name in self._caps
