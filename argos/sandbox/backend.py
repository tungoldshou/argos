"""Internal documentation."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class ExecResult:
    """Internal documentation."""
    stdout: str
    value_repr: str
    exc: str

    @property
    def ok(self) -> bool:
        return self.exc == ""


@runtime_checkable
class SandboxBackend(Protocol):
    """Internal documentation."""

    def spawn(self, *, workspace: Path, namespace: dict[str, Any]) -> None:
        """Internal documentation."""
        ...

    def exec_code(self, code: str) -> ExecResult:
        """Internal documentation."""
        ...

    def close(self) -> None:
        """Internal documentation."""
        ...
