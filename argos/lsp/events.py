from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping


@dataclass(frozen=True, slots=True)
class LspServerEvent:
    server_name: str = ""
    status: str = ""
    command: str = ""
    exit_code: int | None = None
    elapsed_ms: int = 0
    error: str | None = None
    cwd: str = ""
    timestamp_ms: int = 0

    kind = "lsp_server_event"


@dataclass(frozen=True, slots=True)
class LspDiagnosticEvent:
    server_name: str = ""
    uri: str = ""
    count: int = 0
    severity_counts: Mapping[str, int] = field(default_factory=dict)
    cached: bool = False
    cwd: str = ""

    kind = "lsp_diagnostic_event"

